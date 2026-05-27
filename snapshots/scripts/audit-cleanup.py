#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit-cleanup.py — discover-airports 私有审计日志清理

每周日 03:30 跑一次:
  - 每源仅保留最近 10 条 audit 记录
  - 30 天前的 info/warn 全部清掉
  - critical 永久保留 (用户人工 review 用)

不动 sources 表, 不动 discovery_state.
"""
import sqlite3
import sys
from datetime import datetime, timezone, timedelta

DB = "/opt/subs-check/scripts/source-scores.db"
KEEP_PER_SOURCE = 10
RETAIN_DAYS_INFO_WARN = 30


def main():
    conn = sqlite3.connect(DB, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")

    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETAIN_DAYS_INFO_WARN)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    n_old = conn.execute(
        """DELETE FROM source_audits
           WHERE severity IN ('info', 'warn') AND audited_at < ?""",
        (cutoff,),
    ).rowcount

    # 每源仅保留最近 10 条
    n_excess = conn.execute(
        """DELETE FROM source_audits
           WHERE audit_id NOT IN (
             SELECT audit_id FROM (
               SELECT audit_id,
                      ROW_NUMBER() OVER (PARTITION BY source_url ORDER BY audited_at DESC) AS rn
               FROM source_audits
             )
             WHERE rn <= ?
           )""",
        (KEEP_PER_SOURCE,),
    ).rowcount

    conn.commit()

    remaining = conn.execute("SELECT COUNT(*) FROM source_audits").fetchone()[0]
    by_sev = conn.execute(
        "SELECT severity, COUNT(*) FROM source_audits GROUP BY severity"
    ).fetchall()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] audit-cleanup: 清 {n_old} 条 info/warn (>30天), {n_excess} 条超额 (>10/源)")
    print(f"[{ts}] 剩余 source_audits: {remaining}")
    for sev, n in by_sev:
        print(f"  {sev}: {n}")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
