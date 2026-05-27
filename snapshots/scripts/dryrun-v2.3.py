#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dryrun-v2.3.py — v2.3 评分规则纯只读模拟器

用途:
    在不改任何生产数据的前提下, 用现有 DB 数据回放 + 预测,
    评估 v2.3 规则上线后会发生什么.

输入:
    /opt/subs-check/scripts/source-scores.db  (只读)
    /opt/subs-check/scripts/history.db        (只读)

输出:
    /tmp/v2.3-dryrun-report.json   (机器可读完整报告)
    /tmp/v2.3-dryrun-report.txt    (人类可读摘要)

模式:
    A. 历史回放 (Replay)
       - 用 source_quality_history 已有 round 数据回放
       - 应用 v2.3 规则, 看部署后第一时刻状态
    B. 稳态预测 (Forecast)
       - 假设当前模式延续 (节点速度/出现率/均分分布不变)
       - 预测未来 30 轮谁会被拉黑

依赖: 仅 sqlite3 + json + dataclasses (Python 标准库)
作者: hermes (v2.3 规则评估)
日期: 2026-05-26
"""

import json
import sqlite3
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# === v2.3 规则常量 (与 SCORING_RULES_v2.md 对齐) ===

# 源级
SOURCE_DEFAULT_SCORE = 100
SOURCE_FETCH_FAIL_PENALTY = 15
SOURCE_PARSE_EMPTY_PENALTY = 10
FAIL_THRESHOLD_CANDIDATE = 3
FAIL_THRESHOLD_WHITELIST = 60
PASS_THRESHOLD_PROMOTE = 30
SOURCE_BLACKLIST_DAYS = 30

SOURCE_QUALITY_PENALTY_LOW = 2     # 50-69
SOURCE_QUALITY_PENALTY_MID = 5     # 30-49
SOURCE_QUALITY_PENALTY_HIGH = 10   # <30
SOURCE_KILL_AFTER_LOW_ROUNDS = 5   # ③ lq streak
SOURCE_KILL_AFTER_LOW_TOTAL = 15   # ④ low_score_total
SOURCE_LOW_SCORE_THRESHOLD = 30
MIN_NODES_FOR_QUALITY_EVAL = 5

# 节点级
NODE_DEFAULT_SCORE = 100
NODE_FAIL_THRESHOLD = 4
NODE_LOW_QUALITY_THRESHOLD = 30
NODE_KILL_AFTER_LOW_ROUNDS = 5

NODE_PROBE_FAIL_PENALTY = 10
NODE_PROBE_PASS_BONUS = 3
NODE_ABSENT_PENALTY = 3
NODE_PRESENT_BONUS = 2
NODE_CONSECUTIVE_BONUS = 3   # consecutive_appearances >= 5

NODE_SPEED_HIGH_BONUS = 3
NODE_SPEED_LOW_PENALTY = 3
NODE_SPEED_VLOW_PENALTY = 12   # 100-511 (v2.2 加大)
NODE_SPEED_DEAD_PENALTY = 15
NODE_SPEED_TIMEOUT_PENALTY = 10

# DB 路径
SCORES_DB = "/opt/subs-check/scripts/source-scores.db"
HISTORY_DB = "/opt/subs-check/scripts/history.db"


# === 数据类 ===
@dataclass
class SourceState:
    url: str
    score: float = SOURCE_DEFAULT_SCORE
    status: str = 'candidate'
    consecutive_fails: int = 0
    consecutive_passes: int = 0
    consecutive_low_quality: int = 0
    low_score_total: int = 0
    blacklist_reason: Optional[str] = None      # ① ② ③ ④
    blacklist_at_round: Optional[int] = None
    history: list = field(default_factory=list)  # [(round, event, score, lq, lst), ...]


@dataclass
class NodeState:
    sig: str
    quality_score: float = NODE_DEFAULT_SCORE
    consecutive_fails: int = 0
    consecutive_low_quality_node: int = 0
    blacklist_reason: Optional[str] = None      # ① ② (节点只有 2 个)
    blacklist_at_round: Optional[int] = None


# === 源级 v2.3 规则应用 ===
def apply_source_rules(s: SourceState, round_id: int, avg_quality: Optional[float],
                       node_count: int) -> Optional[str]:
    """
    应用源级 v2.3 规则到一轮的均分输入.

    返回: None (未拉黑) 或 触发点编号 ('1','2','3','4')
    """
    if s.status == 'blacklisted':
        return None

    # 信号 B: 节点质量减分 (假设网络全可达, 因为 dryrun 没有网络层数据)
    # 真实 sync-lza6 会从 subs-check 日志解析, 这里跳过 ① ②
    if avg_quality is not None and node_count >= MIN_NODES_FOR_QUALITY_EVAL:
        if avg_quality >= 70:
            penalty = 0
            s.consecutive_low_quality = 0
        elif avg_quality >= 50:
            penalty = SOURCE_QUALITY_PENALTY_LOW
            s.consecutive_low_quality += 1
        elif avg_quality >= 30:
            penalty = SOURCE_QUALITY_PENALTY_MID
            s.consecutive_low_quality += 1
        else:
            penalty = SOURCE_QUALITY_PENALTY_HIGH
            s.consecutive_low_quality += 1
        s.score = max(0, s.score - penalty)
    elif node_count == 0 or node_count < MIN_NODES_FOR_QUALITY_EVAL:
        # 不评估, lq 重置
        s.consecutive_low_quality = 0

    # ④ low_score_total 累计
    if s.score < SOURCE_LOW_SCORE_THRESHOLD:
        s.low_score_total += 1

    # 记录历史
    s.history.append({
        'round': round_id,
        'avg_quality': avg_quality,
        'node_count': node_count,
        'score_after': s.score,
        'lq': s.consecutive_low_quality,
        'lst': s.low_score_total,
    })

    # 拉黑判定 (优先级 ① > ② > ③ > ④)
    if s.consecutive_fails >= FAIL_THRESHOLD_CANDIDATE and s.status == 'candidate':
        s.status = 'blacklisted'
        s.blacklist_reason = '1'
        s.blacklist_at_round = round_id
        return '1'
    if s.consecutive_fails >= FAIL_THRESHOLD_WHITELIST and s.status == 'whitelisted':
        s.status = 'blacklisted'
        s.blacklist_reason = '2'
        s.blacklist_at_round = round_id
        return '2'
    if s.consecutive_low_quality >= SOURCE_KILL_AFTER_LOW_ROUNDS:
        s.status = 'blacklisted'
        s.blacklist_reason = '3'
        s.blacklist_at_round = round_id
        return '3'
    if s.low_score_total >= SOURCE_KILL_AFTER_LOW_TOTAL:
        s.status = 'blacklisted'
        s.blacklist_reason = '4'
        s.blacklist_at_round = round_id
        return '4'
    return None


# === 节点级 v2.3 规则应用 ===
def calc_node_score_v23(present: bool, cons_apps: int, speed_kbps: int,
                        probe_pass: bool = False, probe_fail: bool = False,
                        speed_timeout: bool = False) -> tuple[float, bool]:
    """
    返回单轮节点 quality_score 增减 + 是否累加 fails.
    """
    delta = 0
    fail_inc = False

    # 信号 A: 探活
    if probe_fail:
        delta -= NODE_PROBE_FAIL_PENALTY
        fail_inc = True
    elif probe_pass:
        delta += NODE_PROBE_PASS_BONUS

    # 信号 B: 轮次
    if not present:
        delta -= NODE_ABSENT_PENALTY
    else:
        delta += NODE_PRESENT_BONUS
        if cons_apps >= 5:
            delta += NODE_CONSECUTIVE_BONUS

    # 信号 C: 测速 (仅当 present 且测了速)
    if present and speed_kbps is not None:
        if speed_timeout:
            delta -= NODE_SPEED_TIMEOUT_PENALTY
            fail_inc = True
        elif speed_kbps >= 2048:
            delta += NODE_SPEED_HIGH_BONUS
        elif speed_kbps >= 1024:
            pass  # +0
        elif speed_kbps >= 512:
            delta -= NODE_SPEED_LOW_PENALTY
        elif speed_kbps >= 100:
            delta -= NODE_SPEED_VLOW_PENALTY
        else:
            delta -= NODE_SPEED_DEAD_PENALTY

    return delta, fail_inc


# ============== 模式 A: 历史回放 ==============
def replay_sources():
    """读 source_quality_history 历史轮数据,应用 v2.3 规则模拟到当前."""
    db = sqlite3.connect(f'file:{SCORES_DB}?mode=ro', uri=True)

    # 拉所有源 + 所有 history rounds
    sources = {}
    for url, in db.execute("SELECT url FROM sources"):
        sources[url] = SourceState(url=url)

    rounds = db.execute("""
        SELECT DISTINCT round_id FROM source_quality_history ORDER BY round_id ASC
    """).fetchall()
    rounds = [r[0] for r in rounds]

    if not rounds:
        return sources, [], 0

    # 逐轮回放
    blacklist_log = []
    for rid in rounds:
        round_data = db.execute("""
            SELECT source_url, avg_quality_score, node_count
            FROM source_quality_history WHERE round_id = ?
        """, (rid,)).fetchall()

        # 转 dict 便于 lookup
        evaluated = {url: (avg, nc) for url, avg, nc in round_data}

        for url, s in sources.items():
            if s.status == 'blacklisted':
                continue
            avg, nc = evaluated.get(url, (None, 0))
            triggered = apply_source_rules(s, rid, avg, nc)
            if triggered:
                blacklist_log.append({
                    'url': url, 'round': rid, 'reason': triggered,
                    'score_at_trigger': round(s.score, 1),
                    'lq': s.consecutive_low_quality,
                    'lst': s.low_score_total,
                })

    db.close()
    return sources, blacklist_log, max(rounds)


def replay_nodes():
    """节点级回放: 用现有 nodes_history 字段直接计算 v2.3 默认状态."""
    db = sqlite3.connect(f'file:{HISTORY_DB}?mode=ro', uri=True)
    cur_round_row = db.execute("SELECT MAX(last_round_id) FROM nodes_history").fetchone()
    cur_round = cur_round_row[0] if cur_round_row else 0

    nodes = []
    for row in db.execute("""
        SELECT canonical_sig, quality_score, total_appearances, consecutive_appearances,
               consecutive_fails, incremental_pass, incremental_fail,
               blacklisted_until, last_round_id, avg_speed_kbps
        FROM nodes_history
    """):
        sig, qs, ta, ca, cf, ip, ifail, bl, lrid, speed = row
        speed = speed or 0
        nodes.append({
            'sig': sig,
            'old_quality_score': round(qs or 0, 1),
            'total_appearances': ta or 0,
            'consecutive_appearances': ca or 0,
            'consecutive_fails': cf or 0,
            'inc_pass': ip or 0,
            'inc_fail': ifail or 0,
            'old_blacklisted': bl is not None,
            'last_round_id': lrid or 0,
            'avg_speed_kbps': round(speed, 0),
            'rounds_absent': cur_round - (lrid or 0) if cur_round else 0,
        })
    db.close()
    return nodes, cur_round


# ============== 模式 B: 稳态预测 (节点) ==============
def forecast_nodes(nodes, cur_round, future_rounds=30):
    """
    预测未来 N 轮内有多少节点会因 v2.3 规则被拉黑.
    假设: 每个节点保持当前 avg_speed_kbps 和 last_round_id 与 cur_round 的关系.
    """
    forecast = []
    for n in nodes:
        if n['old_blacklisted']:
            forecast.append({
                'sig': n['sig'],
                'verdict': 'already_blacklisted',
                'reason': 'pre-existing',
                'rounds_to_blacklist': 0,
            })
            continue

        # 1. 节点已经 30 轮没出现 → 即将 DELETE (优先于拉黑)
        if n['rounds_absent'] >= 30:
            forecast.append({
                'sig': n['sig'],
                'verdict': 'will_delete_soon',
                'reason': 'rounds_absent>=30',
                'rounds_to_blacklist': None,
                'avg_speed': n['avg_speed_kbps'],
            })
            continue

        # 2. 模拟未来 N 轮: 假设节点保持当前出现/不出现状态
        present = n['rounds_absent'] == 0  # 本轮出现
        cons_apps = n['consecutive_appearances']
        score = NODE_DEFAULT_SCORE  # v2.3 默认从 100 开始
        fails = 0
        lq_node = 0
        speed = n['avg_speed_kbps']

        triggered_round = None
        triggered_reason = None
        for r in range(1, future_rounds + 1):
            # 模拟一轮 (假设 present 状态不变, 速度不变)
            if present:
                cons_apps += 1
            delta, fail_inc = calc_node_score_v23(
                present=present, cons_apps=cons_apps,
                speed_kbps=int(speed) if speed > 0 else None
            )
            score = max(0, min(100, score + delta))
            if fail_inc:
                fails += 1
            else:
                # 探活通过会重置 fails, 但 dryrun 不模拟 incremental-check
                pass

            # lq_node 判定 (仅本轮出现)
            if present:
                if score < NODE_LOW_QUALITY_THRESHOLD:
                    lq_node += 1
                else:
                    lq_node = 0

            # 拉黑触发
            if fails >= NODE_FAIL_THRESHOLD:
                triggered_round = r
                triggered_reason = '1_fails'
                break
            if lq_node >= NODE_KILL_AFTER_LOW_ROUNDS:
                triggered_round = r
                triggered_reason = '2_lq_node'
                break

        forecast.append({
            'sig': n['sig'],
            'verdict': 'will_blacklist' if triggered_round else 'safe',
            'reason': triggered_reason,
            'rounds_to_blacklist': triggered_round,
            'avg_speed': n['avg_speed_kbps'],
            'rounds_absent': n['rounds_absent'],
        })
    return forecast


# === 主流程 ===
def main():
    print("=" * 70)
    print("v2.3 dry-run 模拟器 (纯只读, 不改 DB)")
    print("=" * 70)
    print(f"开始: {datetime.now().isoformat(timespec='seconds')}")
    print()

    # ===== 模式 A: 源级历史回放 =====
    print("【模式 A】源级历史回放 (基于 source_quality_history)...")
    sources, src_blacklist_log, last_round = replay_sources()
    print(f"  当前 round: {last_round}")
    print(f"  源总数: {len(sources)}")
    print(f"  v2.3 规则下立即拉黑: {len(src_blacklist_log)} 个")
    by_reason = {}
    for entry in src_blacklist_log:
        by_reason[entry['reason']] = by_reason.get(entry['reason'], 0) + 1
    for r, c in sorted(by_reason.items()):
        reason_name = {'1': '① 网络硬故障', '2': '② 升白源失败',
                       '3': '③ 节点持续低质 (lq≥5)', '4': '④ 累计低分 (total≥15)'}[r]
        print(f"    {reason_name}: {c}")
    print()

    # 源 score 分布
    score_bands = {'100': 0, '90-99': 0, '70-89': 0, '50-69': 0, '30-49': 0, '<30': 0}
    for s in sources.values():
        if s.status == 'blacklisted':
            continue
        if s.score == 100:
            score_bands['100'] += 1
        elif s.score >= 90:
            score_bands['90-99'] += 1
        elif s.score >= 70:
            score_bands['70-89'] += 1
        elif s.score >= 50:
            score_bands['50-69'] += 1
        elif s.score >= 30:
            score_bands['30-49'] += 1
        else:
            score_bands['<30'] += 1
    print("  源 score 分布 (回放后, candidate+whitelisted):")
    for band, cnt in score_bands.items():
        print(f"    {band:>6}: {cnt}")
    print()

    # 接近拉黑的源 (lq≥3 或 lst≥10)
    danger = [s for s in sources.values() if s.status != 'blacklisted'
              and (s.consecutive_low_quality >= 3 or s.low_score_total >= 10)]
    danger.sort(key=lambda s: (-s.consecutive_low_quality, -s.low_score_total))
    print(f"  接近拉黑的源 (lq≥3 或 total≥10): {len(danger)}")
    for s in danger[:10]:
        print(f"    [{s.consecutive_low_quality}/5 lq] [{s.low_score_total}/15 total] "
              f"score={s.score:.1f} {s.url[:60]}")
    print()

    # ===== 模式 B: 节点级稳态预测 =====
    print("【模式 B】节点级稳态预测 (未来 30 轮)...")
    nodes, cur_round = replay_nodes()
    forecast = forecast_nodes(nodes, cur_round, future_rounds=30)

    by_verdict = {}
    for f in forecast:
        by_verdict[f['verdict']] = by_verdict.get(f['verdict'], 0) + 1
    print(f"  节点总数: {len(nodes)}")
    for v, c in by_verdict.items():
        print(f"    {v}: {c}")
    print()

    # 拉黑速度分布
    blk_rounds = [f['rounds_to_blacklist'] for f in forecast
                  if f['verdict'] == 'will_blacklist' and f['rounds_to_blacklist']]
    if blk_rounds:
        print(f"  预计拉黑速度: 中位 {sorted(blk_rounds)[len(blk_rounds)//2]} 轮 "
              f"(min={min(blk_rounds)}, max={max(blk_rounds)})")

    # 预计拉黑节点速度分布
    will_blk = [f for f in forecast if f['verdict'] == 'will_blacklist']
    speed_dist = {'>=2048': 0, '1024-2047': 0, '512-1023': 0, '100-511': 0, '<100': 0, '0/未测': 0}
    for f in will_blk:
        sp = f['avg_speed']
        if sp == 0:
            speed_dist['0/未测'] += 1
        elif sp >= 2048:
            speed_dist['>=2048'] += 1
        elif sp >= 1024:
            speed_dist['1024-2047'] += 1
        elif sp >= 512:
            speed_dist['512-1023'] += 1
        elif sp >= 100:
            speed_dist['100-511'] += 1
        else:
            speed_dist['<100'] += 1
    print("  预计被拉黑节点的速度分布:")
    for sp, c in speed_dist.items():
        print(f"    {sp}: {c}")
    print()

    # ===== 输出 JSON 报告 =====
    report = {
        'timestamp': datetime.now().isoformat(timespec='seconds'),
        'rules_version': 'v2.3',
        'dry_run': True,
        'mode_a_source_replay': {
            'last_round': last_round,
            'total_sources': len(sources),
            'will_blacklist_count': len(src_blacklist_log),
            'by_reason': by_reason,
            'score_bands': score_bands,
            'danger_zone': [
                {'url': s.url, 'score': round(s.score, 1),
                 'lq': s.consecutive_low_quality, 'lst': s.low_score_total}
                for s in danger
            ],
            'blacklist_log': src_blacklist_log,
        },
        'mode_b_node_forecast': {
            'total_nodes': len(nodes),
            'forecast_horizon_rounds': 30,
            'by_verdict': by_verdict,
            'will_blacklist_speed_distribution': speed_dist,
            'sample_will_blacklist': [
                {'sig': f['sig'][:60], 'rounds': f['rounds_to_blacklist'],
                 'reason': f['reason'], 'avg_speed': f['avg_speed']}
                for f in will_blk[:20]
            ],
        },
    }

    out_json = '/tmp/v2.3-dryrun-report.json'
    with open(out_json, 'w') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"完整报告: {out_json}")

    # 文本摘要
    out_txt = '/tmp/v2.3-dryrun-report.txt'
    with open(out_txt, 'w') as f:
        f.write(f"v2.3 dry-run 报告 ({datetime.now().isoformat(timespec='seconds')})\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"模式 A 源级回放 (round 1..{last_round}):\n")
        f.write(f"  总源: {len(sources)}, 立即拉黑: {len(src_blacklist_log)}\n")
        for r, c in sorted(by_reason.items()):
            reason_name = {'1': '① 网络故障', '2': '② 升白源失败',
                           '3': '③ lq≥5', '4': '④ total≥15'}[r]
            f.write(f"    {reason_name}: {c}\n")
        f.write(f"\n  危险区 (lq≥3 或 total≥10): {len(danger)}\n")
        for s in danger[:20]:
            f.write(f"    [{s.consecutive_low_quality}/5][{s.low_score_total}/15] "
                    f"score={s.score:.1f} {s.url[:60]}\n")
        f.write(f"\n模式 B 节点预测 (未来 30 轮):\n")
        f.write(f"  总节点: {len(nodes)}\n")
        for v, c in by_verdict.items():
            f.write(f"    {v}: {c}\n")
        f.write(f"  拉黑节点速度分布:\n")
        for sp, c in speed_dist.items():
            f.write(f"    {sp}: {c}\n")
    print(f"文本摘要: {out_txt}")

    return report


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
