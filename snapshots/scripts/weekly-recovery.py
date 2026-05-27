#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
weekly-recovery.py — v2.3 源级周期恢复

每周日 03:00 跑一次:
  candidate AND consecutive_fails=0 AND consecutive_low_quality=0 AND low_score_total=0
  → score = MIN(100, score + 5)

防止"一次失误永久惩罚":
  - 一次失误扣到 70 分后, 6 周无故障即恢复到 100
  - 已经 100 的源不变 (cap)
  - 有任何故障/低质标记的源不参与恢复 (避免奖励垃圾)
"""
import sys
import sqlite3
from datetime import datetime, timezone

SOURCES_DB = "/opt/subs-check/scripts/source-scores.db"
RECOVERY_AMOUNT = 5


def main():
    db = sqlite3.connect(SOURCES_DB)

    # 跑前快照
    before = db.execute("""
        SELECT COUNT(*), AVG(score), MIN(score), MAX(score)
        FROM sources
        WHERE status='candidate'
          AND consecutive_fails = 0
          AND consecutive_low_quality = 0
          AND low_score_total = 0
    """).fetchone()
    n_eligible, avg_before, min_before, max_before = before

    if n_eligible == 0:
        print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] 周期恢复: 无符合条件的源")
        db.close()
        return 0

    # 应用 +5
    cur = db.execute("""
        UPDATE sources SET score = MIN(100, score + ?)
        WHERE status='candidate'
          AND consecutive_fails = 0
          AND consecutive_low_quality = 0
          AND low_score_total = 0
          AND score < 100
    """, (RECOVERY_AMOUNT,))
    n_recovered = cur.rowcount
    db.commit()

    # 跑后快照
    after = db.execute("""
        SELECT AVG(score) FROM sources WHERE status='candidate'
    """).fetchone()
    avg_after = after[0]

    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] 周期恢复 v2.3:")
    print(f"  符合条件: {n_eligible}, 实际恢复: {n_recovered} (已满分 {n_eligible - n_recovered} 跳过)")
    print(f"  candidate 池均分: {avg_before:.1f} → {avg_after:.1f}")
    db.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
