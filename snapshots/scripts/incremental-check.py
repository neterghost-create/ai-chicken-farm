#!/usr/bin/env python3
"""
增量节点测试 — v3.0 (Hysteresis 三态机)

设计哲学:
  - 节点有 testing / decaying / recovering 三态
  - 仅 testing 状态节点参与探活 (节省资源)
  - 探活通过 +5, 失败 -10 (信号 A)
  - 触顶 100 → decaying, 触底 0 → recovering
  - decaying / recovering 状态由 convert-formats.py 在 round 切换时被动衰减/恢复
  - 没有节点级黑名单 (0 分进 recovering 自动从底回升, 不是封禁)

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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

HISTORY_DB = "/opt/subs-check/scripts/history.db"
NODES_JSON = "/opt/ss-monitor/sub/free/nodes.json"

# ============= v3.0 配置 =============
CONCURRENT = 20
TIMEOUT_PER_NODE = 5
MAX_RUNTIME_SEC = 300       # 整体 5min 不超
ACTIVE_WITHIN_ROUNDS = 5    # 最近 N 轮内出现过的才测

# v3.0 节点级评分 (信号 A 探活)
NODE_PROBE_FAIL_PENALTY = 10
NODE_PROBE_PASS_BONUS = 5


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


def probe_node(server: str, port: int, use_tls: bool = True) -> tuple[bool, str]:
    """TCP 连接测试, 可选 TLS 握手. 返回 (是否通过, 失败原因 / 'ok')"""
    try:
        sock = socket.create_connection((server, port), timeout=TIMEOUT_PER_NODE)
        if use_tls:
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with ctx.wrap_socket(sock, server_hostname=server) as ssock:
                    ssock.settimeout(TIMEOUT_PER_NODE)
                    pass
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


def load_targets(db) -> list:
    """v3.0: 仅测 state='testing' 且最近活跃的节点

    decaying / recovering 由 convert-formats.py round 切换时被动调整,
    不消耗探活资源.
    """
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

    started = datetime.now(timezone.utc).isoformat()
    print(f"[{started}] v3.0 增量探活 {len(targets)} 个 testing 状态节点")
    print(f"  并发 {CONCURRENT}, 单节点 timeout {TIMEOUT_PER_NODE}s, 总上限 {MAX_RUNTIME_SEC}s")
    print(f"  规则: 通过 +{NODE_PROBE_PASS_BONUS}, 失败 -{NODE_PROBE_FAIL_PENALTY}, "
          f"触 100 → decaying, 触 0 → recovering")

    start_time = time.time()
    n_pass = n_fail = n_skip = n_decaying = n_recovering = 0
    fail_reasons = {}

    def worker(row):
        sig, protocol, last_rid = row
        server, port = parse_sig(sig)
        if not server or not port:
            return sig, False, "bad_sig"
        use_tls = protocol in ('vless', 'trojan', 'vmess', 'hysteria', 'hysteria2')
        ok, reason = probe_node(server, port, use_tls=use_tls)
        return sig, ok, reason

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
                sig, ok, reason = fut.result()
            except Exception:
                continue

            now = datetime.now(timezone.utc).isoformat()

            if ok:
                # 探活通过 +5, 触 100 → decaying
                n_pass += 1
                db.execute("""
                    UPDATE nodes_history SET
                        incremental_pass = incremental_pass + 1,
                        consecutive_fails = 0,
                        quality_score = MIN(100.0, COALESCE(quality_score, 50.0) + ?),
                        last_seen = ?
                    WHERE canonical_sig = ?
                """, (NODE_PROBE_PASS_BONUS, now, sig))
                row = db.execute(
                    "SELECT quality_score FROM nodes_history WHERE canonical_sig = ?", (sig,)
                ).fetchone()
                if row and row[0] >= 100:
                    db.execute(
                        "UPDATE nodes_history SET state='decaying', quality_score=100 "
                        "WHERE canonical_sig = ?", (sig,)
                    )
                    n_decaying += 1
            else:
                # 探活失败 -10, 触 0 → recovering
                n_fail += 1
                fail_reasons[reason] = fail_reasons.get(reason, 0) + 1
                db.execute("""
                    UPDATE nodes_history SET
                        incremental_fail = incremental_fail + 1,
                        consecutive_fails = consecutive_fails + 1,
                        quality_score = MAX(0.0, COALESCE(quality_score, 50.0) - ?),
                        last_seen = ?
                    WHERE canonical_sig = ?
                """, (NODE_PROBE_FAIL_PENALTY, now, sig))
                row = db.execute(
                    "SELECT quality_score FROM nodes_history WHERE canonical_sig = ?", (sig,)
                ).fetchone()
                if row and row[0] <= 0:
                    db.execute(
                        "UPDATE nodes_history SET state='recovering', quality_score=0 "
                        "WHERE canonical_sig = ?", (sig,)
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
