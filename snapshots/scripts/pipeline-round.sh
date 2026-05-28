#!/bin/bash
# pipeline-round.sh — 一轮完整处理: convert-formats → incremental-check
# 合并两个 cron 任务, 避免 database locked 冲突
set -euo pipefail

LOG_DIR="/var/log"
TS=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$TS] === pipeline-round 开始 ==="

# 1. convert-formats (信號 B+C)
echo "[$TS] [1/2] convert-formats..."
/usr/bin/python3 /opt/subs-check/scripts/convert-formats.py >> "$LOG_DIR/subs-check-convert.log" 2>&1
echo "[$TS] [1/2] convert-formats 完成"

# 2. incremental-check (信號 A, CN 代理)
echo "[$TS] [2/2] incremental-check..."
/usr/bin/python3 /opt/subs-check/scripts/incremental-check.py >> "$LOG_DIR/subs-check-incremental.log" 2>&1
echo "[$TS] [2/2] incremental-check 完成"

TS=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TS] === pipeline-round 完成 ==="
