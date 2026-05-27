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
    blacklisted_until TEXT,            -- v3.0 已废弃 (无黑名单), 保留列兼容旧库
    quality_score REAL DEFAULT 50.0,   -- 综合质量分 (0-100), v3.0 默认 50
    state TEXT DEFAULT 'testing',      -- v3.0: testing / decaying / recovering
    last_round_id INTEGER,             -- 最后出现的 round_id
    region TEXT,
    protocol TEXT,
    sample_name TEXT                   -- 最近一次的展示名
);

CREATE INDEX IF NOT EXISTS idx_nodes_score ON nodes_history(quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_nodes_blacklist ON nodes_history(blacklisted_until);
CREATE INDEX IF NOT EXISTS idx_nodes_state ON nodes_history(state);
"""


def get_history_db():
    Path(HISTORY_DB).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(HISTORY_DB)
    db.executescript(HISTORY_SCHEMA)
    # v3.0 迁移: 旧库可能没 state 列
    try:
        db.execute("ALTER TABLE nodes_history ADD COLUMN state TEXT DEFAULT 'testing'")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE nodes_history ADD COLUMN consecutive_low_quality_node INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
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
    """脱敏后的节点信息 (给前端表格用, 不含密码/uuid)

    v3.0 节点名规范化:
      - subs-check 在 sub-url 带 #fragment 时, 会把 sub_tag 拼进节点名 ("|sinspired/subs-check")
      - 拆 display_name 保留 "🇸🇬SG_224|1.2MB/s" 两段, sub_tag 单独字段
      - 避免前端表格列拥挤 + 让用户能筛选 / 排序 sub_tag
    """
    raw_name = p.get('name', '')
    sub_tag = p.get('sub_tag') or ''
    display_name = raw_name
    if raw_name.count('|') >= 2:
        parts = raw_name.split('|', 2)
        display_name = '|'.join(parts[:2])
        if not sub_tag:
            sub_tag = parts[2]
    return {
        'name': display_name,
        'sub_tag': sub_tag or None,
        'type': p.get('type', ''),
        'server': p.get('server', ''),
        'port': p.get('port', 0),
        'region': extract_region_from_name(display_name),
        'speed_kbps': extract_speed_from_name(display_name),
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
    更新节点级历史表 (v3.0: 三态机 + 信号 B+C 直接累加 quality_score)

    v3.0 评分逻辑:
      - 仅 testing 状态节点接受信号 B+C 累加
      - decaying / recovering 状态本轮出现也只更新 last_seen / sample_name (分数由 apply_hysteresis_node 控)
      - 本轮出现节点: 累加 +1 (PRESENT) + 测速档 (信号 C 五档)
      - 触 100 → decaying, 触 0 → recovering
      - 本轮未出现节点 (testing 态): -3, 不累加 fails (避免冤死)

    返回 (新出现, 旧节点, 重新激活的节点数)
    """
    now = datetime.now(timezone.utc).isoformat()
    seen_sigs = set()
    n_new = n_recurring = 0

    # === 1. 处理本轮出现的节点 (信号 B+C) ===
    for s in summaries:
        sig = s['sig']
        if not sig or sig in seen_sigs:
            continue
        seen_sigs.add(sig)

        speed = s.get('speed_kbps')   # v3.0: None 视为 TIMEOUT, 不强转 0
        region = s.get('region')
        proto = s.get('type')
        name = s.get('name', '')[:80]  # 限长防注入 (display_name, 不含 sub_tag)

        row = db.execute(
            "SELECT total_appearances, consecutive_appearances, avg_speed_kbps, "
            "quality_score, last_round_id, state "
            "FROM nodes_history WHERE canonical_sig = ?",
            (sig,)
        ).fetchone()

        if row is None:
            # 全新节点 - 默认 50 (testing 态), 加上本轮信号 B+C
            n_new += 1
            cons_apps = 1
            delta = calc_round_delta(present=True, cons_apps=cons_apps, speed_kbps=speed)
            new_score = max(0.0, min(100.0, NODE_DEFAULT_SCORE + delta))
            new_state = 'testing'
            if new_score >= 100:
                new_score = 100.0
                new_state = 'decaying'
            elif new_score <= 0:
                new_score = 0.0
                new_state = 'recovering'
            db.execute("""
                INSERT INTO nodes_history (
                    canonical_sig, first_seen, last_seen, last_speed_kbps, avg_speed_kbps,
                    total_appearances, consecutive_appearances, last_round_id,
                    region, protocol, sample_name, quality_score, state,
                    consecutive_low_quality_node
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (sig, now, now, speed if speed else 0, speed if speed else 0,
                  cons_apps, round_id, region, proto, name, new_score, new_state))
        else:
            (total_apps, cons_apps, avg_speed, old_score, last_rid, state) = row

            # 是不是连续出现 (上一轮 round_id == 当前-1)
            if last_rid == round_id - 1:
                cons_apps += 1
            else:
                cons_apps = 1
            total_apps += 1
            new_avg = (avg_speed or 0) * 0.7 + (speed or 0) * 0.3

            # v3.0: 仅 testing 状态接受信号 B+C 累加 (decaying / recovering 由 hysteresis 控)
            new_score = old_score or NODE_DEFAULT_SCORE
            new_state = state or 'testing'
            if state == 'testing':
                delta = calc_round_delta(present=True, cons_apps=cons_apps, speed_kbps=speed)
                new_score = max(0.0, min(100.0, new_score + delta))
                if new_score >= 100:
                    new_score = 100.0
                    new_state = 'decaying'
                elif new_score <= 0:
                    new_score = 0.0
                    new_state = 'recovering'

            n_recurring += 1
            db.execute("""
                UPDATE nodes_history SET
                    last_seen = ?,
                    last_speed_kbps = ?,
                    avg_speed_kbps = ?,
                    total_appearances = ?,
                    consecutive_appearances = ?,
                    last_round_id = ?,
                    region = ?,
                    protocol = ?,
                    sample_name = ?,
                    quality_score = ?,
                    state = ?
                WHERE canonical_sig = ?
            """, (now, speed if speed else 0, new_avg, total_apps, cons_apps, round_id,
                  region, proto, name, new_score, new_state, sig))

    # === 2. 处理本轮未出现的 testing 态节点 (信号 B: -3, 触 0 → recovering) ===
    # 仅处理 testing 状态且最近 30 轮内还活的, 避免对早就死的反复扣分
    db.execute("""
        UPDATE nodes_history SET
            quality_score = MAX(0, COALESCE(quality_score, ?) - ?),
            consecutive_appearances = 0
        WHERE state = 'testing'
          AND last_round_id IS NOT NULL
          AND last_round_id < ?
          AND last_round_id >= ?
    """, (NODE_DEFAULT_SCORE, NODE_ABSENT_PENALTY, round_id, round_id - 30))

    # 触底 0 → recovering
    db.execute("""
        UPDATE nodes_history SET state='recovering', quality_score=0
        WHERE state='testing' AND quality_score <= 0
    """)

    db.commit()
    return n_new, n_recurring, 0   # n_reactivated 兼容旧返回签名 (v3.0 无黑名单)


def apply_lq_node_and_blacklist(db, round_id: int):
    """v3.0: 已废弃 (无黑名单系统). 保留空 stub 兼容旧调用方.

    v3.0 改造: 节点 quality_score 触 0 → state='recovering', 自动从底回升;
    不再有 48h 黑名单. 源级也类似处理 (见 update_source_quality).
    """
    return 0


# ============= v3.0 节点级评分常量 (Hysteresis 三态机) =============
NODE_DEFAULT_SCORE = 50.0            # v3.0: 初始中点 (新节点从 50 起跑, 进 testing 态)
NODE_LOW_QUALITY_THRESHOLD = 30      # 报告/统计阈值, v3.0 不再触发拉黑

# Hysteresis 被动衰减/恢复 (decaying / recovering 状态用)
PASSIVE_RATE = 1.0                   # 每轮 ±1 分基础速率
PASSIVE_JITTER = 0.3                 # ±0.3 抖动

# 信号 B (轮次)
NODE_PRESENT_BONUS = 1               # v3.0: 本轮出现 +1
NODE_ABSENT_PENALTY = 3              # 本轮未出现 -3 (避免冤死, 仅近期还活的节点)

# 信号 C (测速, v3.0 五档)
NODE_SPEED_EXCEL_BONUS = 3           # >= 2048 KB/s
NODE_SPEED_GOOD_BONUS = 1            # 1024-2047 KB/s
NODE_SPEED_OK_BONUS = 0              # 512-1023 KB/s
NODE_SPEED_POOR_PENALTY = 2          # 100-511 KB/s
NODE_SPEED_TERRIBLE_PENALTY = 5      # < 100 KB/s
NODE_SPEED_TIMEOUT_PENALTY = 8       # 0 / 测速失败 (speed_kbps=None)


def calc_quality_score(*args, **kwargs) -> float:
    """v3.0: 已废弃. 节点 quality_score 由信号 ABC 直接累积维护."""
    return NODE_DEFAULT_SCORE


def calc_round_delta(present: bool, cons_apps: int, speed_kbps) -> float:
    """v3.0 信号 B (轮次) + 信号 C (测速) 单轮 delta.

    explicit None 测速 = TIMEOUT (节点没测出速度, 视为故障); 0 也算 TIMEOUT.
    探活 (信号 A) 由 incremental-check.py 直接更新, 不在此处.
    """
    delta = 0.0
    # 信号 B: 轮次
    if present:
        delta += NODE_PRESENT_BONUS
    else:
        delta -= NODE_ABSENT_PENALTY
        return delta  # 未出现的没有测速信号

    # 信号 C: 测速 (本轮出现, 未测速 = TIMEOUT)
    if speed_kbps is None or speed_kbps <= 0:
        delta -= NODE_SPEED_TIMEOUT_PENALTY
    elif speed_kbps >= 2048:
        delta += NODE_SPEED_EXCEL_BONUS
    elif speed_kbps >= 1024:
        delta += NODE_SPEED_GOOD_BONUS
    elif speed_kbps >= 512:
        delta += NODE_SPEED_OK_BONUS
    elif speed_kbps >= 100:
        delta -= NODE_SPEED_POOR_PENALTY
    else:
        delta -= NODE_SPEED_TERRIBLE_PENALTY
    return delta


def apply_hysteresis_node(db, round_id: int):
    """v3.0 节点三态机: 被动衰减 / 恢复

    decaying:  score -= 1±0.3 → 触 50 → testing
    recovering: score += 1±0.3 → 触 50 → testing
    testing:    由 calc_round_delta + incremental-check 直接累加; 触 100 → decaying, 触 0 → recovering

    本函数仅处理 decaying / recovering 两态的被动调整 (testing 已由 update_nodes_history 处理).
    """
    import random
    rows = db.execute("""
        SELECT canonical_sig, state, quality_score
        FROM nodes_history
        WHERE state IN ('decaying', 'recovering')
    """).fetchall()
    n_dec_to_test = n_rec_to_test = 0
    for sig, state, score in rows:
        score = score or NODE_DEFAULT_SCORE
        jitter = random.uniform(-PASSIVE_JITTER, PASSIVE_JITTER)
        if state == 'decaying':
            new_score = max(0.0, min(100.0, score - PASSIVE_RATE + jitter))
            if new_score <= NODE_DEFAULT_SCORE:
                new_score = NODE_DEFAULT_SCORE
                new_state = 'testing'
                n_dec_to_test += 1
            else:
                new_state = 'decaying'
        else:  # recovering
            new_score = max(0.0, min(100.0, score + PASSIVE_RATE + jitter))
            if new_score >= NODE_DEFAULT_SCORE:
                new_score = NODE_DEFAULT_SCORE
                new_state = 'testing'
                n_rec_to_test += 1
            else:
                new_state = 'recovering'
        db.execute("""
            UPDATE nodes_history SET state=?, quality_score=?
            WHERE canonical_sig=?
        """, (new_state, new_score, sig))
    db.commit()
    return n_dec_to_test, n_rec_to_test


def cleanup_dead_nodes(db, current_round_id: int, fresh_threshold_rounds: int = 30):
    """v3.0: 清掉超过 N 轮 (~30轮 ≈ 7天) 没出现的节点

    v3.0 取消节点黑名单, 0 分进 recovering 自动恢复, 不需要解封逻辑.
    """
    n_purged = db.execute("""
        DELETE FROM nodes_history
        WHERE last_round_id IS NOT NULL
          AND ? - last_round_id > ?
    """, (current_round_id, fresh_threshold_rounds)).rowcount
    db.commit()
    return 0, n_purged   # 保持返回签名兼容


# ============= v3.0 源级质量评分 (Hysteresis 三态机) =============
SOURCES_DB = "/opt/subs-check/scripts/source-scores.db"

# v3.0 源级评分常量 (拉取信号 A)
SOURCE_FETCH_OK = 3                  # 拉取成功 (有节点)
SOURCE_FETCH_EMPTY = -5              # 拉取成功但 0 节点
SOURCE_FETCH_FAIL = -10              # 拉取失败 (HTTP 4xx/5xx)
SOURCE_FETCH_TIMEOUT = -8            # 拉取超时

# v3.0 节点质量反馈 (信号 B 四档)
SOURCE_NQ_HIGH_BONUS = 2             # 节点均分 >= 70
SOURCE_NQ_MID_BONUS = 0              # 50-69
SOURCE_NQ_LOW_PENALTY = 3            # 30-49
SOURCE_NQ_TERRIBLE_PENALTY = 8       # < 30

SOURCE_DEFAULT_SCORE_V3 = 50.0       # 中点起跑
SOURCE_LOW_QUALITY_THRESHOLD = 30    # 报告阈值, v3.0 不再触发拉黑
MIN_NODES_FOR_QUALITY_EVAL = 5       # 节点 < 5 不评估


def apply_hysteresis_source(db):
    """v3.0 源三态机: 被动衰减 / 恢复

    decaying / recovering 状态由本函数被动调整, testing 由 sync-lza6 + update_source_quality 累加.
    每轮 (convert-formats round 切换时) 调用一次.
    """
    import random
    rows = db.execute("""
        SELECT url, state, score FROM sources
        WHERE state IN ('decaying', 'recovering')
    """).fetchall()
    n_dec_to_test = n_rec_to_test = 0
    for url, state, score in rows:
        score = score if score is not None else SOURCE_DEFAULT_SCORE_V3
        jitter = random.uniform(-PASSIVE_JITTER, PASSIVE_JITTER)
        if state == 'decaying':
            new_score = max(0.0, min(100.0, score - PASSIVE_RATE + jitter))
            if new_score <= SOURCE_DEFAULT_SCORE_V3:
                new_score = SOURCE_DEFAULT_SCORE_V3
                new_state = 'testing'
                n_dec_to_test += 1
            else:
                new_state = 'decaying'
        else:  # recovering
            new_score = max(0.0, min(100.0, score + PASSIVE_RATE + jitter))
            if new_score >= SOURCE_DEFAULT_SCORE_V3:
                new_score = SOURCE_DEFAULT_SCORE_V3
                new_state = 'testing'
                n_rec_to_test += 1
            else:
                new_state = 'recovering'
        db.execute("""
            UPDATE sources SET state=?, score=? WHERE url=?
        """, (new_state, new_score, url))
    db.commit()
    return n_dec_to_test, n_rec_to_test


def update_source_quality(round_id: int):
    """v3.0 源级质量评分 (信号 B: 节点均分反馈)

    每轮跑一次. 流程:
      1. 算每个源贡献节点 (5 轮窗口) 的均分
      2. 仅 testing 状态源接受信号 B 累加 (decaying / recovering 由 hysteresis 控)
      3. 按均分档位调整 score: >=70 +2 / 50-69 0 / 30-49 -3 / <30 -8
      4. 触 100 → decaying, 触 0 → recovering (无黑名单)
      5. 跑 hysteresis 让 decaying / recovering 状态被动调整
    """
    if not os.path.exists(SOURCES_DB):
        return None

    score_db = sqlite3.connect(SOURCES_DB)

    # 兼容老库: state 列必须存在
    try:
        score_db.execute("ALTER TABLE sources ADD COLUMN state TEXT DEFAULT 'testing'")
        score_db.commit()
    except sqlite3.OperationalError:
        pass

    score_db.execute(f"ATTACH DATABASE '{HISTORY_DB}' AS hdb")

    now = datetime.now(timezone.utc).isoformat()
    n_updated = n_to_decaying = n_to_recovering = 0

    # === 1. 算每个源该轮贡献节点平均分 ===
    rows = score_db.execute("""
        SELECT m.source_url, COUNT(*) as node_count, AVG(h.quality_score) as avg_score
        FROM source_node_map m
        JOIN hdb.nodes_history h ON h.canonical_sig = m.canonical_sig
        WHERE m.last_seen_round >= ?
        GROUP BY m.source_url
    """, (round_id - 5,)).fetchall()

    for source_url, node_count, avg_score in rows:
        if avg_score is None or node_count < MIN_NODES_FOR_QUALITY_EVAL:
            continue

        # 写入 source_quality_history (UNIQUE on source+round)
        below_50 = 1 if avg_score < 50 else 0
        try:
            score_db.execute("""
                INSERT INTO source_quality_history
                    (source_url, round_id, timestamp, node_count, avg_quality_score, below_50)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (source_url, round_id, now, node_count, round(avg_score, 2), below_50))
        except sqlite3.IntegrityError:
            continue   # 重跑场景

        # v3.0: 仅 testing 状态源累加信号 B
        cur = score_db.execute(
            "SELECT state, score FROM sources WHERE url=?", (source_url,)
        ).fetchone()
        if not cur:
            continue
        state, cur_score = cur
        if state != 'testing':
            continue

        if avg_score >= 70:
            delta = SOURCE_NQ_HIGH_BONUS
        elif avg_score >= 50:
            delta = SOURCE_NQ_MID_BONUS
        elif avg_score >= 30:
            delta = -SOURCE_NQ_LOW_PENALTY
        else:
            delta = -SOURCE_NQ_TERRIBLE_PENALTY

        new_score = max(0.0, min(100.0, (cur_score or SOURCE_DEFAULT_SCORE_V3) + delta))
        new_state = 'testing'
        if new_score >= 100:
            new_score = 100.0
            new_state = 'decaying'
            n_to_decaying += 1
        elif new_score <= 0:
            new_score = 0.0
            new_state = 'recovering'
            n_to_recovering += 1

        score_db.execute("""
            UPDATE sources SET score=?, state=? WHERE url=?
        """, (new_score, new_state, source_url))
        n_updated += 1

    score_db.commit()

    # === 2. 跑 hysteresis (decaying / recovering 被动调整) ===
    n_dec_to_test, n_rec_to_test = apply_hysteresis_source(score_db)

    score_db.close()

    return {
        'updated': n_updated,
        'to_decaying': n_to_decaying,
        'to_recovering': n_to_recovering,
        'hysteresis_dec_to_test': n_dec_to_test,
        'hysteresis_rec_to_test': n_rec_to_test,
    }


# ============= enrich =============
def enrich_summaries_with_history(db, summaries: list) -> list:
    """
    把 nodes_history 表的 quality_score / total_appearances / state 等数据合并到 summaries
    返回的列表按 quality_score 降序排序 (前端表格优先看高分节点)
    """
    sigs = [s['sig'] for s in summaries if s.get('sig')]
    if not sigs:
        return summaries

    placeholders = ','.join('?' * len(sigs))
    rows = db.execute(f"""
        SELECT canonical_sig, quality_score, total_appearances, consecutive_appearances,
               avg_speed_kbps, incremental_pass, incremental_fail, state
        FROM nodes_history WHERE canonical_sig IN ({placeholders})
    """, sigs).fetchall()

    history = {r[0]: {
        'quality_score': round(r[1], 1) if r[1] is not None else 50.0,
        'appearances': r[2],
        'consecutive': r[3],
        'avg_speed_kbps': round(r[4]) if r[4] else 0,
        'inc_pass': r[5],
        'inc_fail': r[6],
        'state': r[7] or 'testing',
    } for r in rows}

    enriched = []
    for s in summaries:
        merged = dict(s)
        h = history.get(s['sig'], {})
        merged.update({
            'quality_score': h.get('quality_score', 50.0),
            'appearances': h.get('appearances', 1),
            'consecutive': h.get('consecutive', 1),
            'avg_speed_kbps': h.get('avg_speed_kbps', s.get('speed_kbps') or 0),
            'inc_pass': h.get('inc_pass', 0),
            'inc_fail': h.get('inc_fail', 0),
            'state': h.get('state', 'testing'),
        })
        enriched.append(merged)

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

        # ===== v3.0 节点三态机被动衰减/恢复 (decaying / recovering 状态) =====
        if is_new_round:
            n_dec_to_test, n_rec_to_test = apply_hysteresis_node(db, new_round_id)
            if n_dec_to_test or n_rec_to_test:
                print(f"  ✓ 节点三态机: decaying→testing {n_dec_to_test}, "
                      f"recovering→testing {n_rec_to_test}")

        # ===== 源级质量评分 (v3.0: 三态机 + 信号 B 节点均分反馈) =====
        sq_result = update_source_quality(new_round_id)
        if sq_result:
            print(f"  ✓ 源级评分 v3.0: 累加 {sq_result['updated']} 源, "
                  f"→decaying {sq_result['to_decaying']}, "
                  f"→recovering {sq_result['to_recovering']}, "
                  f"hysteresis dec→test {sq_result['hysteresis_dec_to_test']}, "
                  f"rec→test {sq_result['hysteresis_rec_to_test']}")

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
