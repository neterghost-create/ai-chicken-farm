#!/bin/bash
# sync-to-github.sh — 把生产 ss-monitor 改动脱敏后同步到 ai-chicken-farm 公开 repo
#
# 用法:
#   ./sync-to-github.sh "commit message"          # 同步 ss-monitor 4 件套 + auto-commit + push
#   ./sync-to-github.sh --dry-run                 # 只显示会做什么, 不动 git
#   ./sync-to-github.sh --include nginx,cron "msg"  # 额外同步 nginx / cron 等系统配置
#   ./sync-to-github.sh --no-push "msg"           # 同步 + commit, 不 push (人工 review)
#
# 脱敏规则: 只在 repo 副本上改, 不动生产文件.
#
# 安全: push 前会再扫一遍敏感词, 发现 → abort.

set -euo pipefail

REPO_DIR="/tmp/ai-chicken-farm-public"
PROD_SS_DIR="/opt/ss-monitor"

# 脱敏映射 (生产值 → repo 占位符)
declare -A REDACTIONS=(
    ["neterghost.duckdns.org"]="example-root.duckdns.org"
    ["oneapi-neterghost.duckdns.org"]="example-legacy.duckdns.org"
    ["webai-neterghost.duckdns.org"]="example-aux.duckdns.org"
)

# DOMAINS 列表里的裸域名 (cron 脚本) — 单独处理, 因为 'aicf' 在 README 里要保留
declare -A REDACTIONS_DOMAINS_LIST=(
    ["neterghost,oneapi-neterghost,webai-neterghost,aicf"]="example-root,example-legacy,example-aux,example"
    ["conf 裡實際是 neterghost"]="conf 裡實際是 example-root"
)

# 系统配置文件里 'aicf' 也要脱敏成 'example' (nginx server_name / cron 标识等)
declare -A REDACTIONS_SYS_CONFIG=(
    ["aicf.duckdns.org"]="example.duckdns.org"
    ["server_name aicf"]="server_name example"
    ["aicf-uptime"]="example-uptime"
)

# Push 前扫敏感词 (任意一项命中 → abort)
SENSITIVE_PATTERNS=(
    "neterghost"
    "oneapi-neterghost"
    "webai-neterghost"
    # 不扫 'aicf' 因为 README/DEPLOYMENT.md 里要保留
)

# === 参数解析 ===
DRY_RUN=0
NO_PUSH=0
INCLUDE_DIRS="ss-monitor"
COMMIT_MSG=""

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --no-push) NO_PUSH=1; shift ;;
        --include) INCLUDE_DIRS="ss-monitor,$2"; shift 2 ;;
        -h|--help)
            sed -n '2,15p' "$0"; exit 0 ;;
        *)
            COMMIT_MSG="$1"; shift ;;
    esac
done

if [ $DRY_RUN -eq 0 ] && [ -z "$COMMIT_MSG" ]; then
    echo "❌ commit message 必填 (除非 --dry-run)" >&2
    echo "用法: $0 \"commit message\"" >&2
    exit 1
fi

# === Step 0: 准备 repo (拉最新, 防本次冲突) ===
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "❌ $REPO_DIR 不是 git repo" >&2
    exit 1
fi

cd "$REPO_DIR"
echo "=== [1/5] 拉取远端最新 ==="
git fetch origin >/dev/null 2>&1
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [ "$LOCAL" != "$REMOTE" ]; then
    echo "  本地落后远端, 自动 rebase..."
    if ! git pull --rebase origin main 2>&1; then
        echo "❌ rebase 冲突, 手动解后重试" >&2
        exit 1
    fi
fi

# === Step 1: 同步文件 + 脱敏 ===
echo
echo "=== [2/5] 同步生产文件 → repo (脱敏) ==="

