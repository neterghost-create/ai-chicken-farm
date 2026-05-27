#!/usr/bin/env python3
"""
all.yaml (Clash/Mihomo) → 多格式 + 监控数据:

输出文件:
  - all.yaml      (原始 Clash, 不动)
  - v2ray.txt     (vmess://, vless://, trojan://, ss:// 一行一个)
  - base64.txt    (上面 v2ray.txt 的 base64 编码)
  - stats.json    (节点统计 + 协议分布 + URLs)
  - nodes.json    (当前轮节点详情列表, 前端表格用)
  - diff.json     (这轮 vs 上轮: 新增/消失/保留 节点)

监控数据:
  - history.db    (SQLite, 存历次轮次摘要 + 趋势)

idempotency:
  - 如果 all.yaml 没变 (mtime 未变), 不重写衍生文件 (只在 stats.json 标记 noop)
  - 如果 nodes 集合没变 (用 server:port:type 哈希识别), diff 写空, history 不新增行
"""
import os
import sys
import re
import json
import yaml
import base64
import urllib.parse
import hashlib
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

OUT_DIR = "/opt/ss-monitor/sub/free"      # 监控 JSON 输出位置 (公开)
HISTORY_DB = "/opt/subs-check/scripts/history.db"
TOKEN_CONF = "/opt/subs-check/scripts/free-pool.conf"


