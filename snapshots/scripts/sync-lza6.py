#!/usr/bin/env python3
"""
subs-check 智能源同步器 v2

合并:
  - 抓 README + 评分 + 写 sub-urls.txt
  - sub-urls.txt → config.yaml + reload subs-check
  (不再依赖外部 shell 脚本)

状态机 (3 态):
  candidate (新加入或黑名单到期)
    ├─ 连续 3 轮失败 → blacklisted (锁 30 天, 自动解封后回 candidate)
    └─ 连续 30 轮通过 → whitelisted (优先选, 失败容忍度高)
  whitelisted
    └─ 连续 60 轮失败 → blacklisted (即便白名单也封)
  blacklisted
    └─ 30 天到期 → candidate (重置计数器)

抓取优化:
  - 用 ETag/If-None-Match 304 short-circuit, README 没变就只跑状态机扫描

输出:
  - sub-urls.txt (评分系统的 source-of-truth)
  - config.yaml.sub-urls (subs-check 的实际输入)
  - subs-check 重启 (只在源列表真变化时)
"""
import os
import re
import sys
import sqlite3
import urllib.request
import urllib.error
import subprocess
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ============= 配置 =============
LZA6_README = "https://raw.githubusercontent.com/lza6/free-VPN/main/README.md"
TARGET_FILE = "/opt/subs-check/config/sub-urls.txt"
CONFIG_YAML = "/opt/subs-check/config/config.yaml"
WHITELIST_USER = "/opt/subs-check/config/sub-urls-whitelist.txt"   # 用户固定保留 (高于自动白)
SCORE_DB = "/opt/subs-check/scripts/source-scores.db"
SUBS_LOG_DIR = "/var/log"
SUBS_LOG_GLOB = "subs-check*"

MAX_SOURCES = 80                  # 最终选源数量上限
FAIL_THRESHOLD_CANDIDATE = 3       # 候选池连续失败 N 轮 → 拉黑
PASS_THRESHOLD_PROMOTE = 30        # 候选池连续通过 N 轮 → 升白
FAIL_THRESHOLD_WHITELIST = 60      # 白名单连续失败 N 轮 → 拉黑
BLACKLIST_DAYS = 30                # 黑名单到期时间
FETCH_TIMEOUT = 15

# v2.3 减分常量
SOURCE_DEFAULT_SCORE = 100.0       # 默认满分起步
SOURCE_FETCH_FAIL_PENALTY = 15     # 拉取失败 (HTTP 4xx/5xx/timeout)
SOURCE_PARSE_EMPTY_PENALTY = 10    # 拉取成功但解析后 0 节点 (按 v2.3 设计区分, 此处沿用 fail_urls 整体处理)

DOMAIN_BLACKLIST = {'openproxylist.com', 'git.io'}
KEYWORD_BLACKLIST = [
    '/socks', '/http.txt', '/https.txt',
    '/socks4.txt', '/socks5.txt',
    'hideip.me', 'BreakingTechFr', 'zloi-user',
]
URL_PATTERN = re.compile(r'https?://[^\s<>")\]\']+')


# ============= DB =============
SCHEMA_TABLE = """
CREATE TABLE IF NOT EXISTS sources (
    url TEXT PRIMARY KEY,
    first_seen TEXT,
    last_seen TEXT,
    last_in_subs_check TEXT,
    consecutive_fails INTEGER DEFAULT 0,
    consecutive_passes INTEGER DEFAULT 0,
    total_checks INTEGER DEFAULT 0,
    total_passes INTEGER DEFAULT 0,
    score REAL DEFAULT 100.0,
    status TEXT DEFAULT 'candidate',
    blocked_until TEXT,
    consecutive_low_quality INTEGER DEFAULT 0,
    low_score_total INTEGER DEFAULT 0,
    note TEXT
);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);
"""

SCHEMA_INDEX = """
CREATE INDEX IF NOT EXISTS idx_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_score ON sources(score DESC);
"""

MIGRATIONS = [
    "ALTER TABLE sources ADD COLUMN consecutive_passes INTEGER DEFAULT 0",
    "ALTER TABLE sources ADD COLUMN status TEXT DEFAULT 'candidate'",
    "ALTER TABLE sources ADD COLUMN blocked_until TEXT",
    "ALTER TABLE sources ADD COLUMN consecutive_low_quality INTEGER DEFAULT 0",
    "ALTER TABLE sources ADD COLUMN low_score_total INTEGER DEFAULT 0",   # v2.3
]


