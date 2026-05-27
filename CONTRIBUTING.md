# 貢獻指南 / Contributing Guide

> 中文 + English bilingual. 中文在前, English follows.

歡迎為 AI 養雞場貢獻！本項目是個人興趣 + 朋友自用性質, 接受 issue / PR / 翻譯 / 文檔修正。
Thanks for considering a contribution! This is a personal hobby project shared under MIT.

---

## 提 Issue 之前 / Before Filing an Issue

### 中文

1. **先讀 [DEPLOYMENT.md](DEPLOYMENT.md) §13 故障排查 cheatsheet** — 9 個常見場景幾乎涵蓋了所有部署問題
2. **搜一下現有 issue** — 你的問題很可能已經有人問過
3. 如果是部署過程的問題, 請先確認你按照 §11 七個 Phase 完整走過
4. 演示頁掛了 ≠ 項目掛了 — 演示是維護者本人的單機實例, 偶爾會維護重啟

### English

1. **Read [DEPLOYMENT.md](DEPLOYMENT.md) §13 (troubleshooting cheatsheet)** first — the 9 listed scenarios cover almost every deployment problem
2. **Search existing issues** — your question may already be answered
3. For deployment problems, confirm you have completed all seven phases in §11
4. The live demo going down ≠ project broken — it is one person's box and occasionally gets restarted

---

## Issue 類型 / Issue Categories

| 模板 | 用途 |
|---|---|
| 🐛 Bug Report | 部署/運行時遇到具體錯誤 (附日誌 + 復現步驟) |
| ✨ Feature Request | 新功能 / 新訂閱格式 / 新發現源 |
| ❓ Question | 用法疑問 (先看 DEPLOYMENT.md 再來) |

---

## Pull Request 流程 / PR Workflow

```bash
# 1. Fork → clone → create branch
git clone git@github.com:<your-username>/ai-chicken-farm.git
cd ai-chicken-farm
git checkout -b feat/your-feature

# 2. Make changes, follow style below

# 3. Run local checks before pushing
python3 -m py_compile snapshots/scripts/*.py    # Python 語法
bash -n snapshots/cron/*.sh                     # Bash 語法
python3 -c "import yaml; list(yaml.safe_load_all(open('snapshots/scripts/discovery-config.yaml')))"

# 4. Push → open PR against main
git push -u origin feat/your-feature
gh pr create --base main
```

CI 會自動跑 (見 `.github/workflows/ci.yml`):
- Python `py_compile` + pyflakes (warn-only)
- `bash -n` + ShellCheck (warn-only)
- YAML 解析 + SQLite schema 校驗
- Markdown 內部連結檢查
- Secret 洩漏掃描 (ghp_/sk-/TG bot token 等)

---

## 改動類型對應規則 / Change-Type Specific Rules

### 改評分規則 / Changing Scoring Logic

**必讀**: [DEPLOYMENT.md §17.1](DEPLOYMENT.md) — v2.3 設計理由
**模擬**: 改完先跑 `dryrun-v2.3.py`, 看部署後第一輪會立即拉黑多少源 (>10% 算雪崩, 必須調阈值再 PR)
**對齊**: 任何阈值改動需同步 4 個位置:
- `convert-formats.py` 頂部常量
- `api.py` `/api/free-pool/sources` 返回 `kill_threshold_*`
- `index.html` srcKillThreshold 默認值
- `app.js` 顯示文本

### 加新訂閱發現源 / Adding a Discovery Source

```yaml
# 編輯 snapshots/scripts/discovery-config.yaml
awesome_readme:
  - key: <owner>/<repo>
    url: https://raw.githubusercontent.com/<owner>/<repo>/main/README.md
    priority: 60     # 數字越小越早扫
```

PR 描述需附:
- 為什麼選這個源 (品質 / 活躍度)
- 用 `discover-airports.py --dry-run --only awesome_readme` 跑過, 候選/通過數量

### 改前端 / Frontend Changes

**拆分原則** (DEPLOYMENT §7.1):
- HTML/CSS/JS 三文件分離
- 無 inline `<script>` / `<style>`
- 改外置文件不需要重啟 ss-monitor.service
- 改 `api.py` 才需要重啟

**i18n 加新文本**: 必須三個字典 (zh-Hant / zh-Hans / EN) 同時加 key, 不允許單語

**安全**: 用戶數據進 `innerHTML` 必須走 `esc()`, URL 走 `safeUrl()`

### 改 cron / Modifying cron

**必讀**: [DEPLOYMENT.md §9.4](DEPLOYMENT.md) — 5 條隱含時序假設

絕對不要破壞:
1. subs-check 6h 一輪 (04/10/16/22) ↔ source-fetcher 跟著跑
2. 04:00 sync-lza6 → reload subs-check
3. convert-formats 在 subs-check 完成後才有 all.yaml
4. discover-airports 02:00 在 sync-lza6 04:00 之前
5. 04:00-04:15 dpkg 鎖窗口避開

### 翻譯 / Translation

特別歡迎 `DEPLOYMENT.en.md` 全文英譯 PR (74 KB / 20 章)。建議流程:
1. 開 issue 標記 "i18n" 認領章節 (避免重複勞動)
2. 章節對齊 (章標題 + 編號保持一致)
3. 代碼塊 / shell 命令保留原樣不翻譯
4. 術語表參考 DEPLOYMENT §19.7 「用語對照英中速查」

---

## 命名 / 風格 / Style

- **Python**: 4 空格縮進, snake_case, 函數頂部 docstring 簡述職責
- **Bash**: `set -uo pipefail` 開頭, 函數用 lowercase_with_underscore
- **YAML**: 2 空格縮進, 字串不加引號除非必要
- **Markdown**: 中英文之間留空格 (`AI 養雞場` 而不是 `AI養雞場`)
- **Commit 訊息**: 短句 + 動詞開頭, 中英文皆可 (`Add X` / `Fix Y` / `修復 Z`)

---

## 不接受的 PR / What We Won't Merge

- 加任何商業化 / 付費訂閱功能 (本項目限個人 + 朋友用)
- 加自動爬 Telegram 頻道內容的代碼 (法律灰色)
- 訂閱輸出格式裡內嵌追蹤腳本 / 廣告
- 評分機制改成「給特定源加白」(破壞中立性)
- 任何讓 nginx vhost 暴露 admin 接口給公網的改動
- 帶有真實 token / 真實域名 / 真實 IP 的代碼 (被 secret-scan 自動攔)

---

## 行為準則 / Code of Conduct

對所有貢獻者保持友善, 不容忍人身攻擊 / 騷擾 / 歧視。
Be respectful. No personal attacks, harassment, or discrimination.

---

## 聯絡 / Contact

- GitHub Issues: 主要溝通渠道
- Maintainer 不一定第一時間回, 個人項目, 業餘維護

謝謝! / Thanks!
