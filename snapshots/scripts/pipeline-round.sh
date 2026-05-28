#!/bin/bash
# pipeline-round.sh — 一轮完整处理: convert-formats → incremental-check → cn-refresh
# GitHub 同步由 auto-sync-github.sh 文件监听自动处理
set -euo pipefail

LOG_DIR="/var/log"
TS=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$TS] === pipeline-round 开始 ==="

# 1. convert-formats (信號 B+C: all.yaml / v2ray.txt / base64.txt / all-config.yaml)
echo "[$TS] [1/3] convert-formats..."
/usr/bin/python3 /opt/subs-check/scripts/convert-formats.py >> "$LOG_DIR/subs-check-convert.log" 2>&1
echo "[$TS] [1/3] convert-formats 完成"

# 2. incremental-check (信號 A: CN 代理探活节点)
echo "[$TS] [2/3] incremental-check..."
/usr/bin/python3 /opt/subs-check/scripts/incremental-check.py >> "$LOG_DIR/subs-check-incremental.log" 2>&1
echo "[$TS] [2/3] incremental-check 完成"

# 3. cn-refresh (CN 代理拉活 → cn.yaml + Telegram 推送)
echo "[$TS] [3/3] cn-refresh..."
/usr/bin/python3 /opt/subs-check/scripts/cn-refresh.py >> "$LOG_DIR/cn-refresh.log" 2>&1
echo "[$TS] [3/3] cn-refresh 完成"

TS=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TS] === pipeline-round 完成 ==="
