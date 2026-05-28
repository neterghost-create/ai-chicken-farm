#!/usr/bin/env python3
"""
增量节点测试 — v3.1 (CN 代理多视角探活)

设计哲学:
  - 每次跑先拉取免费 CN 代理 (ProxyScrape API)
  - 验证可用的 CN 代理 (快速连通性测试)
  - 每个节点通过所有可用 CN 代理测试
  - 取通过率平均值作为评分依据 (而非单一视角 pass/fail)
  - pass_rate * PASS_BONUS - (1-pass_rate) * FAIL_PENALTY

v3.0 → v3.1 变更:
  - 新增 CN 代理池: ProxyScrape API 拉取 + 验证
  - 多视角测试: 每个节点通过 N 个 CN 代理测试
  - 评分公式: pass_rate 加权 (不再二元 pass/fail)
  - 保留 v3.0 三态机逻辑 (testing/decaying/recovering)

不做:
  - 不下载文件 (会消耗别人节点流量)
  - 不发 HTTP 请求 (TCP+TLS 已足够判断节点存活)
  - 不更新订阅文件 (那是 convert-formats 的活)
  - 不触发拉黑 (v3.0 取消黑名单)
"""
import os
import sys
import sqlite3
import socket
import ssl
import time
import json
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

# 保存原始 socket 函数 (PySocks import 前)
_ORIG_CREATE_CONNECTION = socket.create_connection
_ORIG_SOCKET = socket.socket

import socks

HISTORY_DB = "/opt/subs-check/scripts/history.db"
NODES_JSON = "/opt/ss-monitor/sub/free/nodes.json"

# ============= v3.1 配置 =============
CONCURRENT = 20
TIMEOUT_PER_NODE = 5
MAX_RUNTIME_SEC = 300       # 整体 5min 不超
ACTIVE_WITHIN_ROUNDS = 5    # 最近 N 轮内出现过的才测

# v3.0 节点级评分 (信号 A 探活)
NODE_PROBE_FAIL_PENALTY = 10
NODE_PROBE_PASS_BONUS = 5

# v3.1 CN 代理配置
CN_PROXY_API = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol={proto}&timeout=10000&country=cn"
CN_PROXY_VERIFY_TIMEOUT = 3     # 验证代理超时
CN_PROXY_MAX = 20               # 最多使用 N 个 CN 代理
CN_PROXY_MIN = 1                # 最少需要 N 个可用代理 (低于此值回退直连)


def fetch_cn_proxies() -> list:
    """从 ProxyScrape API 拉取 CN 代理列表, 返回 [(proto, host, port), ...]"""
    proxies = []

    for proto in ["socks5", "http"]:
        try:
            url = CN_PROXY_API.format(proto=proto)
            req = urllib.request.Request(url, headers={"User-Agent": "subs-check/3.1"})
            with urllib.request.urlopen(req, timeout=10) as r:
                lines = r.read().decode("utf-8", errors="ignore").strip().split("\n")
                for line in lines:
                    line = line.strip()
                    if ":" in line and not line.startswith("#"):
                        parts = line.rsplit(":", 1)
                        if len(parts) == 2:
                            try:
                                proxies.append((proto, parts[0].strip(), int(parts[1].strip())))
                            except ValueError:
                                pass
        except Exception:
            pass

    return proxies[:CN_PROXY_MAX]


def _verify_socks5(host: str, port: int) -> bool:
    """验证单个 SOCKS5 代理 (不使用 set_default_proxy, 避免 monkey-patch)"""
    try:
        sock = socks.socksocket()
        sock.setproxy(socks.SOCKS5, host, port)
        sock.settimeout(CN_PROXY_VERIFY_TIMEOUT)
        sock.connect(("httpbin.org", 80))
        sock.sendall(b"GET /ip HTTP/1.1\r\nHost: httpbin.org\r\n\r\n")
        resp = sock.recv(4096).decode()
        sock.close()
        return "200 OK" in resp
    except:
        try: sock.close()
        except: pass
        return False


