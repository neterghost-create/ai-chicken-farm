#!/usr/bin/env python3
"""
cn-proxy-to-yaml.py — 从 CN 代理源拉取存活代理，输出 Mihomo YAML

流程:
  1. 从 cn-proxy-sources.db 读取启用且上次状态 ok 的源
  2. 拉取代理列表 (HTTP/SOCKS5/SOCKS4)
  3. 并发验证存活 (CONNECT httpbin.org:80)
  4. 输出 cn.yaml (Mihomo proxies + proxy-groups + rules)

用法:
  python3 cn-proxy-to-yaml.py                  # 输出到 stdout
  python3 cn-proxy-to-yaml.py -o /path/to/cn.yaml
  python3 cn-proxy-to-yaml.py --max 50         # 最多验证 50 个
  python3 cn-proxy-to-yaml.py --timeout 3      # 单个验证超时 3s
"""

import os
import sys
import json
import socket
import sqlite3
import ssl
import argparse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CN_PROXY_DB = os.path.join(SCRIPT_DIR, "cn-proxy-sources.db")


# ── 拉取代理 ──────────────────────────────────────────────

def fetch_proxies(max_proxies: int = 100) -> list:
    """从 cn-proxy-sources.db 读可用源，拉取代理列表。
    返回 [(proto, host, port), ...]
    """
    proxies = []
    sources = []

    if os.path.exists(CN_PROXY_DB):
        try:
            db = sqlite3.connect(f"file:{CN_PROXY_DB}?mode=ro", uri=True)
            rows = db.execute(
                "SELECT url, protocol, format FROM cn_proxy_sources "
                "WHERE enabled=1 AND last_status='ok' ORDER BY priority"
            ).fetchall()
            db.close()
            sources = [{"url": r[0], "protocol": r[1], "format": r[2]} for r in rows]
        except Exception:
            pass

    if not sources:
        print("⚠️  无可用 CN 代理源", file=sys.stderr)
        return []

    seen = set()
    for src in sources:
        try:
            req = urllib.request.Request(src["url"], headers={"User-Agent": "cn-proxy-to-yaml/1.0"})
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                text = r.read().decode("utf-8", errors="ignore")

            if src["format"] == "lines":
                for line in text.strip().split("\n"):
                    line = line.strip()
                    if ":" in line and not line.startswith("#"):
                        parts = line.rsplit(":", 1)
                        if len(parts) == 2:
                            try:
                                host = parts[0].strip()
                                port = int(parts[1].strip())
                                key = f"{host}:{port}:{src['protocol']}"
                                if key not in seen:
                                    seen.add(key)
                                    proxies.append((src["protocol"], host, port))
                            except ValueError:
                                pass
            elif src["format"] == "json":
                try:
                    data = json.loads(text)
                    for item in data.get("data", []):
                        ip = item.get("ip")
                        port = item.get("port")
                        if ip and port:
                            key = f"{ip}:{port}:{src['protocol']}"
                            if key not in seen:
                                seen.add(key)
                                proxies.append((src["protocol"], ip, int(port)))
                except Exception:
                    pass
        except Exception:
            pass

    print(f"📥 拉取到 {len(proxies)} 个代理 (去重后)", file=sys.stderr)
    return proxies[:max_proxies]


# ── 验证 ──────────────────────────────────────────────────

def verify_socks5(host: str, port: int, timeout: float = 3) -> bool:
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.sendall(b"\x05\x01\x00")
        resp = sock.recv(2)
        if resp[0:1] != b"\x05":
            sock.close()
            return False
        # CONNECT httpbin.org:80
        req = b"\x05\x01\x00\x03\x0bhttpbin.org\x00\x50"
        sock.sendall(req)
        resp = sock.recv(10)
        sock.close()
        return resp[0:1] == b"\x05" and resp[1:2] == b"\x00"
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        return False


def verify_http(host: str, port: int, timeout: float = 3) -> bool:
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.sendall(b"CONNECT httpbin.org:80 HTTP/1.1\r\nHost: httpbin.org:80\r\n\r\n")
        resp = sock.recv(1024).decode()
        sock.close()
        return "200" in resp
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        return False


def verify_proxy(proxy: tuple, timeout: float = 3) -> tuple:
    """验证单个代理，返回 (proto, host, port, alive)"""
    proto, host, port = proxy
    if proto in ("socks5", "socks4"):
        alive = verify_socks5(host, port, timeout)
    elif proto == "http":
        alive = verify_http(host, port, timeout)
    else:
        alive = False
    return (proto, host, port, alive)


# ── YAML 输出 ─────────────────────────────────────────────

