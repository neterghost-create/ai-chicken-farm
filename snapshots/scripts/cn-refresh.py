#!/usr/bin/env python3
"""
cn-refresh.py — CN 代理拉活 + 生成 cn.yaml + Telegram 推送

流程:
  1. 从 cn-proxy-sources.db 拉取 CN 代理
  2. 并发验证存活
  3. 生成 Mihomo cn.yaml (含 proxies + proxy-groups + rules)
  4. 拼 token 订阅 URL
  5. Telegram 推送摘要 + 订阅链接

cron 示例 (每 4h):
  0 */4 * * * /opt/subs-check/scripts/cn-refresh.py >> /var/log/cn-refresh.log 2>&1
"""

import os
import sys
import json
import socket
import sqlite3
import ssl
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CN_PROXY_DB = os.path.join(SCRIPT_DIR, "cn-proxy-sources.db")
FREE_POOL_CONF = os.path.join(SCRIPT_DIR, "free-pool.conf")
TOKEN_DIR = ""  # 运行时从 free-pool.conf 读取
OUTPUT_YAML = ""  # 运行时拼接
TELEGRAM_CONF = "/etc/telegram-bot.conf"

MAX_PROXIES = 80
VERIFY_TIMEOUT = 3
WORKERS = 30


# ── 配置读取 ──────────────────────────────────────────────

def load_conf(path: str) -> dict:
    cfg = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


# ── 拉取代理 ──────────────────────────────────────────────

def fetch_proxies() -> list:
    """从 cn-proxy-sources.db 读可用源，拉取代理列表。"""
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
            req = urllib.request.Request(src["url"], headers={"User-Agent": "cn-refresh/1.0"})
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
    return proxies[:MAX_PROXIES]


# ── 验证 ──────────────────────────────────────────────────

def verify_socks5(host: str, port: int, timeout: float = 3) -> bool:
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.sendall(b"\x05\x01\x00")
        resp = sock.recv(2)
        if resp[0:1] != b"\x05":
            sock.close()
            return False
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
    proto, host, port = proxy
    if proto in ("socks5", "socks4"):
        alive = verify_socks5(host, port, timeout)
    elif proto == "http":
        alive = verify_http(host, port, timeout)
    else:
        alive = False
    return (proto, host, port, alive)


# ── YAML 生成 ─────────────────────────────────────────────

def to_mihomo_yaml(alive_proxies: list) -> str:
    lines = []
    lines.append("# CN 代理节点 — 自动生成")
    lines.append(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"# 存活节点: {len(alive_proxies)}")
    lines.append("")
    lines.append("proxies:")
    names = []
    for i, (proto, host, port) in enumerate(alive_proxies, 1):
        name = f"CN_{proto.upper()}_{i}"
        names.append(name)
        lines.append(f"  - name: \"{name}\"")
        lines.append(f"    type: {proto}")
        lines.append(f"    server: {host}")
        lines.append(f"    port: {port}")
        if proto in ("socks5", "socks4"):
            lines.append(f"    udp: true")
        lines.append("")

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

    lines.append("  - name: \"CN-Fallback\"")
    lines.append("    type: fallback")
    lines.append("    url: http://connect.rom.miui.com/generate_204")
    lines.append("    interval: 60")
    lines.append("    proxies:")
    for n in names:
        lines.append(f"      - \"{n}\"")
    lines.append("")

    lines.append("rules:")
    lines.append("  - DOMAIN-SUFFIX,cn,CN-Proxies")
    lines.append("  - DOMAIN-SUFFIX,com.cn,CN-Proxies")
    lines.append("  - DOMAIN-SUFFIX,net.cn,CN-Proxies")
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
    lines.append("  - GEOIP,CN,CN-Proxies")
    lines.append("  - MATCH,DIRECT")
    lines.append("")
    return "\n".join(lines)


# ── Telegram ──────────────────────────────────────────────

def send_telegram(token: str, chat_id: str, text: str) -> bool:
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            'chat_id': chat_id,
            'parse_mode': 'Markdown',
            'text': text,
        }).encode()
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        return result.get('ok', False)
    except Exception as e:
        print(f"⚠️  Telegram 推送失败: {e}", file=sys.stderr)
        return False


# ── 主流程 ────────────────────────────────────────────────

def main():
    now = datetime.now()

    # 0. 读配置, 拼路径
    fp_cfg = load_conf(FREE_POOL_CONF)
    fp_token = fp_cfg.get('TOKEN', '')
    domain = fp_cfg.get('DOMAIN', 'example-legacy.duckdns.org')
    if not fp_token:
        print("❌ free-pool.conf TOKEN 未配置", file=sys.stderr)
        sys.exit(1)
    token_dir = f"/opt/ss-monitor/sub/free/{fp_token}"
    output_yaml = os.path.join(token_dir, "cn.yaml")

    # 1. 拉取
    proxies = fetch_proxies()
    if not proxies:
        print("❌ 无代理可输出", file=sys.stderr)
        sys.exit(1)

    # 2. 验证
    print(f"🔍 并发验证 {len(proxies)} 个 (workers={WORKERS}, timeout={VERIFY_TIMEOUT}s)...", file=sys.stderr)
    alive = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(verify_proxy, p, VERIFY_TIMEOUT): p for p in proxies}
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

    # 3. 生成 cn.yaml
    yaml_content = to_mihomo_yaml(alive)
    os.makedirs(token_dir, exist_ok=True)
    with open(output_yaml, "w") as f:
        f.write(yaml_content)
    print(f"📄 已写入 {output_yaml} ({len(alive)} 个节点)", file=sys.stderr)

    # 4. 拼 token URL
    sub_url = f"https://{domain}/sub/free/{fp_token}/cn.yaml"

    # 5. 统计协议分布
    proto_dist = {}
    for p, _, _ in alive:
        proto_dist[p] = proto_dist.get(p, 0) + 1
    proto_str = " · ".join(f"{k}:{v}" for k, v in sorted(proto_dist.items(), key=lambda x: -x[1]))

    # 6. Telegram 推送
    tg_cfg = load_conf(TELEGRAM_CONF)
    tg_token = tg_cfg.get('TELEGRAM_BOT_TOKEN', '')
    tg_chat = tg_cfg.get('TELEGRAM_CHAT_ID', '')

    text = f"""*🛜 CN 代理刷新*

⏰ {now.strftime('%Y-%m-%d %H:%M:%S')}
✅ 存活节点: *{len(alive)}*/{len(proxies)}
📊 协议分布: {proto_str}

📡 订阅 URL (Clash/Mihomo Provider):
`{sub_url}`"""

    if tg_token and tg_chat:
        ok = send_telegram(tg_token, tg_chat, text)
        print(f"{'✓' if ok else '✗'} Telegram 推送{'成功' if ok else '失败'}", file=sys.stderr)
    else:
        print("⚠️  Telegram 未配置", file=sys.stderr)

    # stdout 也输出摘要
    print(text.replace('*', '').replace('`', ''))


if __name__ == "__main__":
    main()
