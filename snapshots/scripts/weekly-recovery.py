#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
weekly-recovery.py — v3.1 双表周期恢复

每周日 03:00 跑一次.

处理两张表:
  source-scores.db (sources表):
    1. 修复孤立状态: state IS NULL → 'testing'
    2. 修复 score 越界: < 0 → 0, > 100 → 100
    3. 兜底: testing 状态 score < 30 → 强制 recovering
    4. 报告各状态分布快照

  history.db (nodes_history表):
    1. 修复孤立状态: state IS NULL → 'testing'
    2. 修复 score 越界
    3. 兜底: recovering 状态 score 停在 0 → 强制 state='testing', score=50 (重启)
    4. 兜底: testing 状态 score < 10 且连续失败 > 10 → 强制 recovering
    5. 报告各状态分布快照
"""
import sys
import sqlite3
from datetime import datetime, timezone

SOURCES_DB = "/opt/subs-check/scripts/source-scores.db"
HISTORY_DB = "/opt/subs-check/scripts/history.db"


def recover_sources():
    """处理 source-scores.db 的 sources 表"""
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
    n_force_rec = db.execute("""
        UPDATE sources SET state='recovering'
        WHERE state='testing' AND score < 30
    """).rowcount

    # 4. 状态分布快照
    state_dist = db.execute(
        "SELECT state, COUNT(*), AVG(score), MIN(score), MAX(score) FROM sources GROUP BY state"
    ).fetchall()

    db.commit()
    db.close()

    return {
        "orphan": n_orphan,
        "oob_low": n_oob_low,
        "oob_high": n_oob_high,
        "force_rec": n_force_rec,
        "state_dist": state_dist,
    }


def recover_nodes():
    """处理 history.db 的 nodes_history 表"""
    db = sqlite3.connect(HISTORY_DB)

    # 检查表是否存在
    has_nodes = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nodes_history'"
    ).fetchone()
    if not has_nodes:
        db.close()
        return {"skip": True}

    # 确保 state 列存在
    try:
        db.execute("ALTER TABLE nodes_history ADD COLUMN state TEXT DEFAULT 'testing'")
        db.commit()
    except sqlite3.OperationalError:
        pass

    # 1. 修复孤立状态
    n_orphan = db.execute(
        "UPDATE nodes_history SET state='testing' WHERE state IS NULL OR state=''"
    ).rowcount

    # 2. 修复 score 越界
    n_oob_low = db.execute(
        "UPDATE nodes_history SET quality_score=0 WHERE quality_score < 0"
    ).rowcount
    n_oob_high = db.execute(
        "UPDATE nodes_history SET quality_score=100 WHERE quality_score > 100"
    ).rowcount

    # 3. 兜底: recovering 状态卡死 (score=0 且连续失败 > 20) → 重启为 testing
    #    给节点一次重新测试的机会
    n_restart = db.execute("""
        UPDATE nodes_history SET state='testing', quality_score=50
        WHERE state='recovering' AND quality_score <= 0 AND consecutive_fails > 20
    """).rowcount

    # 4. 兜底: testing 状态 score < 5 且连续失败 > 15 → 强制 recovering
    n_force_rec = db.execute("""
        UPDATE nodes_history SET state='recovering', quality_score=0
        WHERE state='testing' AND quality_score < 5 AND consecutive_fails > 15
    """).rowcount

    # 5. 清理超过 30 天未见的节点 (可选, 减少 DB 体积)
    n_cleanup = db.execute("""
        DELETE FROM nodes_history
        WHERE last_seen < datetime('now', '-30 days')
          AND state = 'recovering'
          AND quality_score <= 0
    """).rowcount

    # 6. 状态分布快照
    state_dist = db.execute(
        "SELECT state, COUNT(*), AVG(quality_score), MIN(quality_score), MAX(quality_score) "
        "FROM nodes_history GROUP BY state"
    ).fetchall()

    db.commit()
    db.close()

    return {
        "orphan": n_orphan,
        "oob_low": n_oob_low,
        "oob_high": n_oob_high,
        "restart": n_restart,
        "force_rec": n_force_rec,
        "cleanup": n_cleanup,
        "state_dist": state_dist,
    }


def main():
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')

    # === sources 表 ===
    print(f"[{ts}] 周期维护 v3.1:")
    print(f"\n  === sources 表 ===")
    src = recover_sources()
    print(f"  孤立状态修复: {src['orphan']}")
    print(f"  score 越界修复: 低 {src['oob_low']}, 高 {src['oob_high']}")
    print(f"  testing 转 recovering (score<30): {src['force_rec']}")
    print(f"  状态分布:")
    for state, cnt, avg, mn, mx in src['state_dist']:
        avg = avg or 0
        mn = mn or 0
        mx = mx or 0
        print(f"    {state or 'NULL':<12}: {cnt:>4} 个, 均分 {avg:>5.1f}, 范围 [{mn:>5.1f}, {mx:>5.1f}]")

    # === nodes_history 表 ===
    print(f"\n  === nodes_history 表 ===")
    nodes = recover_nodes()
    if nodes.get("skip"):
        print(f"  表不存在, 跳过")
    else:
        print(f"  孤立状态修复: {nodes['orphan']}")
        print(f"  score 越界修复: 低 {nodes['oob_low']}, 高 {nodes['oob_high']}")
        print(f"  recovering 重启 (score=0 且 fails>20): {nodes['restart']}")
        print(f"  testing 转 recovering (score<5 且 fails>15): {nodes['force_rec']}")
        print(f"  清理过期节点 (>30天): {nodes['cleanup']}")
        print(f"  状态分布:")
        for state, cnt, avg, mn, mx in nodes['state_dist']:
            avg = avg or 0
            mn = mn or 0
            mx = mx or 0
            print(f"    {state or 'NULL':<12}: {cnt:>4} 个, 均分 {avg:>5.1f}, 范围 [{mn:>5.1f}, {mx:>5.1f}]")

    return 0


if __name__ == '__main__':
    sys.exit(main())
