#!/usr/bin/env python3
"""
源-节点映射构建器

目标:
  - 抓取 sub-urls.txt 里每个源
  - 解析出节点 (Clash YAML / V2Ray base64 / V2Ray plain URL)
  - 计算每个节点的 canonical_sig (server:port:type)
  - 写入 source_node_map 表 (源-节点 N:N 关系)

用途:
  - 后续 convert-formats.py 跑完一轮后, 用这个映射计算每个源的 "贡献节点平均分"
  - 连续 5 轮平均分 <50 → 源拉黑

设计:
  - 并发 10 抓取 (轻任务, 避免被 GitHub rate-limit)
  - 单源 timeout 15s
  - 同 source-check + tolerant 解析: 失败的源跳过不致命
  - idempotent: 多次跑只更新 last_seen_round
"""
import os
import sys
import re
import yaml
import json
import base64
import sqlite3
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

SUB_URLS = "/opt/subs-check/config/sub-urls.txt"
SCORES_DB = "/opt/subs-check/scripts/source-scores.db"
HISTORY_DB = "/opt/subs-check/scripts/history.db"

CONCURRENT = 10
TIMEOUT = 15
USER_AGENT = "clash.meta (compatible; subs-check)"


def fetch(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode('utf-8', errors='ignore')
    except Exception:
        return None


def parse_clash(text: str) -> list:
    """Clash YAML → [{server, port, type}]"""
    try:
        d = yaml.safe_load(text)
        if not isinstance(d, dict):
            return []
        proxies = d.get('proxies') or d.get('Proxy') or []
        if not isinstance(proxies, list):
            return []
        return [
            {'server': p.get('server'), 'port': p.get('port'), 'type': p.get('type')}
            for p in proxies if isinstance(p, dict) and p.get('server') and p.get('port')
        ]
    except Exception:
        return []


def parse_v2ray_url(line: str) -> dict | None:
    """单行 v2ray-style URL → {server, port, type}"""
    line = line.strip()
    if not line:
        return None
    
    # vmess://base64(json)
    if line.startswith('vmess://'):
        try:
            payload = line[8:]
            # 补 padding
            payload += '=' * (4 - len(payload) % 4)
            j = json.loads(base64.b64decode(payload).decode('utf-8', errors='ignore'))
            return {'server': j.get('add'), 'port': int(j.get('port', 0)), 'type': 'vmess'}
        except Exception:
            return None
    
    # vless://uuid@server:port?params#name
    if line.startswith('vless://'):
        m = re.match(r'vless://[^@]+@([^:]+):(\d+)', line)
        if m:
            return {'server': m.group(1), 'port': int(m.group(2)), 'type': 'vless'}
    
    # trojan://password@server:port?params#name
    if line.startswith('trojan://'):
        m = re.match(r'trojan://[^@]+@([^:]+):(\d+)', line)
        if m:
            return {'server': m.group(1), 'port': int(m.group(2)), 'type': 'trojan'}
    
    # ss://base64(method:password)@server:port  或  ss://base64(method:password@server:port)
    if line.startswith('ss://'):
        try:
            body = line[5:].split('#')[0].split('?')[0]
            if '@' in body:
                # 标准格式
                m = re.match(r'[^@]+@([^:]+):(\d+)', body)
                if m:
                    return {'server': m.group(1), 'port': int(m.group(2)), 'type': 'ss'}
            else:
                # 全部 base64
                body += '=' * (4 - len(body) % 4)
                decoded = base64.urlsafe_b64decode(body).decode('utf-8', errors='ignore')
                m = re.match(r'[^@]+@([^:]+):(\d+)', decoded)
                if m:
                    return {'server': m.group(1), 'port': int(m.group(2)), 'type': 'ss'}
        except Exception:
            return None
    
    # hysteria2://auth@server:port
    if line.startswith(('hysteria2://', 'hy2://', 'hysteria://')):
        proto = 'hysteria2' if line.startswith(('hysteria2://', 'hy2://')) else 'hysteria'
        m = re.search(r'://[^@]+@([^:]+):(\d+)', line)
        if m:
            return {'server': m.group(1), 'port': int(m.group(2)), 'type': proto}
    
    return None


def parse_v2ray_text(text: str) -> list:
    """V2Ray 纯文本订阅 (一行一个 URL) 或 base64 整体编码"""
    text = text.strip()
    if not text:
        return []
    
    # 试 base64 整体
    if not text.startswith(('vmess://', 'vless://', 'trojan://', 'ss://', 'hysteria')):
        try:
            padded = text + '=' * (4 - len(text) % 4)
            decoded = base64.b64decode(padded).decode('utf-8', errors='ignore')
            if any(decoded.startswith(p) for p in ('vmess://', 'vless://', 'trojan://', 'ss://')):
                text = decoded
        except Exception:
            pass
    
    nodes = []
    for line in text.split('\n'):
        n = parse_v2ray_url(line)
        if n and n.get('server') and n.get('port'):
            nodes.append(n)
    return nodes


def extract_nodes(text: str) -> list:
    """统一入口: 自动识别 Clash YAML / V2Ray URL / base64"""
    if not text:
        return []
    
    # 优先试 Clash YAML (有 proxies: 关键字)
    if 'proxies:' in text or 'Proxy:' in text:
        nodes = parse_clash(text)
        if nodes:
            return nodes
    
    # 试 V2Ray URL/base64
    return parse_v2ray_text(text)


def canonical_sig(node: dict) -> str:
    """生成 server:port:type"""
    s = node.get('server', '')
    p = node.get('port', 0)
    t = node.get('type', 'unknown')
    return f"{s}:{p}:{t}"


def main():
    if not os.path.exists(SUB_URLS):
        print(f"  ✗ {SUB_URLS} 不存在")
        return 1
    
    # 拿当前最大 round_id (用于标记 first_seen_round / last_seen_round)
    if not os.path.exists(HISTORY_DB):
        print(f"  ℹ️  {HISTORY_DB} 不存在 (subs-check 还没出过结果), 仍然能跑但 round_id=0")
        current_round = 0
    else:
        hdb = sqlite3.connect(HISTORY_DB)
        row = hdb.execute("SELECT MAX(round_id) FROM rounds").fetchone()
        current_round = row[0] if row and row[0] else 0
        hdb.close()
    
    # 读 sub-urls.txt
    with open(SUB_URLS) as f:
        urls = [l.strip() for l in f if l.strip() and not l.startswith('#')]
    print(f"[{datetime.now()}] 抓取 {len(urls)} 个源 (current_round={current_round})")
    
    # 并发抓取 + 解析
    results = {}  # url -> [sig, sig, ...]
    fail_count = 0
    
    def worker(url):
        text = fetch(url)
        if text is None:
            return url, None, "fetch_fail"
        nodes = extract_nodes(text)
        sigs = list(set(canonical_sig(n) for n in nodes))
        return url, sigs, "ok"
    
    with ThreadPoolExecutor(max_workers=CONCURRENT) as ex:
        futures = {ex.submit(worker, u): u for u in urls}
        for fut in as_completed(futures):
            try:
                url, sigs, status = fut.result()
                if status == "fetch_fail":
                    fail_count += 1
                    continue
                results[url] = sigs
            except Exception as e:
                fail_count += 1
    
    print(f"  抓取完成: 成功 {len(results)}, 失败 {fail_count}")
    
    # 统计节点
    all_sigs = set()
    for sigs in results.values():
        all_sigs.update(sigs)
    print(f"  共解析出 {len(all_sigs)} 个唯一 sig")
    
    # 写入 source_node_map
    db = sqlite3.connect(SCORES_DB)
    now = datetime.now(timezone.utc).isoformat()
    
    n_inserted = n_updated = 0
    for url, sigs in results.items():
        for sig in sigs:
            cur = db.execute(
                "SELECT first_seen_round FROM source_node_map WHERE source_url=? AND canonical_sig=?",
                (url, sig)
            ).fetchone()
            if cur:
                db.execute(
                    "UPDATE source_node_map SET last_seen_round=? WHERE source_url=? AND canonical_sig=?",
                    (current_round, url, sig)
                )
                n_updated += 1
            else:
                db.execute(
                    "INSERT INTO source_node_map (source_url, canonical_sig, first_seen_round, last_seen_round) "
                    "VALUES (?, ?, ?, ?)",
                    (url, sig, current_round, current_round)
                )
                n_inserted += 1
    
    # 同时给 sources 表打 first_seen_round (新源用于 grace period 判定)
    for url in results.keys():
        db.execute("""
            UPDATE sources SET first_seen_round = COALESCE(first_seen_round, ?)
            WHERE url = ?
        """, (current_round, url))
    
    db.commit()
    db.close()
    
    print(f"  source_node_map: 新增 {n_inserted} 关系, 更新 {n_updated} 关系")
    return 0


if __name__ == '__main__':
    sys.exit(main())
