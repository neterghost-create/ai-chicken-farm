#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
source-quality-history-cleanup.py — v2.3 历史数据清理

每天 04:33 跑一次 (避开 04:00 sync-lza6 + 04:30 openclaw-conditional-restart):
  DELETE FROM source_quality_history WHERE timestamp < datetime('now', '-30 days')

防止 source_quality_history 表无限增长.
按 v2.3 时间窗口 (5 轮 = 30h, 评估只看最近 5 轮), 30 天前的数据已无意义.
"""
import sys
import sqlite3
from datetime import datetime, timezone

SOURCES_DB = "/opt/subs-check/scripts/source-scores.db"
RETAIN_DAYS = 30


def main():
    db = sqlite3.connect(SOURCES_DB)

    before = db.execute("SELECT COUNT(*) FROM source_quality_history").fetchone()[0]

    cur = db.execute("""
        DELETE FROM source_quality_history
        WHERE timestamp < datetime('now', ?)
    """, (f'-{RETAIN_DAYS} days',))
    n_deleted = cur.rowcount

    db.commit()
    db.execute("VACUUM")  # 释放空间
    db.close()

    after = before - n_deleted
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] history-cleanup v2.3:")
    print(f"  删除 {n_deleted} 行 ({RETAIN_DAYS} 天前数据), 剩余 {after}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