def _verify_http(host: str, port: int) -> bool:
    """验证单个 HTTP CONNECT 代理"""
    try:
        sock = _ORIG_CREATE_CONNECTION((host, port), timeout=CN_PROXY_VERIFY_TIMEOUT)
        sock.sendall(b"CONNECT httpbin.org:80 HTTP/1.1\r\nHost: httpbin.org:80\r\n\r\n")
        resp = sock.recv(1024).decode()
        sock.close()
        return "200" in resp
    except:
        try: sock.close()
        except: pass
        return False


def verify_cn_proxy(proxy: tuple) -> bool:
    """验证 CN 代理是否可用"""
    proto, host, port = proxy
    if proto == "socks5":
        return _verify_socks5(host, port)
    else:
        return _verify_http(host, port)


def verify_cn_proxies(proxies: list) -> list:
    """并发验证 CN 代理, 返回可用列表"""
    if not proxies:
        return []

    verified = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(verify_cn_proxy, p): p for p in proxies}
        for fut in as_completed(futures):
            proxy = futures[fut]
            try:
                if fut.result():
                    verified.append(proxy)
            except Exception:
                pass

    return verified[:CN_PROXY_MAX]


def _probe_socks5(proxy_host: str, proxy_port: int, server: str, port: int, use_tls: bool) -> tuple[bool, str]:
    """通过 SOCKS5 代理测试节点"""
    try:
        sock = socks.socksocket()
        sock.setproxy(socks.SOCKS5, proxy_host, proxy_port)
        sock.settimeout(TIMEOUT_PER_NODE)
        sock.connect((server, port))
        if use_tls:
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with ctx.wrap_socket(sock, server_hostname=server) as ssock:
                    ssock.settimeout(TIMEOUT_PER_NODE)
            except (ssl.SSLError, OSError, socket.timeout):
                sock.close()
                return True, "tcp-only"
        else:
            sock.close()
        return True, "ok"
    except socket.gaierror:
        return False, "dns_fail"
    except (socket.timeout, TimeoutError):
        return False, "timeout"
    except (ConnectionRefusedError, OSError) as e:
        return False, f"refuse_{type(e).__name__}"
    except Exception as e:
        return False, f"unknown_{type(e).__name__}"
    finally:
        try: sock.close()
        except: pass


def _probe_http(proxy_host: str, proxy_port: int, server: str, port: int, use_tls: bool) -> tuple[bool, str]:
    """通过 HTTP CONNECT 代理测试节点"""
    try:
        sock = _ORIG_CREATE_CONNECTION((proxy_host, proxy_port), timeout=TIMEOUT_PER_NODE)
        sock.sendall(f"CONNECT {server}:{port} HTTP/1.1\r\nHost: {server}:{port}\r\n\r\n".encode())
        resp = sock.recv(1024).decode()
        if "200" not in resp:
            sock.close()
            return False, "connect_fail"
        if use_tls:
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with ctx.wrap_socket(sock, server_hostname=server) as ssock:
                    ssock.settimeout(TIMEOUT_PER_NODE)
            except (ssl.SSLError, OSError, socket.timeout):
                sock.close()
                return True, "tcp-only"
        else:
            sock.close()
        return True, "ok"
    except socket.gaierror:
        return False, "dns_fail"
    except (socket.timeout, TimeoutError):
        return False, "timeout"
    except (ConnectionRefusedError, OSError) as e:
        return False, f"refuse_{type(e).__name__}"
    except Exception as e:
        return False, f"unknown_{type(e).__name__}"
    finally:
        try: sock.close()
        except: pass


def probe_via_proxy(proxy: tuple, server: str, port: int, use_tls: bool = True) -> tuple[bool, str]:
    """通过 CN 代理测试节点连通性"""
    proto, proxy_host, proxy_port = proxy
    if proto == "socks5":
        return _probe_socks5(proxy_host, proxy_port, server, port, use_tls)
    else:
        return _probe_http(proxy_host, proxy_port, server, port, use_tls)


