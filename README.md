# AI 養雞場 (AI Chicken Farm)

> 在小内存 VPS 上自動發現 + 清洗 + 評分 + 展示公益免費代理節點，給朋友提供穩定訂閱

[繁體中文](README.md) · [English](README.en.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux-blue.svg)]()
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-green.svg)]()
[![Release](https://img.shields.io/github/v/release/neterghost-create/ai-chicken-farm?label=release&color=orange)](https://github.com/neterghost-create/ai-chicken-farm/releases/latest)
[![Last Commit](https://img.shields.io/github/last-commit/neterghost-create/ai-chicken-farm?color=informational)](https://github.com/neterghost-create/ai-chicken-farm/commits/main)
[![Stars](https://img.shields.io/github/stars/neterghost-create/ai-chicken-farm?style=social)](https://github.com/neterghost-create/ai-chicken-farm/stargazers)
[![Live Demo](https://img.shields.io/badge/Live%20Demo-aicf.duckdns.org-success?logo=googlechrome&logoColor=white)](https://aicf.duckdns.org/ss-monitor/)

## 🌐 在線演示

**[https://aicf.duckdns.org/ss-monitor/](https://aicf.duckdns.org/ss-monitor/)**

這是維護者本人的生產實例，可以直接看 5 個卡片 + 雞主題 UI + 三檔限制 + 繁/簡/EN 切換的實際效果。

> 演示頁公開展示節點統計 / 評分趨勢 / 覓食隊列 / 飼料廠評分等，但**訂閱檔案需要 token 鑑權**（不公開）。如果你想用這套訂閱，請走項目部署一份自己的；這個演示站只給朋友用。

## 這是什麼

AI 養雞場是一套運行在單台 Linux VPS 上的免費節點池系統：

- **覓食 🐛**：自動從 awesome README + GitHub Topics 發現新訂閱源
- **飼料廠 🏭**：對 200+ 訂閱源做評分 (v2.3 滿分起步單向減分機制)
- **雞舍 🏠**：[subs-check](https://github.com/beck-8/subs-check) 主二進制做測活/測速
- **蛋池 🥚**：清洗後的節點自動輸出 4 種訂閱格式 (Clash / V2Ray / Base64 / 老 Clash 兼容)
- **飼料 🌽**：節點質量評分 + 3 級黑名單機制
- **養雞場控制台**：Flask + 純 HTML/CSS/JS 的監控頁，9 個安全頭 + 繁/簡/EN 三語

每個組件嚴格分離，可以獨立升級回滾。詳見 [DEPLOYMENT.md](DEPLOYMENT.md) (74 KB / 20 章 / 2189 行)。

## 快速開始

```bash
# 1. 克隆
git clone https://github.com/<your-username>/ai-chicken-farm.git
cd ai-chicken-farm

# 2. 看主文檔的部署章節
less DEPLOYMENT.md     # 跳到 §11 「1:1 部署步驟 (從零拉起)」

# 3. 按 7 個 Phase 走
#    Phase 0: 系統準備 (apt + pip)
#    Phase 1: DuckDNS + Telegram + 訂閱 token
#    Phase 2: subs-check 主二進制 + 配置
#    Phase 3: Python 維護腳本 + DB schema
#    Phase 4: ss-monitor 展示頁
#    Phase 5: nginx + TLS
#    Phase 6: cron + 監控
#    Phase 7: 完整自檢
```

預計時間：1-2 小時可拉起新環境。

## 適合誰

- 有閒置 VPS (1.8 GB RAM 級別即可) 想搞個免費節點池給朋友用
- 想學習 Python + SQLite + nginx + systemd + cron 一條龍實戰部署
- 對節點質量評分機制感興趣 (參考 [snapshots/scripts/SCORING_RULES_v2.md](snapshots/scripts/SCORING_RULES_v2.md) 619 行決策追溯)

## 不適合誰

- 想要一鍵安裝腳本的：本項目強調「按文檔理解再部署」，沒有 install.sh
- 想直接用作者訂閱的：本項目是部署框架，節點源來自公益機場 awesome 列表
- 對中文文檔不友好的：主文檔是繁體中文 (含繁/簡/EN 切換)

## 文件結構

```
ai-chicken-farm/
├── README.md                  # 項目介紹 (本文件, 繁體中文)
├── README.en.md               # Project introduction (English)
├── DEPLOYMENT.md              # 詳細部署文檔 (74 KB, 20 章)
├── CONTRIBUTING.md            # 貢獻指南 (中英雙語)
├── LICENSE                    # MIT
├── .github/                   # CI / Issue 模板 / PR 模板
├── .gitignore                 # 排除 *.db, *.bak, *.log, 真實憑證
└── snapshots/                 # 1:1 復原素材 (40 文件, 600 KB)
    ├── scripts/               # 11 個 Python 維護腳本 + DB schema + 配置
    ├── ss-monitor/            # api.py + index.html + app.css + app.js
    ├── nginx/                 # 兩個 vhost + 3 個 snippets
    ├── systemd/               # 兩個 .service + drop-in
    └── cron/                  # 5 個 .sh + crontab snapshot
```

## 核心特性

| 特性 | 說明 |
|---|---|
| 評分 v2.3 | 滿分 100 起步，單向減分；4 個源級 + 2 個節點級拉黑觸發點 |
| 6 層過濾 | 域名/IOC/路徑/響應/內容簽名/跨源去重，配合 SSRF socket-level 硬隔離 |
| 三語 i18n | 134 keys × 繁/簡/EN，數據驅動切換，無 inline JS/CSS |
| 9 安全頭 | CSP / HSTS / X-Frame / X-Content-Type / Referrer / Permissions / COOP / CORP / X-XSS |
| Token 鑑權 | 32 hex 訂閱 token，path-based 鑑權，可在線輪換 |
| 三檔限制 | 表格 5/mid/全部 三檔切換，localStorage 持久化 |
| 雞主題 UI | emoji 配世界觀 (🥚🌽🏭🐛)，敏感信息打碼 |
| 自動發現 | 覓食 cron 02:00，10 awesome + 6 topic + 6 層過濾 |
| 完整回滾 | 備份標籤約定，DB + 腳本 + nginx 一致時間戳 |

## 系統要求

- **OS**: Debian 12 / Ubuntu 22.04+ LTS
- **RAM**: 最低 1 GB，推薦 2 GB
- **磁盤**: 最低 5 GB
- **網絡**: 公網 IP (CGNAT 場景見 README §14)
- **域名**: DuckDNS 免費域名即可

## 性能基線

- 80 源/輪約 5 小時 (1.8 GB RAM VPS 實測)
- ss-monitor 內存：24.8M / 50M (MemoryMax)
- subs-check 內存：80-320M / 512M
- 訂閱檔案大小：~80 KB (~600 節點 Clash YAML)

## 貢獻

歡迎 issue 和 PR。請先讀 README 對應章節：

- 改評分規則 → §17.1 + 跑 `dryrun-v2.3.py` 模擬
- 改前端 → §7 (拆分原則：HTML/CSS/JS 三文件，無 inline)
- 加新覓食源 → §6 + 改 `discovery-config.yaml`
- 改 cron → §9.4 (5 條隱含時序假設)

## 鳴謝

- [beck-8/subs-check](https://github.com/beck-8/subs-check) — 核心測活測速二進制
- [lza6/free-VPN](https://github.com/lza6/free-VPN) 等公益機場聚合 README
- DuckDNS / Let's Encrypt / Cloudflare 等公益基礎設施

## 許可

MIT License — see [LICENSE](LICENSE)

---

> 本項目為個人學習 + 朋友分享性質，請勿用於商業用途。
> 節點來源於公益機場聚合，質量無保證。
