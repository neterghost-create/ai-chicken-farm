#!/bin/bash
# certbot 證書續期後自動 reload nginx
# 觸發: certbot 完成續期任何證書時
# 環境: certbot 注入 RENEWED_LINEAGE (e.g. /etc/letsencrypt/live/example.duckdns.org)
#       和 RENEWED_DOMAINS (空格分隔)

set -e

LOG_TAG="certbot-deploy-hook"
LINEAGE="${RENEWED_LINEAGE:-unknown}"
DOMAINS="${RENEWED_DOMAINS:-unknown}"

logger -t "$LOG_TAG" "證書續期完成: $LINEAGE (domains: $DOMAINS), 準備 reload nginx"

# 先做語法檢查, 任何錯誤都不重啟 (寧可暫時用舊證書也不能讓 nginx 掛)
if ! nginx -t 2>&1 | logger -t "$LOG_TAG"; then
    logger -t "$LOG_TAG" "❌ nginx -t 失敗, 拒絕 reload (證書文件已換但 nginx 仍跑舊版)"
    exit 1
fi

# reload (向 master 發 HUP, 不中斷活躍連接)
if nginx -s reload 2>&1 | logger -t "$LOG_TAG"; then
    logger -t "$LOG_TAG" "✓ nginx reload 成功, 新證書已生效"
else
    logger -t "$LOG_TAG" "❌ nginx reload 失敗"
    exit 1
fi
