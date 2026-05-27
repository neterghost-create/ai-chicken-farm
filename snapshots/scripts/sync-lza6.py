#!/usr/bin/env python3
"""
subs-check 智能源同步器 v3.0

合并:
  - 抓 README + 评分 + 写 sub-urls.txt
  - sub-urls.txt → config.yaml + reload subs-check
  (不再依赖外部 shell 脚本)

v3.0 状态机 (Hysteresis 三态):
  testing (主测试态, 主动累加分数)
    ├─ score 触 100 → decaying
    ├─ score 触 0 → recovering
    └─ 由 sync-lza6 (拉取信号 A) + convert-formats (节点均分信号 B) 累加
  decaying (满分顶到位, 进入被动衰减)
    └─ score 每轮 -1±0.3 (jitter), 触 50 → testing
  recovering (触底, 进入被动恢复)
    └─ score 每轮 +1±0.3, 触 50 → testing

v3.0 评分规则 (信号 A 拉取):
  fetch_ok    +3
  fetch_empty -5  (拉取成功但 0 节点)
  fetch_fail  -10 (HTTP 4xx/5xx)
  fetch_timeout -8

v3.0 选源策略 (80 源):
  1. 用户白名单 (永久保留)
  2. **未评分源 (total_checks=0) — 用户要求最高优先**
  3. testing 状态 (公平轮训, total_checks ASC, score ASC)
  4. recovering / decaying (按 score 排序补齐)

抓取优化:
  - 用 ETag/If-None-Match 304 short-circuit, README 没变就只跑状态机扫描
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
FETCH_TIMEOUT = 15

# v3.0 状态机常量 (Hysteresis 三态)
SOURCE_DEFAULT_SCORE = 50.0        # 默认中点起步
PASSIVE_RATE = 1.0                 # 被动 ±1 分
PASSIVE_JITTER = 0.3               # ±0.3 抖动

# 信号 A (拉取)
SOURCE_FETCH_OK = 3
SOURCE_FETCH_EMPTY = -5
SOURCE_FETCH_FAIL = -10
SOURCE_FETCH_TIMEOUT = -8

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
    "ALTER TABLE sources ADD COLUMN low_score_total INTEGER DEFAULT 0",
    "ALTER TABLE sources ADD COLUMN state TEXT DEFAULT 'testing'",   # v3.0
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
    """v3.0 源三态机: Hysteresis 状态转换 + 信号 A 累加

    规则:
      失败一次:  score -= 10 (SOURCE_FETCH_FAIL), consecutive_fails+1, consecutive_passes=0
      通过一次:  score += 3 (SOURCE_FETCH_OK), consecutive_passes+1, consecutive_fails=0
      触 100:    state='decaying', score=100
      触 0:      state='recovering', score=0
      decaying:  被动 -= 1±0.3, 触 50 → testing
      recovering: 被动 += 1±0.3, 触 50 → testing

    返回 (n_failed, n_passed, n_to_decaying, n_to_recovering, n_dec_to_test, n_rec_to_test)
    """
    import random

    fail_urls = parse_subs_check_failures()
    now = datetime.now(timezone.utc)

    # 取当前 sub-urls.txt 里的, 这些是 "应该被测过的"
    current = set()
    if os.path.exists(TARGET_FILE):
        with open(TARGET_FILE) as f:
            current = {l.strip() for l in f if l.strip() and not l.startswith('#')}

    n_failed = n_passed = n_to_decaying = n_to_recovering = 0

    # === 1. 信号 A: 仅 testing 状态源接受拉取信号累加 ===
    for url in current:
        row = db.execute(
            "SELECT state, score FROM sources WHERE url=?", (url,)
        ).fetchone()
        if not row:
            continue
        state, cur_score = row
        state = state or 'testing'
        cur_score = cur_score if cur_score is not None else SOURCE_DEFAULT_SCORE

        if url in fail_urls:
            n_failed += 1
            db.execute("""
                UPDATE sources SET
                    consecutive_fails = consecutive_fails + 1,
                    consecutive_passes = 0,
                    total_checks = total_checks + 1
                WHERE url=?
            """, (url,))
            if state == 'testing':
                new_score = max(0.0, cur_score + SOURCE_FETCH_FAIL)
                if new_score <= 0:
                    db.execute("UPDATE sources SET score=0, state='recovering' WHERE url=?", (url,))
                    n_to_recovering += 1
                else:
                    db.execute("UPDATE sources SET score=? WHERE url=?", (new_score, url))
        else:
            n_passed += 1
            db.execute("""
                UPDATE sources SET
                    consecutive_passes = consecutive_passes + 1,
                    consecutive_fails = 0,
                    total_checks = total_checks + 1,
                    total_passes = total_passes + 1
                WHERE url=?
            """, (url,))
            if state == 'testing':
                new_score = min(100.0, cur_score + SOURCE_FETCH_OK)
                if new_score >= 100:
                    db.execute("UPDATE sources SET score=100, state='decaying' WHERE url=?", (url,))
                    n_to_decaying += 1
                else:
                    db.execute("UPDATE sources SET score=? WHERE url=?", (new_score, url))

    # === 2. Hysteresis 被动衰减/恢复 (decaying / recovering 两态) ===
    rows = db.execute("""
        SELECT url, state, score FROM sources WHERE state IN ('decaying', 'recovering')
    """).fetchall()
    n_dec_to_test = n_rec_to_test = 0
    for url, state, score in rows:
        score = score if score is not None else SOURCE_DEFAULT_SCORE
        jitter = random.uniform(-PASSIVE_JITTER, PASSIVE_JITTER)
        if state == 'decaying':
            new_score = max(0.0, min(100.0, score - PASSIVE_RATE + jitter))
            if new_score <= SOURCE_DEFAULT_SCORE:
                db.execute("UPDATE sources SET state='testing', score=? WHERE url=?",
                          (SOURCE_DEFAULT_SCORE, url))
                n_dec_to_test += 1
            else:
                db.execute("UPDATE sources SET score=? WHERE url=?", (new_score, url))
        else:  # recovering
            new_score = max(0.0, min(100.0, score + PASSIVE_RATE + jitter))
            if new_score >= SOURCE_DEFAULT_SCORE:
                db.execute("UPDATE sources SET state='testing', score=? WHERE url=?",
                          (SOURCE_DEFAULT_SCORE, url))
                n_rec_to_test += 1
            else:
                db.execute("UPDATE sources SET score=? WHERE url=?", (new_score, url))

    db.commit()
    return n_failed, n_passed, n_to_decaying, n_to_recovering, n_dec_to_test, n_rec_to_test


# ============= 选源 =============
def load_user_whitelist():
    if not os.path.exists(WHITELIST_USER):
        return []
    with open(WHITELIST_USER) as f:
        return [l.strip() for l in f if l.strip() and not l.startswith('#')]


def select_sources(db, max_n=MAX_SOURCES):
    """v3.0 选源策略 (用户要求 80 源优先从未评分的源开始):

    优先级 (自动补齐到 max_n):
      1. 用户白名单 (文件顺序, 永久保留)
      2. **未评分源 total_checks=0** (用户要求 — 最高自动优先)
         按 first_seen ASC (先来先测), 让所有新源至少被轮训一次
      3. testing 状态源 (主测试态, 公平轮训)
         按 total_checks ASC, score ASC, consecutive_passes DESC, first_seen ASC
      4. recovering 状态 (按 score DESC, 让正在恢复的源参与测试反馈)
      5. decaying 状态 (按 score DESC, 满分顶到位的源, 测试少耗一点容错)

    设计目标:
      - 每轮固定 max_n (80) 个源
      - 全部源在 2-3 轮内被首次轮训
      - 之后稳态: testing 池主导, recovering 优先于 decaying (让低分源有机会回归)
      - 没有黑名单, score 触底自动进 recovering 池循环
    """
    user_wl = load_user_whitelist()
    seen = set(user_wl)
    final = list(user_wl)
    layer_stats = {'user_wl': len(user_wl), 'unexplored': 0,
                   'testing': 0, 'recovering': 0, 'decaying': 0}

    def add_from(rows, layer_key):
        for row in rows:
            if len(final) >= max_n:
                return True
            if row[0] not in seen:
                final.append(row[0])
                seen.add(row[0])
                layer_stats[layer_key] += 1
        return False

    # 2. 未评分源 (用户要求最高优先)
    full = add_from(db.execute("""
        SELECT url FROM sources
        WHERE total_checks = 0
        ORDER BY first_seen ASC, url ASC
    """).fetchall(), 'unexplored')
    if full:
        return final, len(user_wl), layer_stats

    # 3. testing 状态 (主测试态, 公平轮训)
    full = add_from(db.execute("""
        SELECT url FROM sources
        WHERE state = 'testing' AND total_checks > 0
        ORDER BY total_checks ASC,
                 score ASC,
                 consecutive_passes DESC,
                 first_seen ASC
    """).fetchall(), 'testing')
    if full:
        return final, len(user_wl), layer_stats

    # 4. recovering 状态 (优先于 decaying, 让低分源有机会回升)
    full = add_from(db.execute("""
        SELECT url FROM sources
        WHERE state = 'recovering'
        ORDER BY score DESC, total_checks ASC
    """).fetchall(), 'recovering')
    if full:
        return final, len(user_wl), layer_stats

    # 5. decaying 状态 (满分顶到位的源, 测试反馈最弱)
    add_from(db.execute("""
        SELECT url FROM sources
        WHERE state = 'decaying'
        ORDER BY score DESC, total_checks ASC
    """).fetchall(), 'decaying')

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
    else:
        n_f, n_p, n_dec, n_rec, n_d2t, n_r2t = apply_state_machine(db)
        print(f"  ✓ v3.0 源三态机: 失败 {n_f}, 通过 {n_p}, "
              f"→decaying {n_dec}, →recovering {n_rec}, "
              f"hysteresis dec→test {n_d2t}, rec→test {n_r2t}")

    # 3. 选源 (用户白 + 未评分 + testing + recovering + decaying)
    final, wl_n, layer_stats = select_sources(db, MAX_SOURCES)
    counts = db.execute(
        "SELECT state, COUNT(*) FROM sources GROUP BY state"
    ).fetchall()
    counts_str = ', '.join(f"{s or 'null'}={c}" for s, c in counts)
    print(f"  ✓ DB 状态分布: {counts_str}")
    print(f"  ✓ 选源 v3.0: {len(final)} 个 (用户白 {layer_stats['user_wl']}"
          f" + 未评分 {layer_stats['unexplored']}"
          f" + testing {layer_stats['testing']}"
          f" + recovering {layer_stats['recovering']}"
          f" + decaying {layer_stats['decaying']})")

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
