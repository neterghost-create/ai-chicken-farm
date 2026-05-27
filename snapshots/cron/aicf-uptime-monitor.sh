#!/usr/bin/env bash
# example.duckdns.org 公網可達性監控
#
# 設計:
#   - 每 30 min 跑一次 (cron */30 * * * *)
#   - 連續 2 次失敗 (=60min) 才告警 Telegram, 避免單次抖動誤報
#   - 同時驗證 https://example.duckdns.org/ss-monitor/ 主頁 + /api/free-pool API
#   - 不做自動修復 — aicf 只是 nginx vhost, 沒有獨立後端可重啟
#     若 nginx 整體掛了, openclaw-uptime-monitor 會處理 (修 nginx 同時修 openclaw)
#
# 狀態文件格式 (key=value):
#   last_status=UP|DOWN
#   consecutive_fail=N
#   last_alert_at=epoch  (恢復通知去重)

set -uo pipefail

# ═══════════════ 共享函數庫 ═══════════════
# 提供: log, get_state, set_state, check_url, notify_telegram, is_maintenance_window
# shellcheck source=/usr/local/lib/uptime-common.sh
source /usr/local/lib/uptime-common.sh

# ═══════════════ 配置 ═══════════════
DOMAIN="example.duckdns.org"
URL_HOMEPAGE="https://$DOMAIN/ss-monitor/"
URL_API="https://$DOMAIN/api/free-pool"
EXPECTED_HTTP=200

LOG_FILE="/var/log/aicf-uptime-monitor.log"
STATE_FILE="/var/lib/aicf-uptime-monitor.state"
mkdir -p "$(dirname "$STATE_FILE")"

CURL_TIMEOUT=10
CONSECUTIVE_FAIL_THRESHOLD=2

# ═══════════════ 維護窗口豁免 ═══════════════
# 跟 openclaw-uptime 對稱:
#   00:00-00:10: openclaw-auto-update (重啟 nginx 鄰居 openclaw, 可能影響 nginx 整體)
#   04:00-04:20: certbot.timer 續期 + 條件重啟 + apt dpkg 鎖
MAINTENANCE_WINDOWS=(
    "00:00-00:10"
    "04:00-04:20"
)

# ═══════════════ 主流程 ═══════════════
main() {
    # 維護窗口豁免
    if window=$(is_maintenance_window); then
        log "↻ 維護窗口 $window 內, 跳過巡檢"
        exit 0
    fi

    local home_code api_code overall_status
    home_code=$(check_url "$URL_HOMEPAGE")
    api_code=$(check_url "$URL_API")

    # 兩個 endpoint 都 200 才算 UP
    if [ "$home_code" = "$EXPECTED_HTTP" ] && [ "$api_code" = "$EXPECTED_HTTP" ]; then
        overall_status="UP"
    else
        overall_status="DOWN"
    fi

    local prev_status; prev_status=$(get_state last_status)
    local consec; consec=$(get_state consecutive_fail); consec=${consec:-0}

    if [ "$overall_status" = "UP" ]; then
        # 從 DOWN 恢復: 通知 + 重置計數
        if [ "$prev_status" = "DOWN" ] && [ "$consec" -ge "$CONSECUTIVE_FAIL_THRESHOLD" ]; then
            log "✓ aicf 恢復 (home=$home_code api=$api_code, 之前連敗 $consec 次)"
            notify_telegram \
                "✅ example.duckdns.org 已恢復" \
                "域名: $DOMAIN
首頁: HTTP $home_code
API:  HTTP $api_code

之前連續失敗 $consec 次, 現恢復"
        fi
        set_state last_status UP
        set_state consecutive_fail 0
        log "✓ aicf UP (home=$home_code api=$api_code)"
    else
        # DOWN 累加
        consec=$((consec + 1))
        set_state last_status DOWN
        set_state consecutive_fail "$consec"
        log "✗ aicf DOWN (home=$home_code api=$api_code), 連敗 $consec 次"

        # 達到閾值且本次達到後第一次告警 (consec == threshold), 之後保持靜默
        if [ "$consec" -eq "$CONSECUTIVE_FAIL_THRESHOLD" ]; then
            log "  → 觸發告警 (達到閾值 $CONSECUTIVE_FAIL_THRESHOLD)"
            notify_telegram \
                "🚨 example.duckdns.org 不可達" \
                "域名: $DOMAIN
首頁: HTTP $home_code (期望 200)
API:  HTTP $api_code (期望 200)

連續失敗 $consec 次 (~$((consec * 30)) 分鐘)
排查方向:
  1. nginx 是否 active: systemctl status nginx
  2. ss-monitor 後端: systemctl status ss-monitor
  3. 證書: ls /etc/letsencrypt/live/example.duckdns.org/
  4. 公網 IP: dig +short $DOMAIN
  5. 日誌: $LOG_FILE"
            set_state last_alert_at "$(date +%s)"
        elif [ "$consec" -gt "$CONSECUTIVE_FAIL_THRESHOLD" ]; then
            log "  → 已告警過, 持續 DOWN 不重複"
        else
            log "  → 未達閾值 ($CONSECUTIVE_FAIL_THRESHOLD), 暫不告警"
        fi
    fi
}

main "$@"
