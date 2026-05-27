#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
weekly-recovery.py — v3.0 三态机周期恢复

每周日 03:00 跑一次. v3.0 设计下, recovering 状态已经自动 +1±0.3 每轮恢复,
不再需要 v2.3 那种"6 周无故障奖励 +5"的恢复逻辑.

本脚本现在仅做:
  1. 修复孤立状态: state IS NULL 的源 → 'testing'
  2. 修复 score 越界: < 0 → 0, > 100 → 100
  3. 兜底: testing 状态下 score 长期停在 0-30 区间 (recovering 没起作用) → 强制 state='recovering'
  4. 报告各状态分布快照
"""
import sys
import sqlite3
from datetime import datetime, timezone

SOURCES_DB = "/opt/subs-check/scripts/source-scores.db"


def main():
    db = sqlite3.connect(SOURCES_DB)

    # 1. 修复孤立状态
    n_orphan = db.execute(
        "UPDATE sources SET state='testing' WHERE state IS NULL OR state=''"
    ).rowcount

    # 2. 修复 score 越界
    n_oob_low = db.execute(
        "UPDATE sources SET score=0 WHERE score < 0"
    ).rowcount
    n_oob_high = db.execute(
        "UPDATE sources SET score=100 WHERE score > 100"
    ).rowcount

    # 3. 兜底: testing 状态 score < 30 持续 → 强制进 recovering
    # (避免 testing 池里的源永远拿不到测试机会)
    n_force_rec = db.execute("""
        UPDATE sources SET state='recovering'
        WHERE state='testing' AND score < 30
    """).rowcount

    # 4. 状态分布快照
    state_dist = db.execute(
        "SELECT state, COUNT(*), AVG(score), MIN(score), MAX(score) FROM sources GROUP BY state"
    ).fetchall()

    db.commit()

    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    print(f"[{ts}] 周期维护 v3.0:")
    print(f"  孤立状态修复: {n_orphan}")
    print(f"  score 越界修复: 低 {n_oob_low}, 高 {n_oob_high}")
    print(f"  testing 转 recovering (score<30): {n_force_rec}")
    print(f"  状态分布:")
    for state, cnt, avg, mn, mx in state_dist:
        avg = avg or 0
        mn = mn or 0
        mx = mx or 0
        print(f"    {state or 'NULL':<12}: {cnt:>4} 个, 均分 {avg:>5.1f}, 范围 [{mn:>5.1f}, {mx:>5.1f}]")

    db.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
