#!/usr/bin/env bash
# Uptime monitor 共享函數庫
# 使用: source /usr/local/lib/uptime-common.sh
#
# 提供:
#   log <msg>                          → echo + tee 到 $LOG_FILE
#   get_state <key>                    → 從 $STATE_FILE 讀
#   set_state <key> <val>              → 原子寫 $STATE_FILE
#   check_url <url> [timeout]          → curl 返回 HTTP code, default timeout=10
#   notify_telegram <title> <body>     → 發 Telegram, 用 /etc/telegram-bot.conf
#   is_maintenance_window              → 看當前時間是否在 $MAINTENANCE_WINDOWS 內
#                                        命中時 echo window 字串並 return 0
#                                        未命中 return 1
#
# 調用方必須預設變量:
#   LOG_FILE     日誌路徑
#   STATE_FILE   狀態文件路徑
#   MAINTENANCE_WINDOWS  bash 數組 (HH:MM-HH:MM 格式)
#   CURL_TIMEOUT 預設 curl 超時 (可選, default 10)
#
# 通知函數可選依賴:
#   /etc/telegram-bot.conf — 提供 TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID

# ═══════════════ 防重複加載 ═══════════════
if [ -n "${UPTIME_COMMON_LOADED:-}" ]; then
    return 0
fi
UPTIME_COMMON_LOADED=1

# ═══════════════ 預設值 ═══════════════
: "${CURL_TIMEOUT:=10}"
: "${TELEGRAM_CONF:=/etc/telegram-bot.conf}"

# ═══════════════ 日誌 ═══════════════
log() {
    echo "[$(date '+%F %T %z')] $*" | tee -a "$LOG_FILE"
}

# ═══════════════ 狀態文件 ═══════════════
get_state() {
    [ -f "$STATE_FILE" ] || return
    grep -E "^$1=" "$STATE_FILE" 2>/dev/null | tail -1 | cut -d= -f2-
}

set_state() {
    local key="$1" val="$2"
    local tmp; tmp=$(mktemp)
    if [ -f "$STATE_FILE" ]; then
        grep -vE "^$key=" "$STATE_FILE" > "$tmp" 2>/dev/null || true
    fi
    echo "$key=$val" >> "$tmp"
    mv "$tmp" "$STATE_FILE"
}

# ═══════════════ HTTP 探活 ═══════════════
check_url() {
    local url="$1" timeout="${2:-$CURL_TIMEOUT}"
    curl -s -o /dev/null -w "%{http_code}" -m "$timeout" "$url" 2>/dev/null
}

# ═══════════════ 維護窗口豁免 ═══════════════
# 調用方必須先定義 MAINTENANCE_WINDOWS=("HH:MM-HH:MM" ...) 數組
is_maintenance_window() {
    local now_hm; now_hm=$(date '+%H:%M')
    local window start end
    for window in "${MAINTENANCE_WINDOWS[@]}"; do
        start="${window%-*}"
        end="${window#*-}"
        if [[ "$now_hm" > "$start" || "$now_hm" == "$start" ]] && \
           [[ "$now_hm" < "$end" || "$now_hm" == "$end" ]]; then
            echo "$window"
            return 0
        fi
    done
    return 1
}

# ═══════════════ Telegram 通知 ═══════════════
notify_telegram() {
    local title="$1" body="$2"
    [ -f "$TELEGRAM_CONF" ] || { log "  [tg] 無 $TELEGRAM_CONF, 跳過"; return 1; }
    # shellcheck disable=SC1090
    source "$TELEGRAM_CONF"
    [ -z "${TELEGRAM_BOT_TOKEN:-}" ] && { log "  [tg] BOT_TOKEN 未設"; return 1; }
    [ -z "${TELEGRAM_CHAT_ID:-}" ] && { log "  [tg] CHAT_ID 未設"; return 1; }

    local text="*$title*

\`\`\`
$body
\`\`\`"
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 \
        -d "chat_id=$TELEGRAM_CHAT_ID" \
        -d "parse_mode=Markdown" \
        --data-urlencode "text=$text" \
        "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" 2>/dev/null)
    if [ "$code" = "200" ]; then
        log "  [tg] ✓ Telegram 已發送"
        return 0
    else
        log "  [tg] ⚠️  Telegram 發送失敗 (HTTP $code)"
        return 1
    fi
}
