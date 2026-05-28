#!/usr/bin/env python3
"""
discover-cn-proxies.py — CN 代理源自动发现

目的:
  - 发现免费 CN (中国大陆) HTTP/SOCKS5 代理 API 和列表
  - 存入 cn_proxy_sources 表供 incremental-check.py 使用
  - 不考虑 HK 节点

发现策略:
  1. 已知 API 源 (配置文件)
  2. GitHub 搜索 "free proxy china" 等关键词
  3. 代理聚合网站爬取

cron: 每 6 小时跑一次 (00/06/12/18)
"""
import os
import sys
import json
import sqlite3
import time
import urllib.request
import urllib.error
import urllib.parse
import re
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CN_PROXY_DB = os.path.join(SCRIPT_DIR, "cn-proxy-sources.db")
LOG_FILE = "/var/log/discover-cn-proxies.log"

# ========== 已知 CN 代理 API 源 ==========
KNOWN_CN_PROXY_APIS = [
    {
        "key": "proxyscrape-http",
        "name": "ProxyScrape HTTP (CN)",
        "url": "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=cn&ssl=all&anonymity=all",
        "format": "lines",  # 每行一个 ip:port
        "protocol": "http",
        "priority": 10,
    },
    {
        "key": "proxyscrape-socks5",
        "name": "ProxyScrape SOCKS5 (CN)",
        "url": "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country=cn",
        "format": "lines",
        "protocol": "socks5",
        "priority": 10,
    },
    {
        "key": "proxyscrape-socks4",
        "name": "ProxyScrape SOCKS4 (CN)",
        "url": "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4&timeout=10000&country=cn",
        "format": "lines",
        "protocol": "socks4",
        "priority": 20,
    },
    {
        "key": "geonode-http",
        "name": "Geonode HTTP (CN)",
        "url": "https://proxylist.geonode.com/api/proxy-list?limit=50&page=1&sort_by=lastChecked&sort_type=desc&country=CN&protocols=http%2Chttps",
        "format": "json",
        "protocol": "http",
        "priority": 20,
    },
    {
        "key": "geonode-socks5",
        "name": "Geonode SOCKS5 (CN)",
        "url": "https://proxylist.geonode.com/api/proxy-list?limit=50&page=1&sort_by=lastChecked&sort_type=desc&country=CN&protocols=socks5",
        "format": "json",
        "protocol": "socks5",
        "priority": 20,
    },
    {
        "key": "freeproxylist-http",
        "name": "FreeProxyList HTTP (CN)",
        "url": "https://www.freeproxylists.net/?c=cn&pr=HTTP",
        "format": "html",
        "protocol": "http",
        "priority": 30,
    },
    {
        "key": "proxyscrape-http-fast",
        "name": "ProxyScrape HTTP Fast (CN)",
        "url": "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=cn&ssl=all&anonymity=all",
        "format": "lines",
        "protocol": "http",
        "priority": 15,
    },
    {
        "key": "proxyscrape-socks5-fast",
        "name": "ProxyScrape SOCKS5 Fast (CN)",
        "url": "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=5000&country=cn",
        "format": "lines",
        "protocol": "socks5",
        "priority": 15,
    },
    {
        "key": "geonode-http-all",
        "name": "Geonode HTTP All (CN)",
        "url": "https://proxylist.geonode.com/api/proxy-list?limit=100&page=1&sort_by=lastChecked&sort_type=desc&country=CN&protocols=http%2Chttps",
        "format": "json",
        "protocol": "http",
        "priority": 25,
    },
    {
        "key": "geonode-socks5-all",
        "name": "Geonode SOCKS5 All (CN)",
        "url": "https://proxylist.geonode.com/api/proxy-list?limit=100&page=1&sort_by=lastChecked&sort_type=desc&country=CN&protocols=socks5",
        "format": "json",
        "protocol": "socks5",
        "priority": 25,
    },

]

# ========== GitHub 搜索关键词 ==========
GITHUB_SEARCH_QUERIES = [
    "free proxy china CN list",
    "cn proxy api free",
    "中国免费代理",
    "china socks5 proxy list",
    "free cn http proxy",
    "cn proxy pool",
    "china proxy aggregator",
    "免费代理池 中国",
    "socks5 proxy china free",
    "http proxy china list",
]


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except:
        pass


