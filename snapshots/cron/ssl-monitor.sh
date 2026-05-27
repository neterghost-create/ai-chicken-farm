#!/usr/bin/env bash
# SSL 證書監控 - 自動掃描 nginx 配置中所有 ssl_certificate
#
# 行為：
#   1. 從 /etc/nginx/sites-enabled + conf.d 抓所有 ssl_certificate 路徑
#   2. 對每張證書讀取主題、SAN、剩餘天數
#   3. 任何證書 < WARN_DAYS 天 → Telegram 警告
#   4. 任何證書 < CRIT_DAYS 天 → Telegram 緊急
#   5. 全部健康時，根據 --quiet/--report 決定是否發每日報告
#
# 用法：
#   ssl-monitor.sh                # 標準模式：寫日誌 + 異常時告警
#   ssl-monitor.sh --report       # 每日總結模式：不管狀態都發 Telegram
#   ssl-monitor.sh --dry-run      # 不發 Telegram，只印到 stdout

set -uo pipefail

WARN_DAYS=${SSL_WARN_DAYS:-30}
CRIT_DAYS=${SSL_CRIT_DAYS:-7}
LOG_FILE="/var/log/ssl-monitor.log"
TG_CONF="/etc/telegram-bot.conf"
NGINX_DIRS=(/etc/nginx/sites-enabled /etc/nginx/conf.d)

MODE="standard"
for arg in "$@"; do
    case "$arg" in
        --report)  MODE="report" ;;
        --dry-run) MODE="dry-run" ;;
        --help|-h)
            cat <<EOF
Usage: $0 [--report|--dry-run]
  --report    無論狀態都發 Telegram（用於每日報告）
  --dry-run   不發 Telegram，只印到 stdout
Env:
  SSL_WARN_DAYS=$WARN_DAYS
  SSL_CRIT_DAYS=$CRIT_DAYS
EOF
            exit 0 ;;
    esac
done

log() { echo "[$(date '+%F %T %z')] $*" | tee -a "$LOG_FILE"; }

tg_send() {
    local msg="$1"
    if [ "$MODE" = "dry-run" ]; then
        echo "[dry-run] 會發 Telegram:"
        echo "$msg"
        return 0
    fi
    [ -f "$TG_CONF" ] || return 0
    # shellcheck disable=SC1090
    source "$TG_CONF"
    [ -z "${TELEGRAM_BOT_TOKEN:-}" ] && return 0
    [ -z "${TELEGRAM_CHAT_ID:-}" ] && return 0
    curl -s --max-time 10 \
        -d "chat_id=$TELEGRAM_CHAT_ID" \
        -d "parse_mode=Markdown" \
        --data-urlencode "text=$msg" \
        "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
        >/dev/null 2>&1 || true
}

# 從 nginx 配置抓所有 ssl_certificate 路徑（去重，跳過 .bak）
discover_certs() {
    for d in "${NGINX_DIRS[@]}"; do
        [ -d "$d" ] || continue
        # 只看實際生效的 *.conf 或無副檔名的；跳過 *.bak*
        find -L "$d" -maxdepth 2 -type f \
            ! -name "*.bak*" ! -name "*.disabled" ! -name "*~" 2>/dev/null
    done | xargs -r grep -hE "^\s*ssl_certificate\s+/" 2>/dev/null \
         | grep -v "ssl_certificate_key" \
         | awk '{print $2}' | sed 's/;$//' | sort -u
}

# 解析證書 → 輸出 "domain|days|expiry|cert_path"
inspect_cert() {
    local cert="$1"
    [ -f "$cert" ] || { echo "MISSING|0|missing|$cert"; return; }

    local exp days domain san
    exp=$(openssl x509 -enddate -noout -in "$cert" 2>/dev/null | cut -d= -f2)
    if [ -z "$exp" ]; then
        echo "PARSE_ERR|0|unreadable|$cert"
        return
    fi
    days=$(( ($(date -d "$exp" +%s) - $(date +%s)) / 86400 ))

    # 主題 CN
    domain=$(openssl x509 -subject -noout -in "$cert" 2>/dev/null \
             | sed -E 's/.*CN\s*=\s*([^,\/]+).*/\1/' \
             | tr -d ' ')
    [ -z "$domain" ] && domain=$(basename "$(dirname "$cert")")

    # SAN（如果有多個域名）
    san=$(openssl x509 -ext subjectAltName -noout -in "$cert" 2>/dev/null \
          | grep -oE "DNS:[^,]+" | sed 's/DNS://g' | tr '\n' ',' | sed 's/,$//' | tr -d ' ')

    if [ -n "$san" ] && [ "$san" != "$domain" ]; then
        domain="$domain ($san)"
    fi

    echo "$domain|$days|$exp|$cert"
}

# ====== 主流程 ======
log "===== SSL 監控啟動（warn=$WARN_DAYS / crit=$CRIT_DAYS）====="

mapfile -t certs < <(discover_certs)
if [ "${#certs[@]}" -eq 0 ]; then
    log "❌ 未在 nginx 配置中找到任何 ssl_certificate"
    tg_send "🚨 SSL 監控異常：nginx 中找不到任何證書"
    exit 2
fi

log "📋 發現 ${#certs[@]} 張證書：${certs[*]}"

declare -a ROWS=()
declare -a ALERTS=()
worst=99999
worst_domain=""
exit_code=0

for cert in "${certs[@]}"; do
    info=$(inspect_cert "$cert")
    IFS='|' read -r domain days exp path <<< "$info"

    icon="✓"
    level=""
    if [ "$days" -lt "$CRIT_DAYS" ]; then
        icon="🚨"; level="CRIT"
    elif [ "$days" -lt "$WARN_DAYS" ]; then
        icon="⚠️"; level="WARN"
    elif [ "$domain" = "MISSING" ] || [ "$domain" = "PARSE_ERR" ]; then
        icon="❌"; level="ERR"
    fi

    line="$icon $domain → ${days}天 ($exp) [$path]"
    log "  $line"
    ROWS+=("$line")

    if [ -n "$level" ]; then
        ALERTS+=("$icon \`$domain\` 剩 *${days}* 天")
        [ "$level" = "CRIT" ] && exit_code=3
        [ "$level" = "ERR" ] && exit_code=2
    fi

    if [ "$days" -lt "$worst" ] 2>/dev/null; then
        worst=$days
        worst_domain=$domain
    fi
done

# ====== 發訊息 ======
HOST=$(hostname)

build_msg() {
    local title="$1"
    local subtitle="$2"
    {
        echo "$title"
        echo "$subtitle"
        echo ""
        echo '```'
        printf '%s\n' "${ROWS[@]}"
        echo '```'
    }
}

if [ "${#ALERTS[@]}" -gt 0 ]; then
    alert_lines=$(printf '%s\n' "${ALERTS[@]}")
    msg=$(build_msg "🔔 *SSL 證書告警* ($HOST)" "$alert_lines")
    tg_send "$msg"
    log "📤 已發告警（${#ALERTS[@]} 條）"
elif [ "$MODE" = "report" ]; then
    msg=$(build_msg "📊 *SSL 證書日報* ($HOST)" "共 ${#certs[@]} 張，全部健康，最近到期：$worst_domain（剩 $worst 天）")
    tg_send "$msg"
    log "📤 已發每日報告"
else
    log "✓ 全部證書健康，最早到期 $worst_domain（$worst 天）"
fi

log "===== SSL 監控結束（exit $exit_code）====="
exit $exit_code
