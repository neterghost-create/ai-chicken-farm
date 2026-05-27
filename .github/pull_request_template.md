<!--
感謝提交 PR! / Thanks for opening a PR!
請填寫下面所有部分。/ Please fill out all sections below.
-->

## 摘要 / Summary

<!-- 一兩句話說清楚這個 PR 做什麼 / 1-2 sentences describing this PR -->

## 改動類型 / Type of Change

- [ ] 🐛 Bug fix (修復現有 bug)
- [ ] ✨ New feature (新功能)
- [ ] 📝 Documentation (僅文檔)
- [ ] 🎨 UI / 前端 (改 ss-monitor HTML/CSS/JS)
- [ ] ⚙️ 評分規則 (改 v2.3 阈值或邏輯)
- [ ] 🐛 覓食 (改 discover-airports 過濾或源)
- [ ] 🔧 Infrastructure (CI / cron / nginx / systemd)
- [ ] 🌐 i18n / 翻譯
- [ ] 💥 Breaking change (現有部署需要遷移)

## 改動清單 / What changed?

<!-- 列改了哪些文件、為什麼這樣改 -->

-
-
-

## 相關 issue / Related issue

<!-- e.g. Fixes #12, Closes #34 -->

## 驗證 / Verification

<!-- 改動類型對應的驗證步驟, 參考 CONTRIBUTING.md -->

- [ ] 本地跑過 `python3 -m py_compile snapshots/scripts/*.py` 無錯
- [ ] 本地跑過 `bash -n snapshots/cron/*.sh` 無錯
- [ ] 修改評分規則的話: 跑過 `dryrun-v2.3.py`, 雪崩 < 10%
- [ ] 修改前端的話: i18n 三字典都加了 key (zh-Hant / zh-Hans / EN)
- [ ] 修改 cron 的話: 不破壞 DEPLOYMENT.md §9.4 五條時序假設
- [ ] 改動已對齊到所有相關位置 (api.py / index.html / app.js / 文檔)

## 截圖 / Screenshots

<!-- UI 改動請貼前後對比截圖 -->

## 安全自查 / Security checklist

- [ ] 沒有提交真實 token / 域名 / IP / 私鑰
- [ ] 用戶輸入進 innerHTML 都有 esc()
- [ ] 用戶 URL 都有 safeUrl()
- [ ] 沒有引入新的外部 CDN / 第三方腳本
- [ ] CI 的 secret-scan job 全綠

## 其他說明 / Additional notes

<!-- 任何想讓 reviewer 知道的內容 -->