sync_one_file() {
    local prod="$1"
    local repo_dst="$2"
    local apply_sys_redactions="${3:-0}"
    local apply_domains_list="${4:-0}"

    if [ ! -f "$prod" ]; then
        echo "  ⚠️ skip: $prod 不存在"
        return
    fi
    mkdir -p "$(dirname "$repo_dst")"
    cp "$prod" "$repo_dst"

    # 应用脱敏
    for orig in "${!REDACTIONS[@]}"; do
        sed -i "s|${orig}|${REDACTIONS[$orig]}|g" "$repo_dst"
    done

    if [ "$apply_domains_list" = "1" ]; then
        for orig in "${!REDACTIONS_DOMAINS_LIST[@]}"; do
            # 用 perl 而非 sed, 避免特殊字符 (逗号, 空格) 转义
            perl -i -pe "s|\Q${orig}\E|${REDACTIONS_DOMAINS_LIST[$orig]}|g" "$repo_dst"
        done
    fi

    if [ "$apply_sys_redactions" = "1" ]; then
        for orig in "${!REDACTIONS_SYS_CONFIG[@]}"; do
            sed -i "s|${orig}|${REDACTIONS_SYS_CONFIG[$orig]}|g" "$repo_dst"
        done
    fi

    echo "  ✓ ${repo_dst#$REPO_DIR/}"
}

# ss-monitor 4 件套
if [[ ",$INCLUDE_DIRS," == *",ss-monitor,"* ]]; then
    for f in api.py app.js app.css index.html; do
        sync_one_file "$PROD_SS_DIR/$f" "$REPO_DIR/snapshots/ss-monitor/$f"
    done
fi

# nginx (系统级 → apply_sys_redactions=1)
if [[ ",$INCLUDE_DIRS," == *",nginx,"* ]]; then
    for f in /etc/nginx/sites-enabled/*; do
        name=$(basename "$f")
        # 只同步已经在 repo 里有的文件 (避免传新发现的 vhost)
        if [ -f "$REPO_DIR/snapshots/nginx/$name" ]; then
            sync_one_file "$f" "$REPO_DIR/snapshots/nginx/$name" 1
        fi
    done
fi

# cron / duck.sh (系统级 + DOMAINS 列表)
if [[ ",$INCLUDE_DIRS," == *",cron,"* ]]; then
    [ -f /opt/duckdns/duck.sh ] && sync_one_file /opt/duckdns/duck.sh "$REPO_DIR/snapshots/cron/duck.sh" 1 1
fi

# === Step 2: diff ===
echo
echo "=== [3/5] 改动 diff ==="
cd "$REPO_DIR"
git diff --stat
echo

# === Step 3: 敏感词扫描 ===
echo "=== [4/5] 推送前敏感词扫描 ==="
LEAK_FOUND=0
for pat in "${SENSITIVE_PATTERNS[@]}"; do
    # 只扫 staged + working tree 的改动文件, 不扫历史
    HITS=$(git diff --cached --name-only; git diff --name-only) 
    HITS=$(echo "$HITS" | sort -u)
    for f in $HITS; do
        [ -f "$f" ] || continue
        if grep -nE "$pat" "$f" 2>/dev/null | grep -v "^[^:]*:[0-9]*:.*<!--.*REDACT-EXEMPT" | head -3 | grep -q .; then
            echo "  ❌ $f 含敏感词 '$pat':"
            grep -nE "$pat" "$f" | head -3 | sed 's/^/      /'
            LEAK_FOUND=1
        fi
    done
done

if [ $LEAK_FOUND -eq 1 ]; then
    echo
    echo "❌ 检测到敏感词泄漏, 中止 push. 请检查脱敏映射是否覆盖所有字段." >&2
    echo "   (如确认是误报, 可在该行尾加 <!-- REDACT-EXEMPT --> 注释豁免)" >&2
    exit 2
fi
echo "  ✓ 无敏感词"

# === Step 4: commit + push ===
if [ $DRY_RUN -eq 1 ]; then
    echo
    echo "=== [5/5] DRY_RUN — 不 commit, 撤销 working tree 改动 ==="
    git checkout -- .
    exit 0
fi

if git diff --quiet; then
    echo
    echo "  无改动, 跳过 commit"
    exit 0
fi

echo
echo "=== [5/5] commit + push ==="
git add -A
git commit -m "$COMMIT_MSG"

if [ $NO_PUSH -eq 1 ]; then
    echo "  ✓ 已 commit, 未 push (--no-push)"
    git log -1 --oneline
    exit 0
fi

git push origin main
echo
echo "✓ 完成"
git log -1 --oneline