def db_init():
    """初始化数据库"""
    conn = sqlite3.connect(CN_PROXY_DB, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cn_proxy_sources (
            key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            format TEXT NOT NULL,       -- lines / json / html
            protocol TEXT NOT NULL,     -- http / socks5 / socks4
            priority INTEGER DEFAULT 100,
            enabled INTEGER DEFAULT 1,
            last_checked_at TEXT,
            last_status TEXT,           -- ok / fail / empty
            last_proxy_count INTEGER DEFAULT 0,
            total_fetches INTEGER DEFAULT 0,
            total_proxies INTEGER DEFAULT 0,
            consecutive_empty INTEGER DEFAULT 0,
            note TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cn_proxy_discovery_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discovered_at TEXT NOT NULL,
            source TEXT NOT NULL,       -- github / website / api_test
            query TEXT,
            found_url TEXT,
            added INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    return conn


def upsert_source(conn, key, name, url, fmt, protocol, priority=100, note=None):
    """插入或更新代理源"""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO cn_proxy_sources (key, name, url, format, protocol, priority, created_at, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            name = excluded.name,
            url = excluded.url,
            format = excluded.format,
            protocol = excluded.protocol,
            priority = excluded.priority,
            note = COALESCE(excluded.note, cn_proxy_sources.note)
    """, (key, name, url, fmt, protocol, priority, now, note))


def fetch_url(url, timeout=15):
    """抓取 URL"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "discover-cn-proxies/1.0",
            "Accept": "*/*"
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return None


def parse_lines(text):
    """解析 ip:port 格式"""
    proxies = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            parts = line.rsplit(":", 1)
            if len(parts) == 2:
                try:
                    port = int(parts[1].strip())
                    if 1 <= port <= 65535:
                        proxies.append((parts[0].strip(), port))
                except ValueError:
                    pass
    return proxies


def parse_json_geonode(text):
    """解析 Geonode API 响应"""
    try:
        data = json.loads(text)
        proxies = []
        for item in data.get("data", []):
            ip = item.get("ip")
            port = item.get("port")
            if ip and port:
                try:
                    proxies.append((ip, int(port)))
                except ValueError:
                    pass
        return proxies
    except:
        return []


def test_source(source):
    """测试代理源是否可用, 返回 (status, proxy_count)"""
    url = source["url"]
    fmt = source["format"]

    text = fetch_url(url)
    if not text:
        return "fail", 0

    if fmt == "lines":
        proxies = parse_lines(text)
    elif fmt == "json":
        proxies = parse_json_geonode(text)
    elif fmt == "html":
        # 简单正则提取 ip:port
        matches = re.findall(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s*[:\s]\s*(\d{2,5})', text)
        proxies = [(ip, int(port)) for ip, port in matches if 1 <= int(port) <= 65535]
    else:
        return "fail", 0

    # GeoIP 过滤: 只保留 CN 代理
    cn_proxies = filter_cn_proxies(proxies, source.get("protocol", "http"))
    count = len(cn_proxies)
    if count == 0:
        return "empty", 0
    return "ok", count


def discover_from_github(conn):
    """从 GitHub 搜索发现新的 CN 代理源"""
    found = 0
    for query in GITHUB_SEARCH_QUERIES:
        log(f"  GitHub 搜索: {query}")
        qs = urllib.parse.urlencode({
            "q": query,
            "sort": "updated",
            "order": "desc",
            "per_page": 10
        })
        url = f"https://api.github.com/search/repositories?{qs}"
        text = fetch_url(url)
        if not text:
            continue

        try:
            data = json.loads(text)
        except:
            continue

        items = data.get("items", [])
        for repo in items[:5]:
            full_name = repo.get("full_name", "")
            if not full_name:
                continue

            # 检查常见的代理列表文件路径
            default_branch = repo.get("default_branch", "main")
            candidate_urls = [
                f"https://raw.githubusercontent.com/{full_name}/{default_branch}/proxy.txt",
                f"https://raw.githubusercontent.com/{full_name}/{default_branch}/http.txt",
                f"https://raw.githubusercontent.com/{full_name}/{default_branch}/socks5.txt",
                f"https://raw.githubusercontent.com/{full_name}/{default_branch}/proxies.txt",
                f"https://raw.githubusercontent.com/{full_name}/{default_branch}/list.txt",
            ]

            for cand_url in candidate_urls:
                key = f"github:{full_name}:{os.path.basename(cand_url)}"
                # 跳过已存在的
                existing = conn.execute("SELECT key FROM cn_proxy_sources WHERE key=?", (key,)).fetchone()
                if existing:
                    continue

                # 测试
                text = fetch_url(cand_url)
                if not text:
                    continue

                proxies = parse_lines(text)
                if len(proxies) < 3:
                    continue

                # 过滤: 只保留包含 CN IP 的 (简单判断)
                # 不做严格 GeoIP 过滤, 因为后续 incremental-check 会验证
                protocol = "socks5" if "socks5" in cand_url else "http"
                upsert_source(conn, key, f"GitHub:{full_name}", cand_url, "lines", protocol, priority=50)
                found += 1
                log(f"    ✓ 发现: {full_name} ({len(proxies)} 个代理)")

                conn.execute("""
                    INSERT INTO cn_proxy_discovery_log (discovered_at, source, query, found_url, added)
                    VALUES (?, 'github', ?, ?, 1)
                """, (datetime.now(timezone.utc).isoformat(), query, cand_url))

                break  # 每个 repo 只取一个文件

    conn.commit()
    return found


def discover_from_apis(conn):
    """测试已知 API 源并更新数据库"""
    found = 0
    for api in KNOWN_CN_PROXY_APIS:
        log(f"  测试 API: {api['name']}")
        status, count = test_source(api)

        upsert_source(conn, api["key"], api["name"], api["url"],
                     api["format"], api["protocol"], api["priority"])

        conn.execute("""
            UPDATE cn_proxy_sources SET
                last_checked_at = ?,
                last_status = ?,
                last_proxy_count = ?,
                total_fetches = total_fetches + 1,
                total_proxies = total_proxies + ?,
                consecutive_empty = CASE WHEN ? = 0 THEN consecutive_empty + 1 ELSE 0 END
            WHERE key = ?
        """, (datetime.now(timezone.utc).isoformat(), status, count, count,
              1 if count == 0 else 0, api["key"]))

        if status == "ok":
            found += 1
            log(f"    ✓ {api['name']}: {count} 个代理")
        else:
            log(f"    ✗ {api['name']}: {status}")

    conn.commit()
    return found


# ========== GeoIP 过滤 ==========
# 用 ip-api.com 批量查询, 精确判断 CN IP
# 免费 API: 45 req/min, 批量 100 IP/次

def filter_cn_proxies(proxies: list, protocol: str = "http") -> list:
    """过滤代理列表, 只保留 CN IP (用 ip-api.com 批量查询)"""
    if not proxies:
        return []

    # 去重
    unique_ips = list(set(ip for ip, _ in proxies))

    # 批量查询 (ip-api.com 支持批量, 每次最多 100)
    cn_ips = set()
    for i in range(0, len(unique_ips), 100):
        batch = unique_ips[i:i+100]
        try:
            import json
            data = json.dumps(batch)
            req = urllib.request.Request(
                "http://ip-api.com/batch",
                data=data.encode(),
                headers={"Content-Type": "application/json", "User-Agent": "discover-cn-proxies/1.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                results = json.loads(r.read().decode())
                for item in results:
                    if item.get("country") == "China" and item.get("status") == "success":
                        cn_ips.add(item.get("query", ""))
        except Exception:
            pass

    # 过滤: 只保留 CN IP
    cn_proxies = [(ip, port) for ip, port in proxies if ip in cn_ips]
    return cn_proxies

def main():
    log("=== CN 代理源发现 开始 ===")
    conn = db_init()

    # Bootstrap 已知 API
    for api in KNOWN_CN_PROXY_APIS:
        upsert_source(conn, api["key"], api["name"], api["url"],
                     api["format"], api["protocol"], api["priority"])
    conn.commit()

    # 1. 测试已知 API
    log("[1/2] 测试已知 API 源...")
    api_found = discover_from_apis(conn)

    # 2. GitHub 搜索发现
    log("[2/2] GitHub 搜索发现...")
    github_found = discover_from_github(conn)

    # 统计
    total = conn.execute("SELECT COUNT(*) FROM cn_proxy_sources WHERE enabled=1").fetchone()[0]
    ok = conn.execute("SELECT COUNT(*) FROM cn_proxy_sources WHERE last_status='ok'").fetchone()[0]

    log(f"=== 完成: API {api_found} 个可用, GitHub 发现 {github_found} 个 ===")
    log(f"总计: {total} 个源, {ok} 个可用")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