def probe_direct(server: str, port: int, use_tls: bool = True) -> tuple[bool, str]:
    """直连探活 (回退方案)"""
    try:
        sock = _ORIG_CREATE_CONNECTION((server, port), timeout=TIMEOUT_PER_NODE)
        if use_tls:
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with ctx.wrap_socket(sock, server_hostname=server) as ssock:
                    ssock.settimeout(TIMEOUT_PER_NODE)
            except (ssl.SSLError, OSError, socket.timeout):
                sock.close()
                return True, "tcp-only"
        else:
            sock.close()
        return True, "ok"
    except socket.gaierror:
        return False, "dns_fail"
    except (socket.timeout, TimeoutError):
        return False, "timeout"
    except (ConnectionRefusedError, OSError) as e:
        return False, f"refuse_{type(e).__name__}"
    except Exception as e:
        return False, f"unknown_{type(e).__name__}"


def parse_sig(sig: str):
    """server:port:type → (server, port)"""
    parts = sig.rsplit(':', 2)
    if len(parts) != 3:
        return None, None
    server = parts[0]
    try:
        port = int(parts[1])
    except ValueError:
        return None, None
    return server, port


def load_targets(db) -> list:
    """v3.0: 仅测 state='testing' 且最近活跃的节点"""
    max_rid_row = db.execute("SELECT MAX(last_round_id) FROM nodes_history").fetchone()
    max_rid = max_rid_row[0] if max_rid_row and max_rid_row[0] else 0
    cutoff_rid = max_rid - ACTIVE_WITHIN_ROUNDS

    rows = db.execute("""
        SELECT canonical_sig, protocol, last_round_id
        FROM nodes_history
        WHERE state = 'testing'
          AND last_round_id IS NOT NULL
          AND last_round_id >= ?
    """, (cutoff_rid,)).fetchall()
    return rows