def get_db():
    Path(SCORE_DB).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(SCORE_DB)
    # 1. 建表 (旧库已有不会覆盖)
    db.executescript(SCHEMA_TABLE)
    # 2. 迁移新列 (旧库可能缺)
    for sql in MIGRATIONS:
        try:
            db.execute(sql)
        except sqlite3.OperationalError:
            pass
    db.commit()
    # 3. 最后才建索引 (此时所有列都已就位)
    db.executescript(SCHEMA_INDEX)
    db.commit()
    return db


def get_meta(db, key, default=None):
    row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(db, key, value):
    now = datetime.now(timezone.utc).isoformat()
    db.execute("""
        INSERT INTO metadata (key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
    """, (key, str(value), now))
    db.commit()


# ============= 抓 lza6 (含 ETag 短路) =============
def fetch_readme(db):
    """
    返回 (changed: bool, text: str|None, etag: str|None)
    changed=False 时 text=None, 不重新抓
    """
    last_etag = get_meta(db, 'lza6_etag')
    headers = {'User-Agent': 'subs-check-syncer/2.0'}
    if last_etag:
        headers['If-None-Match'] = last_etag

    req = urllib.request.Request(LZA6_README, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
            new_etag = r.headers.get('ETag')
            text = r.read().decode('utf-8', errors='ignore')
            return True, text, new_etag
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return False, None, last_etag
        raise


# ============= URL 提取 + 黑名单 =============
def extract_subscription_urls(text):
    urls = URL_PATTERN.findall(text)
    out = set()
    for u in urls:
        u = u.rstrip('),.;:!?)\'"]>')
        if not re.search(
            r'(raw\.githubusercontent\.com|fastly\.jsdelivr|cdn\.jsdelivr|gist\.github|/raw/|/sub|subscribe|/clash|/v2ray|/proxies|\.yaml|\.yml|\.txt)',
            u, re.I
        ):
            continue
        if any(b in u.lower() for b in ['/blob/', '/tree/', '/wiki/', '/issues', '/pull']):
            if '/blob/' in u:
                u = u.replace('github.com', 'raw.githubusercontent.com').replace('/blob/', '/')
            else:
                continue
        out.add(u)
    return sorted(out)


def filter_blacklist(urls):
    survivors = []
    rejected = []
    for u in urls:
        try:
            domain = u.split('/')[2].lower()
        except IndexError:
            rejected.append((u, 'malformed'))
            continue
        if any(b in domain for b in DOMAIN_BLACKLIST):
            rejected.append((u, f'domain blacklist:{domain}'))
            continue
        if any(k.lower() in u.lower() for k in KEYWORD_BLACKLIST):
            rejected.append((u, 'keyword blacklist'))
            continue
        survivors.append(u)
    return survivors, rejected


def upsert_seen(db, urls):
    now = datetime.now(timezone.utc).isoformat()
    for u in urls:
        db.execute("""
            INSERT INTO sources (url, first_seen, last_seen)
            VALUES (?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET last_seen = excluded.last_seen
        """, (u, now, now))
    db.commit()


# ============= 评分 + 状态机 =============
def parse_subs_check_failures():
    """
    扫 subs-check journalctl 失败的 URL 集合 (本次 sync 周期内的, 24h 窗)
    """
    fail_urls = set()
    try:
        out = subprocess.check_output(
            ['journalctl', '-u', 'subs-check',
             '--since', '24 hours ago',
             '--no-pager', '-o', 'cat'],
            stderr=subprocess.DEVNULL, timeout=10
        ).decode('utf-8', errors='ignore')
    except Exception:
        return fail_urls

    for line in out.splitlines():
        m = re.search(r'(?:ERR|WRN).*?url=(https?://\S+)', line)
        if m:
            fail_urls.add(m.group(1).rstrip('"\''))
    return fail_urls


def apply_state_machine(db):
    """
    v2.3 状态机: 根据失败/通过结果更新 sources 表 (信号 A 网络可达性)

    规则:
      失败一次:  score -= 15 (SOURCE_FETCH_FAIL_PENALTY), consecutive_fails+1, consecutive_passes=0
      通过一次:  score 不变, consecutive_passes+1, consecutive_fails=0  (满分起步无需累加)
      candidate AND fails >= 3:  → blacklisted 30 天 (触发点 ①)
      whitelisted AND fails >= 60:  → blacklisted 30 天 (触发点 ②)
      candidate AND passes >= 30:  → whitelisted, 升白时清零所有计数器
      黑名单到期: 完整复活 (score=100, fails=passes=lq=lst=0)

    返回 (n_failed, n_passed, n_promoted, n_demoted, n_unblocked) 统计
    """
    fail_urls = parse_subs_check_failures()

    # === 黑名单到期完整复活 (v2.3: score 重置 100, low_score_total 清零) ===
    now = datetime.now(timezone.utc)
    n_unblocked = 0
    for row in db.execute("""
        SELECT url FROM sources WHERE status='blacklisted' AND blocked_until IS NOT NULL
    """).fetchall():
        url = row[0]
        bu = db.execute("SELECT blocked_until FROM sources WHERE url=?", (url,)).fetchone()[0]
        if bu and datetime.fromisoformat(bu) <= now:
            db.execute("""
                UPDATE sources SET
                    status='candidate',
                    blocked_until=NULL,
                    score=?,
                    consecutive_fails=0,
                    consecutive_passes=0,
                    consecutive_low_quality=0,
                    low_score_total=0
                WHERE url=?
            """, (SOURCE_DEFAULT_SCORE, url))
            n_unblocked += 1

    # 取当前 sub-urls.txt 里的, 这些是 "应该被测过的"
    current = set()
    if os.path.exists(TARGET_FILE):
        with open(TARGET_FILE) as f:
            current = {l.strip() for l in f if l.strip() and not l.startswith('#')}

    n_failed = n_passed = n_promoted = n_demoted = 0

    # 对当前清单中每个源判定 fail/pass 然后状态机
    for url in current:
        if url in fail_urls:
            # === v2.3 失败: score -=15, consecutive_fails+1 ===
            db.execute("""
                UPDATE sources SET
                    consecutive_fails = consecutive_fails + 1,
                    consecutive_passes = 0,
                    total_checks = total_checks + 1,
                    score = MAX(0, score - ?)
                WHERE url=?
            """, (SOURCE_FETCH_FAIL_PENALTY, url))
            n_failed += 1
            # 状态转移 (失败方向)
            row = db.execute(
                "SELECT status, consecutive_fails FROM sources WHERE url=?", (url,)
            ).fetchone()
            if row:
                status, fails_n = row
                if status == 'candidate' and fails_n >= FAIL_THRESHOLD_CANDIDATE:
                    until = (now + timedelta(days=BLACKLIST_DAYS)).isoformat()
                    db.execute("""
                        UPDATE sources SET status='blacklisted', blocked_until=?
                        WHERE url=?
                    """, (until, url))
                    n_demoted += 1
                elif status == 'whitelisted' and fails_n >= FAIL_THRESHOLD_WHITELIST:
                    until = (now + timedelta(days=BLACKLIST_DAYS)).isoformat()
                    db.execute("""
                        UPDATE sources SET status='blacklisted', blocked_until=?
                        WHERE url=?
                    """, (until, url))
                    n_demoted += 1
        else:
            # === v2.3 通过: score 不变 (满分起步无需累加), 仅累加 consecutive_passes ===
            db.execute("""
                UPDATE sources SET
                    consecutive_passes = consecutive_passes + 1,
                    consecutive_fails = 0,
                    total_checks = total_checks + 1,
                    total_passes = total_passes + 1
                WHERE url=?
            """, (url,))
            n_passed += 1
            # 状态转移 (升白) - v2.3: 升白时清零所有计数器
            row = db.execute(
                "SELECT status, consecutive_passes FROM sources WHERE url=?", (url,)
            ).fetchone()
            if row:
                status, passes_n = row
                if status == 'candidate' and passes_n >= PASS_THRESHOLD_PROMOTE:
                    db.execute("""
                        UPDATE sources SET
                            status='whitelisted',
                            score=?,
                            consecutive_fails=0,
                            consecutive_low_quality=0,
                            low_score_total=0
                        WHERE url=?
                    """, (SOURCE_DEFAULT_SCORE, url))
                    n_promoted += 1

    db.commit()
    return n_failed, n_passed, n_promoted, n_demoted, n_unblocked


# ============= 选源 =============
def load_user_whitelist():
    if not os.path.exists(WHITELIST_USER):
        return []
    with open(WHITELIST_USER) as f:
        return [l.strip() for l in f if l.strip() and not l.startswith('#')]


def select_sources(db, max_n=MAX_SOURCES):
    """选源策略 v3 (v2.3 评分规则配套, 2026-05-26):

    优先级 (黑名单永远跳过, 自动补齐到 max_n):
      1. 用户白名单 (文件顺序, 永久保留)
      2. status='whitelisted' 自动白
         按 score DESC, consecutive_passes DESC, total_passes DESC
      3. 探索预算: candidate 中 total_checks=0 的"未测过"源
         按 first_seen ASC (先来先测), 这一层确保所有新源至少被轮训一次
      4. 公平轮训 + 低分翻身 (v2.3 用户原话):
         按 total_checks ASC (公平: 测得越少越优先)
            score ASC          (同次数下低分先翻身)
            consecutive_passes DESC (同分下长期稳定优先)
            first_seen ASC

    设计目标:
      - 每轮固定 max_n (80) 个源, 黑名单触发后从下一层自动补齐
      - 全部源在约 12-18h (2-3 轮) 内被首次轮训
      - 之后稳态: 测得最少+低分先 → 自然轮训, 高分老源不饿死 (consecutive_passes 兜底)
      - 僵尸源由 v2.3 触发点 ④ (low_score_total >= 15) 兜底拉黑, 不靠排序冷处理
    """
    user_wl = load_user_whitelist()
    seen = set(user_wl)
    final = list(user_wl)
    layer_stats = {'user_wl': len(user_wl), 'auto_wl': 0, 'unexplored': 0, 'tested': 0}

    def add_from(rows, layer_key):
        for row in rows:
            if len(final) >= max_n:
                return True  # 满了
            if row[0] not in seen:
                final.append(row[0])
                seen.add(row[0])
                layer_stats[layer_key] += 1
        return False

    # 2. 系统白名单
    full = add_from(db.execute("""
        SELECT url FROM sources
        WHERE status='whitelisted'
        ORDER BY score DESC, consecutive_passes DESC, total_passes DESC
    """).fetchall(), 'auto_wl')
    if full:
        return final, len(user_wl), layer_stats

    # 3. 探索预算: 未测过的 candidate (公平轮训, first_seen ASC)
    full = add_from(db.execute("""
        SELECT url FROM sources
        WHERE status='candidate' AND total_checks=0
        ORDER BY first_seen ASC, url ASC
    """).fetchall(), 'unexplored')
    if full:
        return final, len(user_wl), layer_stats

    # 4. v2.3 公平轮训 + 低分翻身
    add_from(db.execute("""
        SELECT url FROM sources
        WHERE status='candidate' AND total_checks>0
        ORDER BY total_checks ASC,
                 score ASC,
                 consecutive_passes DESC,
                 first_seen ASC
    """).fetchall(), 'tested')

    return final, len(user_wl), layer_stats


# ============= 写 sub-urls.txt =============
def write_sub_urls(urls, user_wl_count, is_unchanged):
    backup = None
    if os.path.exists(TARGET_FILE):
        backup = f"{TARGET_FILE}.bak.{datetime.now():%Y%m%d-%H%M%S}"
        # 只在内容真变化时备份
        with open(TARGET_FILE) as f:
            old_urls = [l.strip() for l in f if l.strip() and not l.startswith('#')]
        if old_urls == urls:
            return False, backup  # 没变化
        os.rename(TARGET_FILE, backup)

    with open(TARGET_FILE, 'w') as f:
        f.write(f"# Auto-synced by sync-lza6-v2.py at {datetime.now()}\n")
        f.write(f"# 选源: 用户白 {user_wl_count} + 自动白/候选 {len(urls)-user_wl_count}\n")
        f.write(f"# 黑名单 30 天 TTL, 详见 source-scores.db\n#\n")
        for u in urls:
            f.write(f"{u}\n")
    return True, backup


# ============= 同步 config.yaml + reload =============
def sync_config_yaml_and_reload(urls, dry_run=False):
    if dry_run:
        print(f"  [dry-run] 不同步 config.yaml")
        return False

    import yaml
    cfg_backup = f"{CONFIG_YAML}.bak.{datetime.now():%Y%m%d-%H%M%S}"
    try:
        with open(CONFIG_YAML) as f:
            cfg = yaml.safe_load(f)
    except Exception as e:
        print(f"  ✗ config.yaml 读取失败: {e}")
        return False

    old_urls = cfg.get('sub-urls') or []
    if old_urls == urls:
        print(f"  config.yaml.sub-urls 已是最新 (无变化), 不重启 subs-check")
        return False

    # 备份
    import shutil
    shutil.copy(CONFIG_YAML, cfg_backup)

    cfg['sub-urls'] = urls
    with open(CONFIG_YAML, 'w') as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=200)

    print(f"  ✓ config.yaml.sub-urls: {len(old_urls)} → {len(urls)}")
    print(f"  ✓ 重启 subs-check...")
    rc = subprocess.run(['systemctl', 'restart', 'subs-check']).returncode
    if rc == 0:
        print(f"  ✓ subs-check 已重启")
        return True
    else:
        print(f"  ✗ subs-check 重启失败 (rc={rc})")
        return False


