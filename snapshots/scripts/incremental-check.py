#!/usr/bin/env python3
"""
增量节点测试 (方向 B) — v2.3

目标:
  - 每小时跑一次, 仅测 nodes_history 表里**当前活跃**的节点
  - 用 TCP+TLS 握手探测 (不下载流量, 不打扰节点)
  - v2.3 信号 A (探活):
      探活失败 → quality_score -10, consecutive_fails +1
      探活通过 → quality_score +3, consecutive_fails = 0
  - 失败 ≥4 次 → 节点级黑名单 48h (v2.3: 3 → 4)
  - 不影响 subs-check 自跑 (它在跑也不冲突, 我们只读 SQLite)
  - 不影响订阅文件 (订阅源用的是 subs-check 实时输出)

v2.3 关键修订:
  - FAIL_THRESHOLD: 3 → 4
  - 探活失败/通过直接调整 quality_score (旧逻辑只动 fails)
  - **不**触发 lq_node 累加判定 (那是 convert-formats round 切换时的职责)
  - 删除旧的 quality_score 加权重算 SQL (convert-formats v2.3 会重写)

设计:
  - 仅测 last_round_id 在最近 5 轮内的节点 (避免测早就消失的)
  - 跳过黑名单节点
  - 并发 20 (轻量任务)
  - 单节点 timeout 5s
  - 总耗时上限 5min

不做:
  - 不下载文件 (会消耗别人节点流量)
  - 不发 HTTP 请求 (TCP+TLS 已足够判断节点存活)
  - 不更新订阅文件 (那是 convert-formats 的活)
  - 不触发 lq_node 拉黑 (避免重复触发, 仅 round 切换才判)
"""
import os
import sys
import sqlite3
import socket
import ssl
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

HISTORY_DB = "/opt/subs-check/scripts/history.db"
NODES_JSON = "/opt/ss-monitor/sub/free/nodes.json"

# ============= v2.3 配置 =============
CONCURRENT = 20
TIMEOUT_PER_NODE = 5
MAX_RUNTIME_SEC = 300       # 整体 5min 不超
FAIL_THRESHOLD = 4          # v2.3: 3 → 4
BLACKLIST_HOURS = 48
ACTIVE_WITHIN_ROUNDS = 5    # 最近 N 轮内出现过的才测

# v2.3 节点级评分 (信号 A 探活)
NODE_PROBE_FAIL_PENALTY = 10    # 探活失败扣分
NODE_PROBE_PASS_BONUS = 3       # 探活通过加分


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
    """
    TCP 连接测试, 可选 TLS 握手
    返回 (是否通过, 失败原因 / 'ok')
    """
    try:
        # 1. TCP 连接
        sock = socket.create_connection((server, port), timeout=TIMEOUT_PER_NODE)

        if use_tls:
            # 2. TLS 握手 (大多数 vless/vmess/trojan 节点用 TLS)
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with ctx.wrap_socket(sock, server_hostname=server) as ssock:
                    ssock.settimeout(TIMEOUT_PER_NODE)
                    # TLS 握手成功就够
                    pass
            except (ssl.SSLError, OSError, socket.timeout) as e:
                # TLS 握手失败但 TCP 通了 (可能是非 TLS 节点)
                # 不算彻底失败 - 节点可能是 vmess/ws 不带 TLS
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
    """从 nodes_history 读出待测节点"""
    # 拿最大 round_id
    max_rid_row = db.execute("SELECT MAX(last_round_id) FROM nodes_history").fetchone()
    max_rid = max_rid_row[0] if max_rid_row and max_rid_row[0] else 0
    cutoff_rid = max_rid - ACTIVE_WITHIN_ROUNDS

    rows = db.execute("""
        SELECT canonical_sig, protocol, last_round_id
        FROM nodes_history
        WHERE blacklisted_until IS NULL
          AND last_round_id IS NOT NULL
          AND last_round_id >= ?
    """, (cutoff_rid,)).fetchall()

    return rows