def to_mihomo_yaml(alive_proxies: list) -> str:
    """生成 Mihomo YAML 配置"""
    lines = []
    lines.append("# CN 代理节点 — 自动生成")
    lines.append(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"# 存活节点: {len(alive_proxies)}")
    lines.append("")

    # proxies
    lines.append("proxies:")
    names = []
    for i, (proto, host, port) in enumerate(alive_proxies, 1):
        tag = {"http": "🛜", "socks5": "🧦", "socks4": "🧦"}.get(proto, "❓")
        name = f"CN_{proto.upper()}_{i}"
        names.append(name)
        lines.append(f"  - name: \"{name}\"")
        lines.append(f"    type: {proto}")
        lines.append(f"    server: {host}")
        lines.append(f"    port: {port}")
        if proto in ("socks5", "socks4"):
            lines.append(f"    udp: true")
        lines.append("")

    # proxy-groups
    lines.append("proxy-groups:")
    lines.append("  - name: \"CN-Proxies\"")
    lines.append("    type: url-test")
    lines.append("    url: http://connect.rom.miui.com/generate_204")
    lines.append("    interval: 300")
    lines.append("    tolerance: 500")
    lines.append("    proxies:")
    for n in names:
        lines.append(f"      - \"{n}\"")
    lines.append("")

    lines.append("  - name: \"CN-Proxies-Fallback\"")
    lines.append("    type: fallback")
    lines.append("    url: http://connect.rom.miui.com/generate_204")
    lines.append("    interval: 60")
    lines.append("    proxies:")
    for n in names:
        lines.append(f"      - \"{n}\"")
    lines.append("")

    # rules (国内直连 + CN 代理)
    lines.append("rules:")
    lines.append("  # 国内域名走 CN 代理")
    lines.append("  - DOMAIN-SUFFIX,cn,CN-Proxies")
    lines.append("  - DOMAIN-SUFFIX,com.cn,CN-Proxies")
    lines.append("  - DOMAIN-SUFFIX,net.cn,CN-Proxies")
    lines.append("  - DOMAIN-SUFFIX,org.cn,CN-Proxies")
    lines.append("  - DOMAIN-KEYWORD,baidu,CN-Proxies")
    lines.append("  - DOMAIN-KEYWORD,alibaba,CN-Proxies")
    lines.append("  - DOMAIN-KEYWORD,tencent,CN-Proxies")
    lines.append("  - DOMAIN-KEYWORD,bilibili,CN-Proxies")
    lines.append("  - DOMAIN-KEYWORD,qq,CN-Proxies")
    lines.append("  - DOMAIN-KEYWORD,taobao,CN-Proxies")
    lines.append("  - DOMAIN-KEYWORD,jd,CN-Proxies")
    lines.append("  - DOMAIN-KEYWORD,163,CN-Proxies")
    lines.append("  - DOMAIN-KEYWORD,zhihu,CN-Proxies")
    lines.append("  - DOMAIN-KEYWORD,douyin,CN-Proxies")
    lines.append("  # 国内 IP 段走 CN 代理")
    lines.append("  - GEOIP,CN,CN-Proxies")
    lines.append("  # 其余直连")
    lines.append("  - MATCH,DIRECT")
    lines.append("")

    return "\n".join(lines)


# ── 主流程 ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CN 代理源 → Mihomo YAML")
    parser.add_argument("-o", "--output", help="输出文件路径 (默认 stdout)")
    parser.add_argument("--max", type=int, default=100, help="最多拉取 N 个代理 (默认 100)")
    parser.add_argument("--timeout", type=float, default=3, help="单个验证超时秒数 (默认 3)")
    parser.add_argument("--workers", type=int, default=30, help="并发验证数 (默认 30)")
    parser.add_argument("--no-verify", action="store_true", help="跳过验证，全部输出")
    args = parser.parse_args()

    # 1. 拉取
    proxies = fetch_proxies(max_proxies=args.max)
    if not proxies:
        print("❌ 无代理可输出", file=sys.stderr)
        sys.exit(1)

    # 2. 验证
    if args.no_verify:
        alive = proxies
        print(f"⏭️  跳过验证，输出全部 {len(alive)} 个", file=sys.stderr)
    else:
        print(f"🔍 并发验证 {len(proxies)} 个代理 (workers={args.workers}, timeout={args.timeout}s)...", file=sys.stderr)
        alive = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(verify_proxy, p, args.timeout): p for p in proxies}
            done = 0
            for f in as_completed(futures):
                done += 1
                proto, host, port, ok = f.result()
                if ok:
                    alive.append((proto, host, port))
                if done % 20 == 0:
                    print(f"  进度: {done}/{len(proxies)}, 存活: {len(alive)}", file=sys.stderr)
        print(f"✅ 验证完成: {len(alive)}/{len(proxies)} 存活", file=sys.stderr)

    if not alive:
        print("❌ 验证后无存活代理", file=sys.stderr)
        sys.exit(1)

    # 3. 输出
    yaml_content = to_mihomo_yaml(alive)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(yaml_content)
        print(f"📄 已写入 {args.output} ({len(alive)} 个节点)", file=sys.stderr)
    else:
        print(yaml_content)


if __name__ == "__main__":
    main()
