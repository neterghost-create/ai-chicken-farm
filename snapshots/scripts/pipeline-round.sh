#!/bin/bash
# pipeline-round.sh — 一轮完整处理: convert → incremental → cn-refresh → notify
# GitHub 同步由 auto-sync-github.sh 文件监听自动处理
set -euo pipefail

LOG_DIR="/var/log"
TS=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$TS] === pipeline-round 开始 ==="

# 1. convert-formats (信號 B+C: all.yaml / v2ray.txt / base64.txt / all-config.yaml)
echo "[$TS] [1/4] convert-formats..."
/usr/bin/python3 /opt/subs-check/scripts/convert-formats.py >> "$LOG_DIR/subs-check-convert.log" 2>&1
echo "[$TS] [1/4] convert-formats 完成"

# 2. incremental-check (信號 A: CN 代理探活节点)
echo "[$TS] [2/4] incremental-check..."
/usr/bin/python3 /opt/subs-check/scripts/incremental-check.py >> "$LOG_DIR/subs-check-incremental.log" 2>&1
echo "[$TS] [2/4] incremental-check 完成"

# 3. cn-refresh (CN 代理拉活 → cn.yaml + cn-stats.json)
echo "[$TS] [3/4] cn-refresh..."
/usr/bin/python3 /opt/subs-check/scripts/cn-refresh.py >> "$LOG_DIR/cn-refresh.log" 2>&1
echo "[$TS] [3/4] cn-refresh 完成"

# 4. notify-telegram (新轮次 → 合并推送: 节点统计 + CN 代理 + 全部订阅 URL)
echo "[$TS] [4/4] notify-telegram..."
/usr/bin/python3 /opt/subs-check/scripts/notify-telegram.py >> "$LOG_DIR/subs-check-notify.log" 2>&1
echo "[$TS] [4/4] notify-telegram 完成"

TS=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TS] === pipeline-round 完成 ==="