# ============= 主流程 =============
def main(dry_run=False):
    print(f"[{datetime.now()}] sync-lza6-v2.py start (dry_run={dry_run})")
    db = get_db()

    # 1. 抓 lza6 (ETag 短路)
    try:
        changed, text, etag = fetch_readme(db)
    except Exception as e:
        print(f"  ✗ 抓取失败: {e}")
        return 1

    if not changed:
        print(f"  ℹ️  lza6 README 未变化 (ETag={etag[:32]}...) → 仅跑状态机")
    else:
        print(f"  ✓ lza6 README 已变化 (新 ETag={etag[:32] if etag else 'n/a'}...)")
        urls = extract_subscription_urls(text)
        print(f"  ✓ 提取 {len(urls)} 个候选 URL")
        surv, rej = filter_blacklist(urls)
        print(f"  ✓ 关键字黑名单: 保留 {len(surv)}, 剔除 {len(rej)}")
        upsert_seen(db, surv)
        if etag:
            set_meta(db, 'lza6_etag', etag)

    # 2. 状态机扫描 (dry-run 模式跳过, 避免污染 DB)
    if dry_run:
        print(f"  [dry-run] 跳过状态机扫描 (避免改 DB)")
        n_f = n_p = n_pro = n_dem = n_unb = 0
    else:
        n_f, n_p, n_pro, n_dem, n_unb = apply_state_machine(db)
        print(f"  ✓ 状态机: 失败 {n_f}, 通过 {n_p}, 升白 {n_pro}, 降黑 {n_dem}, 解封 {n_unb}")

    # 3. 选源 (用户白 + 自动白 + 候选)
    final, wl_n, layer_stats = select_sources(db, MAX_SOURCES)
    counts = db.execute(
        "SELECT status, COUNT(*) FROM sources GROUP BY status"
    ).fetchall()
    counts_str = ', '.join(f"{s}={c}" for s, c in counts)
    print(f"  ✓ DB 统计: {counts_str}")
    print(f"  ✓ 选源: {len(final)} 个 (用户白 {layer_stats['user_wl']}"
          f" + 系统白 {layer_stats['auto_wl']}"
          f" + 未测过 {layer_stats['unexplored']}"
          f" + 已测兜底 {layer_stats['tested']})")

    # 4. 写 sub-urls.txt
    if dry_run:
        print(f"\n[DRY RUN] 不写入文件")
        print(f"前 8 条预览:")
        for u in final[:8]:
            print(f"  {u}")
        return 0

    changed_file, backup = write_sub_urls(final, wl_n, is_unchanged=False)
    if changed_file:
        print(f"  ✓ sub-urls.txt 已更新 ({len(final)} 行), 备份到 {backup}")
    else:
        print(f"  ℹ️  sub-urls.txt 内容未变化, 不写入")

    # 5. 同步 config.yaml + 视情况 reload subs-check
    if changed_file:
        sync_config_yaml_and_reload(final, dry_run=False)

    set_meta(db, 'last_sync_at', datetime.now(timezone.utc).isoformat())
    set_meta(db, 'last_sync_count', len(final))
    return 0

if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    sys.exit(main(dry_run))
