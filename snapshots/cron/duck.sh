#!/bin/bash
# DuckDNS IP 自動推送 — 多域名 (2026-05-27 重寫)
#
# 原版用域名 'clash-airport' 是孤兒, conf 裡實際是 example-root + 衍生域名.
# 重寫後 4 個 duckdns 域名一次推送 (DuckDNS API 支援 comma-separated).
#
# 觸發: cron */5 * * * *
# Token: 從 /etc/duckdns/duckdns.conf 讀取 (key=token, 帶引號)
#
# DuckDNS API:
#   GET https://www.duckdns.org/update?domains=A,B,C&token=X&ip=
#   - ip 為空時, DuckDNS 自動用請求源 IP (CGNAT 場景下這是公網出口 IP)
#   - 回應: 純文本 'OK' 或 'KO'
#
# 退出碼:
#   0 = 推送成功 (OK)
#   1 = 推送失敗 (KO 或網絡錯誤)

set -uo pipefail

CONF="/etc/duckdns/duckdns.conf"
LOG_FILE="/var/log/duckdns-update.log"
DOMAINS="example-root,example-legacy,example-aux,example"

log() { echo "[$(date '+%F %T %z')] $*" | tee -a "$LOG_FILE" >&2; }

# 讀 token (conf 格式: token="...")
if [ ! -f "$CONF" ]; then
    log "❌ 配置 $CONF 不存在"
    exit 1
fi
# shellcheck disable=SC1090
source "$CONF"
if [ -z "${token:-}" ]; then
    log "❌ token 未在 $CONF 中設置"
    exit 1
fi

# 推送
URL="https://www.duckdns.org/update?domains=${DOMAINS}&token=${token}&ip="
RESP=$(curl -sk --max-time 15 "$URL" 2>&1)
RC=$?

if [ $RC -ne 0 ]; then
    log "❌ 網絡錯誤 (curl rc=$RC), domains=$DOMAINS"
    exit 1
fi

if [ "$RESP" = "OK" ]; then
    log "✓ DuckDNS 推送成功 ($DOMAINS)"
    exit 0
else
    log "❌ DuckDNS 拒絕 (response='$RESP'), domains=$DOMAINS"
    exit 1
fi