def main():
    if not os.path.exists(HISTORY_DB):
        print(f"  ℹ️  {HISTORY_DB} 不存在, 跳过")
        return 0

    db = sqlite3.connect(HISTORY_DB)

    # 检查必要表 (convert-formats 第一次跑后才有)
    has_nodes = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nodes_history'"
    ).fetchone()
    if not has_nodes:
        print(f"  ℹ️  nodes_history 表不存在 (subs-check 还没跑过完整轮?), 跳过")
        return 0

    targets = load_targets(db)
    if not targets:
        print(f"  ℹ️  无活跃节点可测")
        return 0

    started = datetime.now(timezone.utc).isoformat()
    print(f"[{started}] v2.3 增量探活 {len(targets)} 个活跃节点")
    print(f"  并发 {CONCURRENT}, 单节点 timeout {TIMEOUT_PER_NODE}s, 总上限 {MAX_RUNTIME_SEC}s")
    print(f"  规则: 失败 -{NODE_PROBE_FAIL_PENALTY} 分 fails+1, 通过 +{NODE_PROBE_PASS_BONUS} 分 fails=0, 拉黑阈值 {FAIL_THRESHOLD}")

    start_time = time.time()
    n_pass = n_fail = n_skip = n_blacklist = 0
    fail_reasons = {}

    def worker(row):
        sig, protocol, last_rid = row
        server, port = parse_sig(sig)
        if not server or not port:
            return sig, False, "bad_sig"

        # 是否要 TLS 握手
        use_tls = protocol in ('vless', 'trojan', 'vmess', 'hysteria', 'hysteria2')
        ok, reason = probe_node(server, port, use_tls=use_tls)
        return sig, ok, reason

    with ThreadPoolExecutor(max_workers=CONCURRENT) as ex:
        futures = {ex.submit(worker, r): r[0] for r in targets}

        for fut in as_completed(futures):
            # 检查总耗时上限
            if time.time() - start_time > MAX_RUNTIME_SEC:
                # 取消未完成的
                for f in futures:
                    if not f.done():
                        f.cancel()
                # 把还没测的标 skip
                n_skip = len(targets) - n_pass - n_fail
                print(f"  ⚠️  超时 {MAX_RUNTIME_SEC}s, 跳过 {n_skip} 个未测节点")
                break

            try:
                sig, ok, reason = fut.result()
            except Exception as e:
                continue

            now = datetime.now(timezone.utc).isoformat()

            if ok:
                # === v2.3: 探活通过 → quality_score +3, consecutive_fails 重置 0 ===
                n_pass += 1
                db.execute("""
                    UPDATE nodes_history SET
                        incremental_pass = incremental_pass + 1,
                        consecutive_fails = 0,
                        quality_score = MIN(100, COALESCE(quality_score, 100) + ?),
                        last_seen = ?
                    WHERE canonical_sig = ?
                """, (NODE_PROBE_PASS_BONUS, now, sig))
            else:
                # === v2.3: 探活失败 → quality_score -10, consecutive_fails +1 ===
                n_fail += 1
                fail_reasons[reason] = fail_reasons.get(reason, 0) + 1
                db.execute("""
                    UPDATE nodes_history SET
                        incremental_fail = incremental_fail + 1,
                        consecutive_fails = consecutive_fails + 1,
                        quality_score = MAX(0, COALESCE(quality_score, 100) - ?),
                        last_seen = ?
                    WHERE canonical_sig = ?
                """, (NODE_PROBE_FAIL_PENALTY, now, sig))

                # === v2.3 触发点 ①: fails ≥ 4 → 黑名单 48h ===
                cur = db.execute(
                    "SELECT consecutive_fails FROM nodes_history WHERE canonical_sig = ?",
                    (sig,)
                ).fetchone()
                if cur and cur[0] >= FAIL_THRESHOLD:
                    blocked_until = (datetime.now(timezone.utc) + timedelta(hours=BLACKLIST_HOURS)).isoformat()
                    db.execute("""
                        UPDATE nodes_history SET blacklisted_until = ?
                        WHERE canonical_sig = ?
                    """, (blocked_until, sig))
                    n_blacklist += 1

    # === v2.3 关键修订: 不再重算 quality_score ===
    # 旧版 (v1) 在这里用加权公式重算所有节点的 quality_score, 现已删除.
    # v2.3 quality_score 由各信号 (探活/轮次/测速) 直接累加,
    # convert-formats.py 在 round 切换时统一负责 lq_node 累加判定 + ② 拉黑触发.

    db.commit()
    db.close()

    elapsed = time.time() - start_time
    print(f"  完成: 通过 {n_pass}, 失败 {n_fail}, 跳过 {n_skip}, 拉黑 {n_blacklist}, 耗时 {elapsed:.1f}s")
    if fail_reasons:
        print(f"  失败原因: {fail_reasons}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
