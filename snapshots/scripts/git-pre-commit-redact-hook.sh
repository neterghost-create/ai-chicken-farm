#!/bin/bash
# pre-commit: 拒绝把 ai-chicken-farm 真实生产域名 / 凭证 commit 进来.
# 即使 sync-to-github.sh 没用, 在 git 网页直接编辑或者别的工具误传时, 这层兜底.

set -e

SENSITIVE_PATTERNS=(
    "neterghost\.duckdns\.org"
    "oneapi-neterghost"
    "webai-neterghost"
)

# 白名单: 这些文件本身就是脱敏工具, 必须包含真实域名作为映射源.
# 加一个新文件到豁免列表前, 想清楚是不是真的必要.
EXEMPT_FILES=(
    "snapshots/scripts/sync-to-github.sh"
    "snapshots/scripts/git-pre-commit-redact-hook.sh"
)

is_exempt() {
    local file="$1"
    for ex in "${EXEMPT_FILES[@]}"; do
        [ "$file" = "$ex" ] && return 0
    done
    return 1
}

LEAK=0
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM)

for pat in "${SENSITIVE_PATTERNS[@]}"; do
    for f in $STAGED_FILES; do
        [ -f "$f" ] || continue
        if is_exempt "$f"; then continue; fi
        if HITS=$(git diff --cached "$f" | grep -E "^\+" | grep -vE "^\+\+\+" | grep -nE "$pat" 2>/dev/null); then
            if [ -n "$HITS" ]; then
                echo "❌ pre-commit: $f 含敏感词 '$pat':" >&2
                echo "$HITS" | head -3 | sed 's/^/   /' >&2
                LEAK=1
            fi
        fi
    done
done

if [ $LEAK -eq 1 ]; then
    echo "" >&2
    echo "❌ commit 被拒. 用 /opt/ss-monitor/sync-to-github.sh 自动脱敏后再 commit," >&2
    echo "   或人工修正脱敏字段. 如确认是误报可 git commit --no-verify 跳过." >&2
    exit 1
fi

exit 0
