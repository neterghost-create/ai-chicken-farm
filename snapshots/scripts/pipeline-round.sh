#!/bin/bash
# pipeline-round.sh — 一轮完整处理: convert-formats → incremental-check → sync GitHub
set -euo pipefail

LOG_DIR="/var/log"
REPO_DIR="/tmp/ai-chicken-farm-public"
PROD_SS_DIR="/opt/ss-monitor"
PROD_SCRIPTS_DIR="/opt/subs-check/scripts"

# 脱敏映射 (用变量拼接, 避免 pre-commit hook 误报)
D1="neterghost.duckdns.org"
D2="oneapi-neterghost.duckdns.org"
D3="webai-neterghost.duckdns.org"
R1="example-root.duckdns.org"
R2="example-legacy.duckdns.org"
R3="example-aux.duckdns.org"

TS=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TS] === pipeline-round 开始 ==="

# 1. convert-formats
echo "[$TS] [1/3] convert-formats..."
/usr/bin/python3 "$PROD_SCRIPTS_DIR/convert-formats.py" >> "$LOG_DIR/subs-check-convert.log" 2>&1
echo "[$TS] [1/3] convert-formats 完成"

# 2. incremental-check
echo "[$TS] [2/3] incremental-check..."
/usr/bin/python3 "$PROD_SCRIPTS_DIR/incremental-check.py" >> "$LOG_DIR/subs-check-incremental.log" 2>&1
echo "[$TS] [2/3] incremental-check 完成"

# 3. 同步到 GitHub
echo "[$TS] [3/3] sync GitHub..."

# 3a. ss-monitor 4 件套
"$PROD_SS_DIR/sync-to-github.sh" "auto: pipeline $(date '+%Y%m%d_%H%M')" >> "$LOG_DIR/subs-check-sync-github.log" 2>&1

# 3b. scripts/
cd "$REPO_DIR"
for f in convert-formats.py incremental-check.py sync-lza6.py weekly-recovery.py discover-cn-proxies.py source-fetcher.py; do
    [ -f "$PROD_SCRIPTS_DIR/$f" ] && cp "$PROD_SCRIPTS_DIR/$f" "snapshots/scripts/$f"
done

# 脱敏 notify-telegram.py
if [ -f "$PROD_SCRIPTS_DIR/notify-telegram.py" ]; then
    cp "$PROD_SCRIPTS_DIR/notify-telegram.py" "snapshots/scripts/notify-telegram.py"
    sed -i "s|$D2|$R2|g" "snapshots/scripts/notify-telegram.py"
    sed -i "s|$D1|$R1|g" "snapshots/scripts/notify-telegram.py"
fi

# 只在有改动时 commit+push
if [ -n "$(git status --porcelain)" ]; then
    git add -A
    if git commit -m "auto: pipeline $(date '+%Y%m%d_%H%M')" --quiet; then
        git push origin main --quiet 2>&1
        echo "[$TS] [3/3] GitHub 同步完成"
    else
        echo "[$TS] [3/3] commit 失败 (可能是 pre-commit hook)"
    fi
else
    echo "[$TS] [3/3] 无改动, 跳过"
fi

TS=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TS] === pipeline-round 完成 ==="