def load_token():
    """读 free-pool.conf 拿 token. 不存在/没设 → 返回 None (回退到无 token 模式)"""
    if not os.path.exists(TOKEN_CONF):
        return None
    try:
        with open(TOKEN_CONF) as f:
            for line in f:
                line = line.strip()
                if line.startswith('TOKEN=') and '=' in line:
                    val = line.split('=', 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val
    except Exception:
        pass
    return None


def get_input_yaml():
    """选 all.yaml 输入: mtime 最新的优先 (兼容老路径残留 + token 子目录两个写入点)
    
    设计:
      - subs-check service 重启前, output-dir 还是老路径, 80 源跑完会写到 /opt/ss-monitor/sub/free/all.yaml
      - subs-check service 重启后, 写到 /opt/ss-monitor/sub/free/<TOKEN>/all.yaml
      - 用 mtime 比较, 永远拿最新结果, 避免展示陈旧数据
    """
    candidates = []
    token = load_token()
    if token:
        p = os.path.join(OUT_DIR, token, 'all.yaml')
        if os.path.exists(p):
            candidates.append(p)
    p_legacy = os.path.join(OUT_DIR, 'all.yaml')
    if os.path.exists(p_legacy):
        candidates.append(p_legacy)
    if not candidates:
        return p_legacy  # 都不存在, 返回老路径让上游错误信息更标准
    # 选 mtime 最新
    return max(candidates, key=os.path.getmtime)


INPUT_YAML = get_input_yaml()

# ============= 历史 DB =============
HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS rounds (
    round_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    yaml_mtime TEXT NOT NULL,
    total_nodes INTEGER,
    protocols_json TEXT,
    nodes_hash TEXT,
    diff_added INTEGER DEFAULT 0,
    diff_removed INTEGER DEFAULT 0,
    diff_kept INTEGER DEFAULT 0,
    notified INTEGER DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_rounds_mtime ON rounds(yaml_mtime);
CREATE INDEX IF NOT EXISTS idx_rounds_ts ON rounds(timestamp DESC);

-- nodes_history: 每个节点 (canonical_sig) 的累积评分
CREATE TABLE IF NOT EXISTS nodes_history (
    canonical_sig TEXT PRIMARY KEY,    -- server:port:type, 跨 cdn 同主机视为同节点
    first_seen TEXT,
    last_seen TEXT,
    last_speed_kbps INTEGER,           -- 上一次测速结果
    avg_speed_kbps REAL DEFAULT 0,     -- 历史均值
    total_appearances INTEGER DEFAULT 0,    -- 出现轮次数
    consecutive_appearances INTEGER DEFAULT 0,  -- 连续出现轮次
    consecutive_fails INTEGER DEFAULT 0,    -- 增量测试连续失败次数
    incremental_pass INTEGER DEFAULT 0,     -- 增量测试通过次数
    incremental_fail INTEGER DEFAULT 0,     -- 增量测试失败次数
    blacklisted_until TEXT,            -- 节点级黑名单到期 (48h)
    quality_score REAL DEFAULT 50.0,   -- 综合质量分 (0-100)
    last_round_id INTEGER,             -- 最后出现的 round_id
    region TEXT,
    protocol TEXT,
    sample_name TEXT                   -- 最近一次的展示名
);

CREATE INDEX IF NOT EXISTS idx_nodes_score ON nodes_history(quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_nodes_blacklist ON nodes_history(blacklisted_until);
"""


def get_history_db():
    Path(HISTORY_DB).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(HISTORY_DB)
    db.executescript(HISTORY_SCHEMA)
    db.commit()
    return db


# ============= 节点 → URL 转换 =============
def to_v2ray_url(p: dict):
    """Clash 节点 dict → v2ray-style URL"""
    typ = p.get('type')
    name = p.get('name', 'unnamed')
    server = p.get('server', '')
    port = p.get('port', 0)
    encoded_name = urllib.parse.quote(name, safe='')

    if typ == 'vmess':
        v = {
            'v': '2', 'ps': name, 'add': server, 'port': port,
            'id': p.get('uuid', ''), 'aid': p.get('alterId', 0),
            'scy': p.get('cipher', 'auto'),
            'net': p.get('network', 'tcp'),
            'type': 'none', 'host': '', 'path': '',
            'tls': 'tls' if p.get('tls') else '',
            'sni': p.get('servername', '') or p.get('sni', ''),
        }
        ws = p.get('ws-opts') or p.get('ws_opts') or {}
        if ws:
            v['path'] = ws.get('path', '')
            hdrs = ws.get('headers') or {}
            v['host'] = hdrs.get('Host', '') or hdrs.get('host', '')
        return 'vmess://' + base64.b64encode(
            json.dumps(v, ensure_ascii=False).encode()
        ).decode().rstrip('=')

    elif typ == 'vless':
        uuid = p.get('uuid', '')
        if not uuid or not server:
            return None
        params = {}
        if p.get('tls') or p.get('security'):
            params['security'] = p.get('security') or ('tls' if p.get('tls') else 'none')
        if p.get('flow'):
            params['flow'] = p['flow']
        sni = p.get('servername') or p.get('sni')
        if sni:
            params['sni'] = sni
        params['type'] = p.get('network', 'tcp')
        ws = p.get('ws-opts') or p.get('ws_opts') or {}
        if ws and 'path' in ws:
            params['path'] = ws['path']
            hdrs = ws.get('headers') or {}
            host = hdrs.get('Host') or hdrs.get('host')
            if host:
                params['host'] = host
        ro = p.get('reality-opts') or {}
        if ro:
            params['security'] = 'reality'
            if ro.get('public-key'):
                params['pbk'] = ro['public-key']
            if ro.get('short-id'):
                params['sid'] = ro['short-id']
        if p.get('client-fingerprint'):
            params['fp'] = p['client-fingerprint']
        q = '&'.join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params.items())
        return f"vless://{uuid}@{server}:{port}?{q}#{encoded_name}"

    elif typ == 'trojan':
        pwd = p.get('password', '')
        sni = p.get('sni') or p.get('servername') or ''
        params = {}
        if sni:
            params['sni'] = sni
        if p.get('skip-cert-verify'):
            params['allowInsecure'] = '1'
        ws = p.get('ws-opts') or p.get('ws_opts') or {}
        if ws:
            params['type'] = 'ws'
            if 'path' in ws:
                params['path'] = ws['path']
            hdrs = ws.get('headers') or {}
            host = hdrs.get('Host') or hdrs.get('host')
            if host:
                params['host'] = host
        q = '&'.join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params.items())
        return f"trojan://{urllib.parse.quote(pwd, safe='')}@{server}:{port}{'?' + q if q else ''}#{encoded_name}"

    elif typ == 'ss':
        cipher = p.get('cipher', '')
        pwd = p.get('password', '')
        if not cipher or not pwd:
            return None
        userinfo = base64.urlsafe_b64encode(f"{cipher}:{pwd}".encode()).decode().rstrip('=')
        return f"ss://{userinfo}@{server}:{port}#{encoded_name}"

    elif typ in ('hysteria', 'hysteria2', 'hy2'):
        auth = p.get('auth-str') or p.get('password') or p.get('auth') or ''
        sni = p.get('sni', '')
        params = {}
        if sni:
            params['sni'] = sni
        if p.get('skip-cert-verify'):
            params['insecure'] = '1'
        if p.get('alpn'):
            alpn = p['alpn']
            if isinstance(alpn, list):
                alpn = ','.join(alpn)
            params['alpn'] = alpn
        q = '&'.join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params.items())
        scheme = 'hysteria2' if typ in ('hysteria2', 'hy2') else 'hysteria'
        return f"{scheme}://{urllib.parse.quote(auth, safe='')}@{server}:{port}{'?' + q if q else ''}#{encoded_name}"

    return None


# ============= 节点信息提取 (脱敏, 给监控前端) =============
FLAG_REGEX = re.compile(r'(\U0001F1E6[\U0001F1E6-\U0001F1FF])') if False else None  # 不用 regex, 直接看 emoji


def extract_speed_from_name(name: str):
    """从节点名提取测速值 KB/s, e.g.
       '🇩🇪DE_1|630KB/s'  → 630
       '🇸🇬SG_4|1.0MB/s' → 1024
       '🇸🇬SG_67|1.1MB/s'→ 1126
    """
    # KB/s (整数或小数)
    m = re.search(r'\|(\d+(?:\.\d+)?)KB/s', name)
    if m:
        return int(float(m.group(1)))
    # MB/s → 转 KB/s
    m = re.search(r'\|(\d+(?:\.\d+)?)MB/s', name)
    if m:
        return int(float(m.group(1)) * 1024)
    return None


def extract_region_from_name(name: str):
    """提取地区 (双字母代码 'DE' / 'SG' / 'HK' 等), 失败返回 None.
    
    必须在节点名开头或者 emoji 旗帜后面, 排除 'KB'/'MB' 等非地区缩写
    """
    NON_REGION = {'KB', 'MB', 'GB', 'TB'}
    # 优先: 紧跟在 emoji 旗帜 (双 unicode regional indicator) 后的两个大写字母
    # 旗帜 unicode 区间: U+1F1E6-U+1F1FF
    m = re.search(r'[\U0001F1E6-\U0001F1FF]{2}([A-Z]{2})', name)
    if m and m.group(1) not in NON_REGION:
        return m.group(1)
    # 否则: 名字开头的两个大写字母
    m = re.match(r'([A-Z]{2})_?\d*', name)
    if m and m.group(1) not in NON_REGION:
        return m.group(1)
    return None


def node_signature(p: dict) -> str:
    """节点稳定标识 (用于 diff 比对): server:port:type"""
    server = p.get('server', '')
    port = p.get('port', '')
    typ = p.get('type', '')
    return f"{server}:{port}:{typ}"


def node_to_summary(p: dict) -> dict:
    """脱敏后的节点信息 (给前端表格用, 不含密码/uuid)"""
    name = p.get('name', '')
    return {
        'name': name,
        'type': p.get('type', ''),
        'server': p.get('server', ''),
        'port': p.get('port', 0),
        'region': extract_region_from_name(name),
        'speed_kbps': extract_speed_from_name(name),
        'network': p.get('network', '') if p.get('network') else None,
        'tls': bool(p.get('tls') or p.get('security') == 'tls' or p.get('security') == 'reality'),
        'sig': node_signature(p),
    }


# 通用 Clash / 老客户端能加载的协议白名单
# (mihomo 专属如 hysteria2/hysteria/tuic/mieru/anytls/ssh 会让老 Clash 报
#  "unsupport proxy type:xxx" 整个 config 加载失败)
LEGACY_CLASH_COMPATIBLE_TYPES = {
    'ss', 'ssr', 'vmess', 'vless', 'trojan',
    'http', 'socks5', 'snell',
}


# ============= 完整 config 生成 (mihomo 标准) =============
def write_full_config(proxies: list, type_counts: dict, sub_dir: str):
    """
    生成自带 proxy-groups + rules 的完整 config (all-config.yaml)
    给那些把订阅链接当完整 config 用的客户端 (而非 Proxy Provider).

    注: 这里会过滤掉 mihomo 专属协议 (hysteria2/hysteria/tuic/mieru/anytls/ssh),
    因为老 Clash / Clash X / 部分 Stash 版本不识别会整个 config 加载失败.
    完整协议池请走 /all.yaml (Proxy Provider 模式).
    """
    out_path = os.path.join(sub_dir, 'all-config.yaml')

    # 过滤: 仅保留老 Clash 也能识别的协议
    original_count = len(proxies)
    proxies = [p for p in proxies if p.get('type') in LEGACY_CLASH_COMPATIBLE_TYPES]
    filtered_count = original_count - len(proxies)

    # 重新统计 type_counts (只统计保留下来的)
    type_counts = {}
    for p in proxies:
        t = p.get('type', 'unknown')
        type_counts[t] = type_counts.get(t, 0) + 1

    proxy_names = [p.get('name', '') for p in proxies if p.get('name')]
    if not proxy_names:
        # 空池, 写最小 config 防 import 报错
        proxy_names = []

    # 按地区/协议分组
    region_groups = {}  # 'HK' -> [name, ...]
    type_groups = {}    # 'vless' -> [name, ...]
    for p in proxies:
        name = p.get('name', '')
        if not name:
            continue
        region = extract_region_from_name(name) or 'Other'
        region_groups.setdefault(region, []).append(name)
        ptype = p.get('type', 'unknown')
        type_groups.setdefault(ptype, []).append(name)

    # 主分组
    proxy_groups = [
        {
            'name': '🚀 节点选择',
            'type': 'select',
            'proxies': ['♻️ 自动选择', '🎯 故障转移', 'DIRECT'] + proxy_names,
        },
        {
            'name': '♻️ 自动选择',
            'type': 'url-test',
            'proxies': proxy_names if proxy_names else ['DIRECT'],
            'url': 'http://www.gstatic.com/generate_204',
            'interval': 300,
            'tolerance': 50,
        },
        {
            'name': '🎯 故障转移',
            'type': 'fallback',
            'proxies': proxy_names if proxy_names else ['DIRECT'],
            'url': 'http://www.gstatic.com/generate_204',
            'interval': 300,
        },
    ]

    # 地区分组 (有节点才加)
    region_emoji = {
        'HK': '🇭🇰 香港', 'TW': '🇹🇼 台湾', 'SG': '🇸🇬 新加坡',
        'JP': '🇯🇵 日本', 'KR': '🇰🇷 韩国', 'US': '🇺🇸 美国',
        'UK': '🇬🇧 英国', 'GB': '🇬🇧 英国', 'DE': '🇩🇪 德国',
        'FR': '🇫🇷 法国', 'NL': '🇳🇱 荷兰', 'CA': '🇨🇦 加拿大',
        'AU': '🇦🇺 澳洲', 'RU': '🇷🇺 俄罗斯', 'TR': '🇹🇷 土耳其',
        'IN': '🇮🇳 印度', 'BR': '🇧🇷 巴西',
    }
    for region in sorted(region_groups.keys()):
        names = region_groups[region]
        if not names:
            continue
        display = region_emoji.get(region, f'🌐 {region}')
        proxy_groups.append({
            'name': display,
            'type': 'url-test',
            'proxies': names,
            'url': 'http://www.gstatic.com/generate_204',
            'interval': 300,
            'tolerance': 50,
        })

    # 标准规则 (基础常用类)
    rules = [
        # 直连
        'DOMAIN-SUFFIX,local,DIRECT',
        'IP-CIDR,127.0.0.0/8,DIRECT,no-resolve',
        'IP-CIDR,172.16.0.0/12,DIRECT,no-resolve',
        'IP-CIDR,192.168.0.0/16,DIRECT,no-resolve',
        'IP-CIDR,10.0.0.0/8,DIRECT,no-resolve',
        'IP-CIDR,17.0.0.0/8,DIRECT,no-resolve',
        'IP-CIDR,100.64.0.0/10,DIRECT,no-resolve',
        # 中国大陆 IP/域名 直连
        'GEOIP,CN,DIRECT',
        'GEOSITE,cn,DIRECT',
        'GEOSITE,private,DIRECT',
        # 其他全部走代理
        'MATCH,🚀 节点选择',
    ]

    config = {
        # 基础设置 (mihomo 标准)
        'port': 7890,
        'socks-port': 7891,
        'mixed-port': 7892,
        'allow-lan': False,
        'mode': 'rule',
        'log-level': 'info',
        'external-controller': '127.0.0.1:9090',
        # DNS
        'dns': {
            'enable': True,
            'ipv6': False,
            'enhanced-mode': 'fake-ip',
            'fake-ip-range': '198.18.0.1/16',
            'nameserver': ['223.5.5.5', '119.29.29.29'],
            'fallback': ['8.8.8.8', '1.1.1.1'],
        },
        # 节点
        'proxies': proxies,
        'proxy-groups': proxy_groups,
        'rules': rules,
    }

    with open(out_path, 'w') as f:
        f.write(f"# Auto-generated full mihomo/Clash config\n")
        f.write(f"# Source: subs-check 公益免费节点池\n")
        f.write(f"# Generated: {datetime.now()}\n")
        f.write(f"# Nodes: {len(proxies)} ({', '.join(f'{k}:{v}' for k, v in type_counts.items())})\n")
        if filtered_count > 0:
            f.write(f"# Filtered: {filtered_count} mihomo-only nodes (hysteria2/tuic/mieru/etc) for legacy Clash compatibility.\n")
            f.write(f"#           Use /all.yaml (Proxy Provider) with mihomo/Clash.Meta to access them.\n")
        f.write(f"# Use this URL when client expects a complete config (not just Proxy Provider).\n")
        f.write(f"#\n")
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False, width=200, default_flow_style=False)


def update_nodes_history(db, summaries: list, round_id: int):
    """
    更新节点级历史表 (v2.3: 信号 B+C 直接累加 quality_score)

    v2.3 评分逻辑:
      - 本轮出现节点: 应用信号 B (出现 +2, 连续 ≥5 额外 +3) + 信号 C (测速档)
      - 本轮未出现节点: -3 (NODE_ABSENT_PENALTY), 不累加 fails (避免冤死)
      - 探活信号 (A) 由 incremental-check.py 处理, 不在此处
      - lq_node 累加 + 触发点 ② (持续低质拉黑) 由调用方 round 切换时统一执行

    返回 (新出现, 旧节点, 重新激活的节点数)
    """
    now = datetime.now(timezone.utc).isoformat()
    seen_sigs = set()
    n_new = n_recurring = n_reactivated = 0

    # === 1. 处理本轮出现的节点 (信号 B+C) ===
    for s in summaries:
        sig = s['sig']
        if not sig or sig in seen_sigs:
            continue
        seen_sigs.add(sig)

        speed = s.get('speed_kbps') or 0
        region = s.get('region')
        proto = s.get('type')
        name = s.get('name', '')[:80]  # 限长防注入

        # 看是否已存在
        row = db.execute(
            "SELECT total_appearances, consecutive_appearances, avg_speed_kbps, "
            "quality_score, last_round_id, blacklisted_until "
            "FROM nodes_history WHERE canonical_sig = ?",
            (sig,)
        ).fetchone()

        if row is None:
            # 全新节点 - 默认 100, 加上本轮信号 B+C
            n_new += 1
            cons_apps = 1
            delta = calc_round_delta(present=True, cons_apps=cons_apps, speed_kbps=speed)
            new_score = max(0.0, min(100.0, NODE_DEFAULT_SCORE + delta))
            db.execute("""
                INSERT INTO nodes_history (
                    canonical_sig, first_seen, last_seen, last_speed_kbps, avg_speed_kbps,
                    total_appearances, consecutive_appearances, last_round_id,
                    region, protocol, sample_name, quality_score, consecutive_low_quality_node
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 0)
            """, (sig, now, now, speed, speed, cons_apps, round_id, region, proto, name, new_score))
        else:
            (total_apps, cons_apps, avg_speed, old_score,
             last_rid, blocked_until) = row

            # 是不是连续出现 (上一轮 round_id == 当前-1)
            if last_rid == round_id - 1:
                cons_apps += 1
            else:
                cons_apps = 1  # 中断重置

            total_apps += 1
            # 加权平均: 新值占 30%, 历史占 70%
            new_avg = (avg_speed or 0) * 0.7 + speed * 0.3

            # 应用 v2.3 信号 B+C
            delta = calc_round_delta(present=True, cons_apps=cons_apps, speed_kbps=speed)
            new_score = max(0.0, min(100.0, (old_score or NODE_DEFAULT_SCORE) + delta))

            # 黑名单到期解封 (即便还没到 48h, 节点重新出现也信任)
            if blocked_until:
                n_reactivated += 1
            else:
                n_recurring += 1

            db.execute("""
                UPDATE nodes_history SET
                    last_seen = ?,
                    last_speed_kbps = ?,
                    avg_speed_kbps = ?,
                    total_appearances = ?,
                    consecutive_appearances = ?,
                    consecutive_fails = 0,
                    last_round_id = ?,
                    region = ?,
                    protocol = ?,
                    sample_name = ?,
                    blacklisted_until = NULL,
                    quality_score = ?
                WHERE canonical_sig = ?
            """, (now, speed, new_avg, total_apps, cons_apps, round_id,
                  region, proto, name, new_score, sig))

    # === 2. 处理本轮未出现的节点 (信号 B: -3 不累加 fails) ===
    # 仅处理"上一轮还出现, 这一轮没出现"的节点 (避免对早就死的节点反复扣分)
    db.execute("""
        UPDATE nodes_history SET
            quality_score = MAX(0, COALESCE(quality_score, ?) - ?),
            consecutive_appearances = 0
        WHERE blacklisted_until IS NULL
          AND last_round_id IS NOT NULL
          AND last_round_id < ?
          AND last_round_id >= ?
    """, (NODE_DEFAULT_SCORE, NODE_ABSENT_PENALTY, round_id, round_id - 30))

    db.commit()
    return n_new, n_recurring, n_reactivated


def apply_lq_node_and_blacklist(db, round_id: int):
    """
    v2.3 触发点 ②: 仅本轮出现的节点参与 lq_node 判定 + 拉黑.

    规则:
      - if quality_score < 30 AND last_round_id == round_id (本轮出现):
          consecutive_low_quality_node += 1
        else if last_round_id == round_id (本轮出现且分数 OK):
          consecutive_low_quality_node = 0
        else:
          不动 (未出现节点不参与 lq 判定, 避免冤死)
      - if consecutive_low_quality_node >= 5:
          blacklisted_until = now + 48h

    仅在 round 切换时由 main 调用一次, 不重复触发.
    """
    now_dt = datetime.now(timezone.utc)
    blocked_until = (now_dt + timedelta(hours=NODE_BLACKLIST_HOURS)).isoformat()

    # 1. 本轮出现且 score < 30 → lq+1
    db.execute("""
        UPDATE nodes_history SET
            consecutive_low_quality_node = consecutive_low_quality_node + 1
        WHERE last_round_id = ?
          AND quality_score < ?
          AND blacklisted_until IS NULL
    """, (round_id, NODE_LOW_QUALITY_THRESHOLD))

    # 2. 本轮出现且 score >= 30 → lq=0
    db.execute("""
        UPDATE nodes_history SET
            consecutive_low_quality_node = 0
        WHERE last_round_id = ?
          AND quality_score >= ?
          AND blacklisted_until IS NULL
          AND consecutive_low_quality_node > 0
    """, (round_id, NODE_LOW_QUALITY_THRESHOLD))

    # 3. lq_node >= 5 → 拉黑 48h
    n_blacklisted = db.execute("""
        UPDATE nodes_history SET
            blacklisted_until = ?
        WHERE consecutive_low_quality_node >= ?
          AND blacklisted_until IS NULL
    """, (blocked_until, NODE_KILL_AFTER_LOW_ROUNDS)).rowcount

    db.commit()
    return n_blacklisted


# ============= v2.3 节点级评分常量 =============
NODE_DEFAULT_SCORE = 100.0
NODE_FAIL_THRESHOLD = 4              # consecutive_fails >= 4 → 黑名单 (探活 incremental-check 触发)
NODE_BLACKLIST_HOURS = 48
NODE_LOW_QUALITY_THRESHOLD = 30      # quality_score < 此值视为低质
NODE_KILL_AFTER_LOW_ROUNDS = 5       # 触发点 ② lq_node >= 5 拉黑

# 信号 B (轮次)
NODE_PRESENT_BONUS = 2               # 本轮出现 +2
NODE_ABSENT_PENALTY = 3              # 本轮未出现 -3
NODE_CONSECUTIVE_BONUS = 3           # consecutive_appearances >= 5 额外 +3

# 信号 C (测速)
NODE_SPEED_HIGH_BONUS = 3            # >= 2048 KB/s
NODE_SPEED_LOW_PENALTY = 3           # 512-1023 KB/s
NODE_SPEED_VLOW_PENALTY = 12         # 100-511 KB/s (v2.2 加大)
NODE_SPEED_DEAD_PENALTY = 15         # < 100 KB/s


def calc_quality_score(*args, **kwargs) -> float:
    """
    v2.3: 已废弃. 节点 quality_score 由信号 ABC (探活/轮次/测速) 直接累积维护,
    不再需要重新计算. 此函数保留为 stub 仅供新节点初始化使用 (返回默认 100).
    """
    return NODE_DEFAULT_SCORE


def calc_round_delta(present: bool, cons_apps: int, speed_kbps: float) -> float:
    """
    v2.3 信号 B (轮次) + 信号 C (测速) 单轮 quality_score 增减.
    探活 (信号 A) 由 incremental-check.py 直接更新, 不在此处.
    """
    delta = 0.0
    # 信号 B: 轮次
    if present:
        delta += NODE_PRESENT_BONUS
        if cons_apps >= 5:
            delta += NODE_CONSECUTIVE_BONUS
    else:
        delta -= NODE_ABSENT_PENALTY
        return delta  # 未出现的没有测速信号

    # 信号 C: 测速 (仅本轮出现且测了速)
    if speed_kbps and speed_kbps > 0:
        if speed_kbps >= 2048:
            delta += NODE_SPEED_HIGH_BONUS
        elif speed_kbps >= 1024:
            pass  # +0
        elif speed_kbps >= 512:
            delta -= NODE_SPEED_LOW_PENALTY
        elif speed_kbps >= 100:
            delta -= NODE_SPEED_VLOW_PENALTY
        else:
            delta -= NODE_SPEED_DEAD_PENALTY
    return delta


def cleanup_dead_nodes(db, current_round_id: int, fresh_threshold_rounds: int = 30):
    """
    清掉超过 N 轮 (~30轮 ≈ 7天) 没出现的节点 + 自动解封黑名单到期节点 (v2.3)
    """
    now = datetime.now(timezone.utc)

    # v2.3 黑名单到期: 完整复活 (score=100, 所有计数器归零)
    n_unblocked = db.execute("""
        UPDATE nodes_history SET
            blacklisted_until = NULL,
            quality_score = 100.0,
            consecutive_fails = 0,
            consecutive_low_quality_node = 0
        WHERE blacklisted_until IS NOT NULL AND blacklisted_until <= ?
    """, (now.isoformat(),)).rowcount

    # 清理 30 轮没见过的节点
    n_purged = db.execute("""
        DELETE FROM nodes_history
        WHERE last_round_id IS NOT NULL
          AND ? - last_round_id > ?
    """, (current_round_id, fresh_threshold_rounds)).rowcount

    db.commit()
    return n_unblocked, n_purged


# ============= v2.3 源级质量评分 =============
SOURCES_DB = "/opt/subs-check/scripts/source-scores.db"

# v2.3 信号 B 节点质量减分档 (分档替代旧版的 "<50 一刀切")
SOURCE_QUALITY_PENALTY_LOW = 2     # 50-69 分均分
SOURCE_QUALITY_PENALTY_MID = 5     # 30-49 分均分
SOURCE_QUALITY_PENALTY_HIGH = 10   # < 30 分均分

# 拉黑触发阈值
SOURCE_KILL_AFTER_LOW_ROUNDS = 5   # ③ consecutive_low_quality streak >= 5
SOURCE_KILL_AFTER_LOW_TOTAL = 15   # ④ low_score_total >= 15
SOURCE_LOW_SCORE_THRESHOLD = 30    # ④ score < 30 累计判定阈值
SOURCE_BLACKLIST_DAYS = 30         # 源拉黑期

# 评估前置条件
MIN_NODES_FOR_QUALITY_EVAL = 5     # 节点 < 5 不评估


def update_source_quality(round_id: int):
    """
    v2.3 源级质量评分 + 拉黑触发 ③ ④

    每轮跑一次. 流程:
      1. 算每个源贡献节点 (5 轮窗口) 的均分
      2. 信号 B: 按均分档位扣分 + lq streak 累加
      3. 累计低分: score < 30 → low_score_total += 1
      4. 拉黑触发 ③: consecutive_low_quality >= 5 → blacklist 30 天
      5. 拉黑触发 ④: low_score_total >= 15 → blacklist 30 天
      6. 黑名单到期: 完整复活 (score=100, 所有计数器清零)

    注意: 跨 2 个 DB (source-scores 主表 + history 节点评分)
    """
    if not os.path.exists(SOURCES_DB):
        return None

    score_db = sqlite3.connect(SOURCES_DB)

    # ATTACH history.db 让我们能 join 节点评分
    score_db.execute(f"ATTACH DATABASE '{HISTORY_DB}' AS hdb")

    now = datetime.now(timezone.utc).isoformat()
    n_updated = n_blacklisted_3 = n_blacklisted_4 = n_unblocked = 0

    # === 0. v2.3 黑名单到期完整复活 (优先于本轮判定) ===
    n_unblocked = score_db.execute("""
        UPDATE sources SET
            status = 'candidate',
            score = 100.0,
            consecutive_fails = 0,
            consecutive_passes = 0,
            consecutive_low_quality = 0,
            low_score_total = 0,
            blocked_until = NULL
        WHERE status = 'blacklisted'
          AND blocked_until IS NOT NULL
          AND blocked_until <= ?
    """, (now,)).rowcount

    # === 1. 算每个源该轮贡献节点平均分 ===
    rows = score_db.execute("""
        SELECT m.source_url, COUNT(*) as node_count, AVG(h.quality_score) as avg_score
        FROM source_node_map m
        JOIN hdb.nodes_history h ON h.canonical_sig = m.canonical_sig
        WHERE m.last_seen_round >= ?      -- 仅算最近 5 轮还出现的关系
        GROUP BY m.source_url
    """, (round_id - 5,)).fetchall()

    for source_url, node_count, avg_score in rows:
        # === 2. 信号 B: 按均分档位扣分 ===
        if avg_score is None or node_count < MIN_NODES_FOR_QUALITY_EVAL:
            # 节点 < 5 不评估, lq 重置 (按 v2.3 决策 2B)
            score_db.execute("""
                UPDATE sources SET consecutive_low_quality = 0
                WHERE url = ? AND consecutive_low_quality > 0
            """, (source_url,))
            continue

        if avg_score >= 70:
            penalty = 0
            lq_action = 'reset'
        elif avg_score >= 50:
            penalty = SOURCE_QUALITY_PENALTY_LOW
            lq_action = 'inc'
        elif avg_score >= 30:
            penalty = SOURCE_QUALITY_PENALTY_MID
            lq_action = 'inc'
        else:
            penalty = SOURCE_QUALITY_PENALTY_HIGH
            lq_action = 'inc'

        below_50 = 1 if avg_score < 50 else 0   # 兼容旧字段

        # 写入 source_quality_history (UNIQUE on source+round)
        try:
            score_db.execute("""
                INSERT INTO source_quality_history
                    (source_url, round_id, timestamp, node_count, avg_quality_score, below_50)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (source_url, round_id, now, node_count, round(avg_score, 2), below_50))
        except sqlite3.IntegrityError:
            continue  # 重跑场景, 已有记录

        # === 3. 应用 score 减分 + lq streak ===
        if lq_action == 'inc':
            score_db.execute("""
                UPDATE sources SET
                    score = MAX(0, score - ?),
                    consecutive_low_quality = consecutive_low_quality + 1
                WHERE url = ?
            """, (penalty, source_url))
        else:
            score_db.execute("""
                UPDATE sources SET
                    consecutive_low_quality = 0
                WHERE url = ?
            """, (source_url,))

        # === 4. 累计低分: score < 30 → low_score_total += 1 ===
        score_db.execute("""
            UPDATE sources SET low_score_total = low_score_total + 1
            WHERE url = ? AND score < ?
        """, (source_url, SOURCE_LOW_SCORE_THRESHOLD))

        n_updated += 1

        # === 5. 拉黑判定: ③ lq >= 5 ===
        cur = score_db.execute("""
            SELECT consecutive_low_quality, low_score_total, status, score
            FROM sources WHERE url = ?
        """, (source_url,)).fetchone()
        if not cur:
            continue
        lq, lst, status, cur_score = cur
        if status == 'blacklisted':
            continue

        from datetime import timedelta as _td

        if lq >= SOURCE_KILL_AFTER_LOW_ROUNDS:
            blocked_until = (datetime.now(timezone.utc) + _td(days=SOURCE_BLACKLIST_DAYS)).isoformat()
            score_db.execute("""
                UPDATE sources SET status='blacklisted', blocked_until=?
                WHERE url=?
            """, (blocked_until, source_url))
            n_blacklisted_3 += 1
            print(f"    ⛔ 拉黑源 ③ (lq={lq}/5, score={cur_score:.1f}): {source_url[:80]}")
            continue

        # === 6. 拉黑判定: ④ low_score_total >= 15 ===
        if lst >= SOURCE_KILL_AFTER_LOW_TOTAL:
            blocked_until = (datetime.now(timezone.utc) + _td(days=SOURCE_BLACKLIST_DAYS)).isoformat()
            score_db.execute("""
                UPDATE sources SET status='blacklisted', blocked_until=?
                WHERE url=?
            """, (blocked_until, source_url))
            n_blacklisted_4 += 1
            print(f"    ⛔ 拉黑源 ④ (low_score_total={lst}/15, score={cur_score:.1f}): {source_url[:80]}")

    score_db.commit()
    score_db.close()

    return {
        'updated': n_updated,
        'blacklisted_3_lq': n_blacklisted_3,
        'blacklisted_4_lst': n_blacklisted_4,
        'blacklisted': n_blacklisted_3 + n_blacklisted_4,
        'unblocked': n_unblocked,
    }


# ============= enrich =============
def enrich_summaries_with_history(db, summaries: list) -> list:
    """
    把 nodes_history 表的 quality_score / total_appearances 等数据合并到 summaries
    返回的列表按 quality_score 降序排序 (前端表格优先看高分节点)
    """
    sigs = [s['sig'] for s in summaries if s.get('sig')]
    if not sigs:
        return summaries
    
    placeholders = ','.join('?' * len(sigs))
    rows = db.execute(f"""
        SELECT canonical_sig, quality_score, total_appearances, consecutive_appearances,
               avg_speed_kbps, incremental_pass, incremental_fail, blacklisted_until
        FROM nodes_history WHERE canonical_sig IN ({placeholders})
    """, sigs).fetchall()
    
    history = {r[0]: {
        'quality_score': round(r[1], 1),
        'appearances': r[2],
        'consecutive': r[3],
        'avg_speed_kbps': round(r[4]) if r[4] else 0,
        'inc_pass': r[5],
        'inc_fail': r[6],
        'blacklisted': bool(r[7]),
    } for r in rows}
    
    enriched = []
    for s in summaries:
        merged = dict(s)
        h = history.get(s['sig'], {})
        merged.update({
            'quality_score': h.get('quality_score', 100.0),
            'appearances': h.get('appearances', 1),
            'consecutive': h.get('consecutive', 1),
            'avg_speed_kbps': h.get('avg_speed_kbps', s.get('speed_kbps') or 0),
            'inc_pass': h.get('inc_pass', 0),
            'inc_fail': h.get('inc_fail', 0),
            'blacklisted': h.get('blacklisted', False),
        })
        enriched.append(merged)
    
    # 按 quality_score 降序, 然后按 speed 降序
    enriched.sort(key=lambda n: (-n.get('quality_score', 0), -(n.get('speed_kbps') or 0)))
    return enriched


# ============= 主流程 =============
def main(force=False):
    if not os.path.exists(INPUT_YAML):
        print(f"✗ {INPUT_YAML} 不存在")
        return 1

    yaml_mtime = datetime.fromtimestamp(os.path.getmtime(INPUT_YAML), tz=timezone.utc).isoformat()

    # ===== Idempotent short-circuit =====
    # 如果 yaml_mtime 已经在 rounds 表里, 说明 subs-check 还没出新结果, 不需要重做
    # 例外: --force 参数强制重新生成 (调试用)
    if not force:
        try:
            db_check = get_history_db()
            existing = db_check.execute(
                "SELECT round_id FROM rounds WHERE yaml_mtime = ? LIMIT 1",
                (yaml_mtime,)
            ).fetchone()
            db_check.close()
            if existing:
                # 已处理过, 静默退出 (cron 每 30min 跑 11 次都会走这, 不刷日志)
                return 0
        except Exception:
            pass  # DB 异常不阻塞主流程

    print(f"  {INPUT_YAML} mtime={yaml_mtime}")

    # 读 token
    token = load_token()
    if token:
        token_dir = os.path.join(OUT_DIR, token)
        Path(token_dir).mkdir(parents=True, exist_ok=True)
        # token 子目录权限收紧 (只 root 可改, 但 nginx 要能读 → 755)
        os.chmod(token_dir, 0o755)
        print(f"  ✓ token={token[:8]}... (订阅文件写入 {token_dir})")
        sub_dir = token_dir   # 订阅文件写这里
    else:
        print(f"  ⚠️  没找到 TOKEN, 订阅文件写到 {OUT_DIR} (无鉴权模式)")
        sub_dir = OUT_DIR

    with open(INPUT_YAML) as f:
        data = yaml.safe_load(f)
    proxies = data.get('proxies', [])
    print(f"  解析 {len(proxies)} 节点")

    # 协议分布
    type_counts = {}
    for p in proxies:
        t = p.get('type', 'unknown')
        type_counts[t] = type_counts.get(t, 0) + 1
    print(f"  协议分布: {type_counts}")

    # 节点摘要 (脱敏)
    summaries = [node_to_summary(p) for p in proxies]
    sigs = sorted(s['sig'] for s in summaries)
    nodes_hash = hashlib.sha256(('|'.join(sigs)).encode()).hexdigest()[:16]
    print(f"  nodes_hash={nodes_hash}")

    # 转换 v2ray
    v2ray_lines = []
    skipped_types = {}
    for p in proxies:
        url = to_v2ray_url(p)
        if url:
            v2ray_lines.append(url)
        else:
            t = p.get('type', 'unknown')
            skipped_types[t] = skipped_types.get(t, 0) + 1
    print(f"  转换: {len(v2ray_lines)} v2ray URL, 跳过 {skipped_types}")

    # ===== 写订阅文件到 token 子目录 =====
    # 注: subs-check 已把 all.yaml 直接写到 token 子目录, 我们只生成衍生文件
    # 如果 INPUT_YAML 不在 token 子目录 (回退模式 = subs-check 老进程写到老路径),
    # 则复制到 token 子目录, 然后删除老路径副本 (不让它残留, 即便 nginx 已 403)
    target_yaml = os.path.join(sub_dir, 'all.yaml')
    if os.path.abspath(INPUT_YAML) != os.path.abspath(target_yaml):
        import shutil
        shutil.copy2(INPUT_YAML, target_yaml)
        print(f"  ✓ 复制 all.yaml 到 token 子目录")
        # 安全清理: 删除老路径副本 (subs-check 下次重启后会自己写到 token 子目录)
        if INPUT_YAML.startswith(OUT_DIR + '/') and not INPUT_YAML.startswith(sub_dir + '/'):
            try:
                os.remove(INPUT_YAML)
                print(f"  ✓ 清理老路径残留: {INPUT_YAML}")
            except OSError as e:
                print(f"  ⚠️  无法删除 {INPUT_YAML}: {e}")

    # v2ray.txt + base64.txt
    v2ray_txt = '\n'.join(v2ray_lines) + '\n'
    with open(os.path.join(sub_dir, 'v2ray.txt'), 'w') as f:
        f.write(v2ray_txt)
    base64_data = base64.b64encode(v2ray_txt.encode()).decode()
    with open(os.path.join(sub_dir, 'base64.txt'), 'w') as f:
        f.write(base64_data)

    # all-config.yaml (完整 mihomo config)
    write_full_config(proxies, type_counts, sub_dir)

    # ===== 历史 DB + diff =====
    db = get_history_db()

    # 找上一轮 (最新一条不重复 mtime 的)
    prev = db.execute("""
        SELECT round_id, nodes_hash, total_nodes
        FROM rounds ORDER BY round_id DESC LIMIT 1
    """).fetchone()

    diff_added = []     # 这轮新增 (上轮没有)
    diff_removed = []   # 这轮消失 (上轮有, 这轮没)
    diff_kept = []      # 两轮都有

    # 取上轮 nodes.json (如果存在), 否则只能算 size diff
    prev_sigs_set = set()
    prev_nodes_path = os.path.join(OUT_DIR, 'nodes.json.prev')
    if os.path.exists(prev_nodes_path):
        try:
            with open(prev_nodes_path) as f:
                prev_summaries = json.load(f).get('nodes', [])
                prev_sigs_set = {n.get('sig') for n in prev_summaries if n.get('sig')}
        except Exception:
            pass

    cur_sigs_set = {s['sig'] for s in summaries}
    diff_added_sigs = cur_sigs_set - prev_sigs_set
    diff_removed_sigs = prev_sigs_set - cur_sigs_set
    diff_kept_sigs = cur_sigs_set & prev_sigs_set

    # 找出对应节点详情
    sig_to_node = {s['sig']: s for s in summaries}
    diff_added = [sig_to_node[sig] for sig in diff_added_sigs if sig in sig_to_node]

    # diff_removed 我们没有上轮详情 (除了 sig), 只能记数
    print(f"  diff: +{len(diff_added)}, -{len(diff_removed_sigs)}, ={len(diff_kept_sigs)}")

    # 入库 (UNIQUE on yaml_mtime, 重复跳过)
    is_new_round = False
    new_round_id = None
    try:
        cur = db.execute("""
            INSERT INTO rounds (timestamp, yaml_mtime, total_nodes, protocols_json,
                nodes_hash, diff_added, diff_removed, diff_kept)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            yaml_mtime,
            len(proxies),
            json.dumps(type_counts),
            nodes_hash,
            len(diff_added),
            len(diff_removed_sigs),
            len(diff_kept_sigs),
        ))
        new_round_id = cur.lastrowid
        db.commit()
        is_new_round = True
        print(f"  ✓ rounds 表新增一行 (round_id={new_round_id})")
    except sqlite3.IntegrityError:
        print(f"  ℹ️  本轮 mtime 已记录, 不重复入库")
        # 取已有的 round_id (用于 nodes_history 更新)
        row = db.execute("SELECT round_id FROM rounds WHERE yaml_mtime = ?", (yaml_mtime,)).fetchone()
        if row:
            new_round_id = row[0]

    # ===== 节点级历史更新 (方向 A) =====
    # 即使 is_new_round=False (force 重跑), 只要有 round_id 也可更新
    if new_round_id is not None:
        n_new, n_recur, n_react = update_nodes_history(db, summaries, new_round_id)
        n_unb, n_purged = cleanup_dead_nodes(db, new_round_id)
        print(f"  ✓ 节点历史: 新 {n_new}, 复现 {n_recur}, 解封重现 {n_react}; "
              f"自动解封 {n_unb}, 清理 30 轮未见 {n_purged}")

        # ===== v2.3 节点级触发点 ②: lq_node 累加 + 持续低质拉黑 =====
        if is_new_round:
            n_node_blacklisted = apply_lq_node_and_blacklist(db, new_round_id)
            if n_node_blacklisted:
                print(f"  ⛔ 节点拉黑 ② (lq_node≥5): {n_node_blacklisted}")

        # ===== 源级质量评分 (v2.3: 信号 B 分档减分 + 触发点 ③④) =====
        sq_result = update_source_quality(new_round_id)
        if sq_result:
            print(f"  ✓ 源级评分: 更新 {sq_result['updated']} 源, "
                  f"拉黑 ③ {sq_result['blacklisted_3_lq']}, "
                  f"拉黑 ④ {sq_result['blacklisted_4_lst']}, "
                  f"黑名单到期复活 {sq_result['unblocked']}")

    # ===== 写衍生 JSON =====
    # nodes.json (前端表格)
    nodes_path = os.path.join(OUT_DIR, 'nodes.json')
    if is_new_round and os.path.exists(nodes_path):
        # 备份当前 nodes.json 为 nodes.json.prev (供下次 diff)
        os.replace(nodes_path, prev_nodes_path)

    # 用 nodes_history 增强 summaries (加 quality_score / total_appearances 等)
    enriched = enrich_summaries_with_history(db, summaries)
    
    with open(nodes_path, 'w') as f:
        json.dump({
            'last_run': datetime.now().isoformat(),
            'yaml_mtime': yaml_mtime,
            'nodes_hash': nodes_hash,
            'total': len(enriched),
            'nodes': enriched,
        }, f, ensure_ascii=False, indent=2)

    # diff.json (前端 diff 区块)
    diff_path = os.path.join(OUT_DIR, 'diff.json')
    with open(diff_path, 'w') as f:
        json.dump({
            'last_run': datetime.now().isoformat(),
            'is_new_round': is_new_round,
            'added_count': len(diff_added),
            'removed_count': len(diff_removed_sigs),
            'kept_count': len(diff_kept_sigs),
            'added': diff_added[:50],   # 限制前 50 个不撑爆 API
            'removed_sigs': list(diff_removed_sigs)[:50],
        }, f, ensure_ascii=False, indent=2)

    # 历史趋势 (最近 20 轮)
    history_path = os.path.join(OUT_DIR, 'history.json')
    rows = db.execute("""
        SELECT round_id, timestamp, total_nodes, protocols_json,
            diff_added, diff_removed, diff_kept
        FROM rounds ORDER BY round_id DESC LIMIT 20
    """).fetchall()
    history = []
    for rid, ts, tot, protos_json, da, dr, dk in rows:
        try:
            protos = json.loads(protos_json) if protos_json else {}
        except Exception:
            protos = {}
        history.append({
            'round_id': rid,
            'timestamp': ts,
            'total_nodes': tot,
            'protocols': protos,
            'diff': {'added': da, 'removed': dr, 'kept': dk},
        })
    with open(history_path, 'w') as f:
        json.dump({'history': history}, f, ensure_ascii=False, indent=2)

    # stats.json (监控 JSON, 留在 OUT_DIR 不带 token, 前端能读)
    # urls 字段不放完整订阅 URL (前端 = 公开监控页, 不应暴露)
    # 真正的订阅 URL 由 notify-telegram.py 读 free-pool.conf 拼出
    stats = {
        'last_run': datetime.now().isoformat(),
        'yaml_mtime': yaml_mtime,
        'total_nodes': len(proxies),
        'protocols': type_counts,
        'v2ray_supported': len(v2ray_lines),
        'v2ray_skipped': skipped_types,
        'is_new_round': is_new_round,
        'token_protected': bool(token),
    }
    with open(os.path.join(OUT_DIR, 'stats.json'), 'w') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"  ✓ 写入 nodes.json / diff.json / history.json / stats.json")

    # ===== 新轮次入库后, 立即触发 Telegram 推送 (避免 cron 等待) =====
    if is_new_round:
        try:
            import subprocess
            r = subprocess.run(
                ['/opt/subs-check/scripts/notify-telegram.py'],
                capture_output=True, timeout=30, text=True
            )
            if r.returncode == 0:
                print(f"  ✓ 级联触发 Telegram 推送: {r.stdout.strip()}")
            else:
                print(f"  ⚠️  Telegram 推送非零返回: {r.returncode}, stderr={r.stderr.strip()[:200]}")
        except Exception as e:
            print(f"  ⚠️  Telegram 推送异常 (会被下一次 cron 兜底): {e}")

    return 0


if __name__ == '__main__':
    force = '--force' in sys.argv
    sys.exit(main(force=force))