def main():
    if not os.path.exists(HISTORY_DB):
        print(f"  ℹ️  {HISTORY_DB} 不存在, 跳过")
        return 0

    db = sqlite3.connect(HISTORY_DB)

    has_nodes = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nodes_history'"
    ).fetchone()
    if not has_nodes:
        print(f"  ℹ️  nodes_history 表不存在, 跳过")
        return 0

    # v3.0: 确保 state 列存在 (兼容老库)
    try:
        db.execute("ALTER TABLE nodes_history ADD COLUMN state TEXT DEFAULT 'testing'")
        db.commit()
    except sqlite3.OperationalError:
        pass

    targets = load_targets(db)
    if not targets:
        print(f"  ℹ️  无 testing 状态活跃节点可测")
        return 0

    # ========== v3.1: 拉取 + 验证 CN 代理 ==========
    print(f"  🔍 拉取 CN 代理...")
    raw_proxies = fetch_cn_proxies()
    print(f"  📡 拉到 {len(raw_proxies)} 个 CN 代理, 开始验证...")

    cn_proxies = verify_cn_proxies(raw_proxies)
    print(f"  ✅ 验证通过 {len(cn_proxies)} 个 CN 代理")

    use_proxy = len(cn_proxies) >= CN_PROXY_MIN
    if not use_proxy:
        print(f"  ⚠️  可用 CN 代理不足 {CN_PROXY_MIN} 个, 回退直连模式")

    started = datetime.now(timezone.utc).isoformat()
    mode = f"CN代理×{len(cn_proxies)}" if use_proxy else "直连"
    print(f"[{started}] v3.1 增量探活 {len(targets)} 个 testing 状态节点 ({mode})")
    print(f"  并发 {CONCURRENT}, 单节点 timeout {TIMEOUT_PER_NODE}s, 总上限 {MAX_RUNTIME_SEC}s")
    print(f"  评分: pass_rate × {NODE_PROBE_PASS_BONUS} - (1-pass_rate) × {NODE_PROBE_FAIL_PENALTY}")

    start_time = time.time()
    n_pass = n_fail = n_skip = n_decaying = n_recovering = 0
    fail_reasons = {}

    def worker(row):
        """测试单个节点: 通过所有 CN 代理测试, 返回 (sig, pass_rate, details)"""
        sig, protocol, last_rid = row
        server, port = parse_sig(sig)
        if not server or not port:
            return sig, 0.0, "bad_sig"
        use_tls = protocol in ('vless', 'trojan', 'vmess', 'hysteria', 'hysteria2')

        if use_proxy:
            # 通过所有 CN 代理测试
            results = []
            for proxy in cn_proxies:
                ok, reason = probe_via_proxy(proxy, server, port, use_tls=use_tls)
                results.append((ok, reason))
            pass_count = sum(1 for ok, _ in results if ok)
            pass_rate = pass_count / len(results) if results else 0.0
            fail_reasons_list = [r for ok, r in results if not ok]
            details = f"{pass_count}/{len(results)}"
            if fail_reasons_list:
                details += f" ({','.join(set(fail_reasons_list))})"
            return sig, pass_rate, details
        else:
            # 直连模式
            ok, reason = probe_direct(server, port, use_tls=use_tls)
            pass_rate = 1.0 if ok else 0.0
            return sig, pass_rate, reason

    with ThreadPoolExecutor(max_workers=CONCURRENT) as ex:
        futures = {ex.submit(worker, r): r[0] for r in targets}

        for fut in as_completed(futures):
            if time.time() - start_time > MAX_RUNTIME_SEC:
                for f in futures:
                    if not f.done():
                        f.cancel()
                n_skip = len(targets) - n_pass - n_fail
                print(f"  ⚠️  超时 {MAX_RUNTIME_SEC}s, 跳过 {n_skip} 个未测节点")
                break

            try:
                sig, pass_rate, details = fut.result()
            except Exception:
                continue

            now = datetime.now(timezone.utc).isoformat()

            # v3.1 评分: pass_rate 加权
            score_delta = pass_rate * NODE_PROBE_PASS_BONUS - (1 - pass_rate) * NODE_PROBE_FAIL_PENALTY

            if pass_rate > 0:
                n_pass += 1
            else:
                n_fail += 1
                if details not in fail_reasons:
                    fail_reasons[details] = 0
                fail_reasons[details] += 1

            db.execute("""
                UPDATE nodes_history SET
                    incremental_pass = incremental_pass + ?,
                    incremental_fail = incremental_fail + ?,
                    consecutive_fails = CASE WHEN ? > 0 THEN 0 ELSE consecutive_fails + 1 END,
                    quality_score = MAX(0.0, MIN(100.0, COALESCE(quality_score, 50.0) + ?)),
                    last_seen = ?
                WHERE canonical_sig = ?
            """, (
                1 if pass_rate > 0 else 0,
                0 if pass_rate > 0 else 1,
                pass_rate,
                score_delta,
                now,
                sig
            ))

            # 检查状态转换
            row = db.execute(
                "SELECT quality_score, state FROM nodes_history WHERE canonical_sig = ?", (sig,)
            ).fetchone()
            if row:
                score, state = row
                if score >= 100 and state != 'decaying':
                    db.execute(
                        "UPDATE nodes_history SET state='decaying', quality_score=100 WHERE canonical_sig = ?",
                        (sig,)
                    )
                    n_decaying += 1
                elif score <= 0 and state != 'recovering':
                    db.execute(
                        "UPDATE nodes_history SET state='recovering', quality_score=0 WHERE canonical_sig = ?",
                        (sig,)
                    )
                    n_recovering += 1

    db.commit()
    db.close()

    elapsed = time.time() - start_time
    print(f"  完成: 通过 {n_pass}, 失败 {n_fail}, 跳过 {n_skip}, "
          f"→ decaying {n_decaying}, → recovering {n_recovering}, 耗时 {elapsed:.1f}s")
    if fail_reasons:
        print(f"  失败原因: {fail_reasons}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
