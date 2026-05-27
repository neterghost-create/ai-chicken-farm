# AI 養雞場 (AI Chicken Farm) — 完整部署文檔

> **項目代號**: AI 養雞場 (前身：免費節點池清洗系統 / subs-check 公益機場節點清洗)
> **部署狀態**: 生產運行中 (2026-05-27)
> **主機**: 單台 Linux VPS (1.8GB RAM 級別可跑)
> **目標**: 在小内存 VPS 上自動發現 + 清洗 + 評分 + 展示公益免費節點，給朋友提供穩定訂閱
> **域名**: `https://example.duckdns.org/` (主) + `https://example-legacy.duckdns.org/ss-monitor/` (兼容舊鏈)
> **可讀復原**: 全部運行時素材在 `./snapshots/` 目錄，可按本文檔 1:1 拉起新環境

---

## 一、世界觀 / 主題映射

養雞場用語 ↔ 真實組件對照表 (前端展示和文檔均沿用此命名，後端 class/id/JSON 字段保留英文)：

| 養雞場術語 | emoji | 實際含義 | 對應組件 |
|---|---|---|---|
| 雞舍 | 🏠 | VPS 主機 | Linux 伺服器 |
| 雞霸王 | 👑 | 主代理出口 (用戶自用 SS) | shadowsocks-rust + ss-monitor |
| 蛋池 | 🥚 | 已清洗的節點池 (subs-check 主出口) | `/sub/free/<token>/all.yaml` 等 |
| 飼料 | 🌽 | 節點質量評分 (節點級) | `nodes_history.quality_score` |
| 飼料廠 | 🏭 | 訂閱源質量評分 (源級) | `sources.score` + status 三態 |
| 覓食 | 🐛 | 自動發現新源 (discover-airports) | awesome README + GitHub Topics |
| 咕咕暗號 | 🔐 | 訂閱 token (32 hex) | `free-pool.conf` |
| 飼料配方 | 📋 | 評分機制 v2.3 規則 | `SCORING_RULES_v2.md` |

每次出現「雞」相關術語請對應到上表。

---

## 二、系統總覽

### 2.1 架構圖

```
┌────────────────────────────────────────────────────────────────────┐
│                         AI 養雞場系統 (單機)                         │
└────────────────────────────────────────────────────────────────────┘

   [覓食 — 自動發現]              [飼料廠 — 源管理]
   discover-airports.py    →     sync-lza6.py (狀態機 + 選源)
   awesome / GitHub Topic         │
        ↓ INSERT 新 source         ↓ 寫 sub-urls.txt
   ┌─────────────────────────────────┐
   │   source-scores.db (源級評分)    │
   │   ├─ sources (三態: c/w/b)       │
   │   ├─ source_node_map             │
   │   ├─ source_quality_history      │
   │   ├─ discovery_state (覓食進度)  │
   │   └─ source_audits (審計 log)    │
   └─────────────────────────────────┘
        ↓
   ┌──────────────────┐
   │  subs-check (Go) │  ← /opt/subs-check/subs-check, systemd 自跑, 每 6h 一輪
   └──────────────────┘
        ↓ 寫 all.yaml (僅 Clash 格式)
   ┌────────────────────────────────────────────────────────────┐
   │ convert-formats.py  (cron */30, idempotent)                 │
   │  - all.yaml → v2ray.txt + base64.txt + all-config.yaml      │
   │  - 節點/源評分: 信號 B (出現/速度) 累加                      │
   │  - 寫 history.db: rounds + nodes_history                    │
   │  - 級聯觸發 notify-telegram.py                              │
   └────────────────────────────────────────────────────────────┘
        ↓
   ┌─────────────────────────────────┐
   │   history.db (節點級)            │
   │   ├─ rounds (每輪摘要)           │
   │   └─ nodes_history (canonical)   │
   └─────────────────────────────────┘
        ↓                                 ↓
   incremental-check.py             ss-monitor (Flask :5000)
   (cron :15, 探活 +/-)              api.py + index.html + app.js
                                          ↓
                                     nginx 443 (aicf + oneapi)
                                          ↓
                                     瀏覽器/朋友訂閱
```

### 2.2 核心數據

| 指標 | 當前值 (2026-05-27) | 上限 |
|---|---|---|
| sources 表行數 | 223 | 軟限 (1.8GB RAM 跑 80 源/輪) |
| 活躍節點 (nodes_history) | 2319 (黑名單外) | 50,000 撞 swap |
| rounds 表 | 7 輪 | 無 (永久保留) |
| ss-monitor 內存 | 24.8M / 50M (MemoryMax) | 50M 硬上限 |
| subs-check 內存 | 80-320M / 512M | 512M MemoryMax |
| 訂閱檔案大小 | ~80KB (all.yaml ~600 節點) | - |

### 2.3 服務矩陣

| 服務 | 類型 | 監聽 | 自啟 | 用途 |
|---|---|---|---|---|
| `subs-check.service` | systemd, Go 二進制 | 127.0.0.1:8199 | ✓ | 節點測活/測速主循環 |
| `ss-monitor.service` | systemd, Python Flask | 127.0.0.1:5000 | ✓ | 監控 API |
| `nginx.service` | systemd | 80/443 | ✓ | 反向代理 + 訂閱分發 |
| `shadowsocks-rust.service` | systemd | 2052 (對外) | ✓ | 雞霸王本人 (用戶自用代理) |
| (cron jobs ×11) | crond | - | - | 同步/評分/發現/通知 |

---

## 三、文件總清單 (1:1 復原參照)

### 3.1 部署目錄結構

```
/opt/subs-check/                       ← 節點清洗根
├── subs-check                         (Go 二進制 ~85MB)
├── config/
│   ├── config.yaml                    (subs-check 配置)
│   ├── config.yaml.default            (默認備份)
│   ├── sub-urls.txt                   (sync-lza6 寫, 別手改)
│   └── sub-urls-whitelist.txt         (人工固定保留)
├── output/                            (subs-check 跑時的臨時)
├── logs/                              (subs-check 自身日誌)
└── scripts/                           ★ 全部 Python 維護腳本
    ├── sync-lza6.py                   (cron 04:00 daily)
    ├── convert-formats.py             (cron */30, 主管道)
    ├── source-fetcher.py              (cron 5 4,10,16,22)
    ├── incremental-check.py           (cron :15 hourly)
    ├── notify-telegram.py             (cron :00 hourly 兜底)
    ├── weekly-recovery.py             (cron 0 3 * * 0)
    ├── source-quality-history-cleanup.py (cron 33 4 daily)
    ├── discover-airports.py           (cron 02:00 daily, 覓食)
    ├── audit-cleanup.py               (cron 30 3 * * 0)
    ├── dryrun-v2.3.py                 (手動跑, 評分規則模擬)
    ├── discovery-config.yaml          (覓食源配置)
    ├── ioc-list.txt                   (惡意 substring 黑名單)
    ├── free-pool.conf                 (TOKEN + DOMAIN, mode 600)
    ├── SCORING_RULES_v2.md            (評分機制 v2.3 終版規則)
    ├── source-scores.db               (源級 SQLite)
    └── history.db                     (節點級 SQLite)

/opt/ss-monitor/                       ← 展示頁根
├── api.py                             (Flask :5000)
├── index.html                         (HTML 骨架 + i18n 標記)
├── app.css                            (外置 CSS, 24KB)
├── app.js                             (外置 JS, 84KB, 全部邏輯)
└── sub/
    └── free/
        ├── stats.json                 (公開: 節點統計)
        ├── nodes.json                 (公開: 節點列表脫敏)
        ├── diff.json                  (公開: 與上輪 diff)
        ├── history.json               (公開: 最近 20 輪趨勢)
        └── <TOKEN>/                   (token 子目錄, mode 750)
            ├── all.yaml               (Clash/Mihomo 格式, subs-check 直寫)
            ├── all-config.yaml        (老 Clash 兼容白名單過濾)
            ├── v2ray.txt              (vmess/vless/ss 一行一條)
            └── base64.txt             (base64(v2ray.txt))

/etc/nginx/sites-available/
├── aicf                               (新主域名 vhost)
├── one-api                            (舊域名兼容 vhost)
├── openclaw-domain                    (其他項目)
└── webai                              (其他項目)

/etc/nginx/snippets/
├── acme-challenge.conf
├── ssl-hardening.conf
├── security-common.conf               (9 安全頭通用片段)
└── openclaw-common.conf

/etc/systemd/system/
├── ss-monitor.service
├── subs-check.service
└── subs-check.service.d/limits.conf   (drop-in: MemoryMax/CPUQuota)

/usr/local/bin/
├── aicf-uptime-monitor.sh             (cron */30)
├── ssl-monitor.sh                     (cron 35 4 daily)
└── (openclaw-uptime-monitor.sh)       (其他項目共用 lib)

/usr/local/lib/
└── uptime-common.sh                   (上面兩個 .sh 共用函數庫)

/etc/letsencrypt/
├── live/example.duckdns.org/             (主證書)
├── live/example-legacy.duckdns.org/ (舊證書)
└── renewal-hooks/deploy/nginx-reload.sh  (證書續期 → nginx -t + reload)

/etc/duckdns/duckdns.conf              (token="...", mode 600)
/opt/duckdns/duck.sh                   (cron */5, 4 域名一次推)

/etc/telegram-bot.conf                 (TELEGRAM_BOT_TOKEN + CHAT_ID, mode 600)

/var/log/
├── subs-check-sync.log
├── subs-check-convert.log
├── subs-check-incremental.log
├── subs-check-notify.log
├── subs-check-fetcher.log
├── subs-check-recovery.log
├── subs-check-cleanup.log
├── subs-check-discover.log
├── subs-check-audit-cleanup.log
├── aicf-uptime-monitor.log
├── ssl-monitor.log
├── duckdns-update.log
└── (logrotate 配置: /etc/logrotate.d/subs-check)
```

### 3.2 配置文件權限

| 路徑 | 權限 | 所有者 | 為什麼 |
|---|---|---|---|
| `/opt/subs-check/scripts/free-pool.conf` | 600 | root | 含訂閱 token |
| `/etc/telegram-bot.conf` | 600 | root | 含 bot token |
| `/etc/duckdns/duckdns.conf` | 600 | root | 含 DuckDNS token |
| `/opt/ss-monitor/sub/free/<TOKEN>/` | 750 | root | 訂閱檔案目錄 |
| `/opt/ss-monitor/sub/free/*.json` | 644 | root | 公開監控 JSON |
| `/opt/subs-check/scripts/*.py` | 755 | root | 可執行 |
| `/opt/subs-check/scripts/*.db` | 644 | root | SQLite 文件 |

---

## 四、外部依賴 / 一次性準備

### 4.1 操作系統 + 包

```bash
# Debian 12 / Ubuntu 22.04 LTS 為基準
apt update
apt install -y \
    python3 python3-pip python3-yaml \
    sqlite3 \
    nginx \
    curl wget jq \
    cron logrotate rsyslog \
    certbot python3-certbot-nginx
```

### 4.2 Python 套件 (system-wide)

```bash
# 注意 Debian 12 用 --break-system-packages, 因為 PEP 668
pip3 install --break-system-packages \
    flask \
    pyyaml \
    requests
```

### 4.3 域名 + DNS

- 主域名: `example.duckdns.org` (DuckDNS 免費域名)
- 兼容: `example-legacy.duckdns.org`
- A 記錄指向 VPS 公網 IP (CGNAT 場景見「七、CGNAT 兼容性」)

DuckDNS 註冊 → 拿到 token → 寫到 `/etc/duckdns/duckdns.conf`：

```bash
mkdir -p /etc/duckdns
cat > /etc/duckdns/duckdns.conf <<'EOF'
token="<your-duckdns-token>"
EOF
chmod 600 /etc/duckdns/duckdns.conf
```

### 4.4 Telegram Bot

1. `@BotFather` 創建 bot, 拿到 token
2. 私聊 bot 一次, 訪問 `https://api.telegram.org/bot<TOKEN>/getUpdates` 取 chat_id
3. 寫到 `/etc/telegram-bot.conf`：

```bash
cat > /etc/telegram-bot.conf <<'EOF'
TELEGRAM_BOT_TOKEN=<your-bot-token>
TELEGRAM_CHAT_ID=<your-chat-id>
EOF
chmod 600 /etc/telegram-bot.conf
```

### 4.5 訂閱 token

```bash
# 32 位 hex, 用於訂閱 URL 路徑鑑權
python3 -c "import secrets; print(secrets.token_hex(16))"
# 拷貝結果到 free-pool.conf 的 TOKEN= 行
```

---


---

## 五、節點清洗 / 評分系統 (subs-check + 11 個 Python 維護腳本)

> 這是 AI 養雞場的核心。設計哲學參考 `snapshots/scripts/SCORING_RULES_v2.md` (619 行終版)，本文檔只給工程實裝視圖。

### 5.1 subs-check 主二進制

**作用**: Go 寫的節點測活/測速主循環，把若干訂閱源 (sub-urls.txt) 拉下來，去重 + 探活 + 測速 + 寫回 Clash YAML。

**安裝**:
```bash
mkdir -p /opt/subs-check && cd /opt/subs-check
timeout 120 curl -L -o /tmp/subs-check.tar.gz \
  https://github.com/beck-8/subs-check/releases/latest/download/subs-check_Linux_x86_64.tar.gz
gzip -t /tmp/subs-check.tar.gz   # 必須校驗完整性 (出過問題)
tar xzf /tmp/subs-check.tar.gz
chmod +x subs-check

# 跑一次自動生成 config
timeout 5 ./subs-check 2>&1 | head -10
cp config/config.yaml config/config.yaml.default
```

**關鍵配置 (Python 安全改, 不用 sed)**:
```python
import yaml
c = yaml.safe_load(open('/opt/subs-check/config/config.yaml'))
c['concurrent']         = 15
c['speed-concurrent']   = 6
c['media-concurrent']   = 6
c['sub-urls-concurrent']= 8
c['timeout']            = 3000        # ms
c['listen-port']        = '127.0.0.1:8199'
c['enable-web-ui']      = False
c['sub-store-port']     = ''
c['output-dir']         = '/opt/ss-monitor/sub/free/<TOKEN>'   # ★ 訂閱 token 子目錄
c['check-interval']     = 360         # 6h, 必須大於單輪耗時 (80 源 ~5h)
c['min-speed']          = 512
c['rename-node']        = True
yaml.safe_dump(c, open('/opt/subs-check/config/config.yaml','w'),
               allow_unicode=True, sort_keys=False, width=200)
```

**systemd unit** (`/etc/systemd/system/subs-check.service`):
```ini
[Unit]
Description=Subs Check - 訂閱檢測轉換工具
After=network-online.target
Wants=network-online.target
StartLimitBurst=5
StartLimitIntervalSec=60

[Service]
Type=simple
WorkingDirectory=/opt/subs-check
ExecStart=/opt/subs-check/subs-check
Restart=always
RestartSec=10
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

**資源限制 drop-in** (`/etc/systemd/system/subs-check.service.d/limits.conf`)：
```ini
[Service]
MemoryMax=512M
MemoryHigh=384M
CPUQuota=80%
```

**啟動**:
```bash
systemctl daemon-reload
systemctl enable --now subs-check
journalctl -u subs-check -f
```

### 5.2 評分機制 v2.3 — 核心不變量

> 完整規則: `snapshots/scripts/SCORING_RULES_v2.md`

#### 滿分起步 + 單向減分
- `sources.score` 默認 100, 只減不加 (除 weekly-recovery +5)
- `nodes_history.quality_score` 默認 100, 只減不加 (除信號 ABC 累加)

#### 4 個源級拉黑觸發點

| 觸發 | 條件 | 寫入位置 | 備註 |
|---|---|---|---|
| ① candidate 網絡硬故障 | `consecutive_fails ≥ 3` | sync-lza6 狀態機 | streak |
| ② whitelisted 大量失敗 | `consecutive_fails ≥ 60` | sync-lza6 狀態機 | streak |
| ③ 節點質量連續低 | `consecutive_low_quality ≥ 5` | convert-formats round 切換 | streak |
| ④ 累計低分兜底 | `low_score_total ≥ 15` | convert-formats round 切換 | total (不重置) |

`consecutive_fails` **僅**由網絡硬故障 (拉取失敗 / 0 節點) 累加。節點質量低**只**走 ③ ④。

#### 2 個節點級拉黑觸發點

| 觸發 | 條件 | 寫入位置 |
|---|---|---|
| ① 探活失敗 streak | `consecutive_fails ≥ 4` | incremental-check |
| ② 連續本輪低質 | `consecutive_low_quality_node ≥ 5` | convert-formats round 切換 |

**關鍵**: lq_node 判定**只**在 convert-formats round 切換時由 `apply_lq_node_and_blacklist` 一次性觸發，incremental-check **不能**觸發 (避免 5 小時拉黑)。

#### 黑名單到期完整復活
- score=100, 全部計數器歸零
- 不要「剛出獄又抓」(漏洞 1 修復)

### 5.3 減分常量速查

```python
# 源級 (sync-lza6.py)
SOURCE_FETCH_FAIL_PENALTY    = 15    # 拉取失敗
SOURCE_DEFAULT_SCORE         = 100.0

# 源級 (convert-formats.py)
SOURCE_QUALITY_PENALTY_LOW   = 2     # 節點均分 50-69
SOURCE_QUALITY_PENALTY_MID   = 5     # 30-49
SOURCE_QUALITY_PENALTY_HIGH  = 10    # <30
SOURCE_LOW_SCORE_THRESHOLD   = 30
SOURCE_KILL_AFTER_LOW_ROUNDS = 5     # ③
SOURCE_KILL_AFTER_LOW_TOTAL  = 15    # ④

# 節點級 (convert-formats.py)
NODE_PRESENT_BONUS           = 2
NODE_ABSENT_PENALTY          = 3
NODE_CONSECUTIVE_BONUS       = 3     # consecutive_appearances >= 5
NODE_SPEED_HIGH_BONUS        = 3     # >= 2048 KB/s
NODE_SPEED_LOW_PENALTY       = 3     # 512-1023
NODE_SPEED_VLOW_PENALTY      = 12    # 100-511 (v2.2 加大)
NODE_SPEED_DEAD_PENALTY      = 15    # < 100

# 節點級 (incremental-check.py)
NODE_PROBE_FAIL_PENALTY      = 10
NODE_PROBE_PASS_BONUS        = 3
NODE_FAIL_THRESHOLD          = 4     # ① v2.3: 3 → 4
```

### 5.4 11 個 Python 維護腳本職責

| 腳本 | 觸發 | 職責 | 副作用 |
|---|---|---|---|
| `sync-lza6.py` | cron 04:00 | 抓 lza6/free-VPN README + 狀態機評分 + 寫 sub-urls.txt + 同步 config.yaml + reload subs-check | RW sources |
| `convert-formats.py` | cron */30 | all.yaml → v2ray/base64/all-config + 節點/源評分 + 寫 history.db + 級聯 notify-tg | RW history.db, RW sources, R all.yaml |
| `source-fetcher.py` | cron 5 4,10,16,22 | 抓每個源 → 解析節點 → 寫 source_node_map | RW source_node_map |
| `incremental-check.py` | cron :15 hourly | TCP+TLS 探活 + 節點黑名單 ① | RW nodes_history (不寫 lq_node) |
| `notify-telegram.py` | cron :00 hourly + 級聯 | 推送新一輪 Telegram 摘要 (idempotent) | W rounds.notified |
| `weekly-recovery.py` | cron 0 3 * * 0 | candidate 健康源 score +5 (cap 100) | RW sources |
| `source-quality-history-cleanup.py` | cron 33 4 daily | 清 30 天前 source_quality_history | DEL sqh |
| `discover-airports.py` | cron 02:00 daily | 自動發現新 awesome/topic 源 + 低分審計 | INSERT sources, RW discovery_state, RW source_audits |
| `audit-cleanup.py` | cron 30 3 * * 0 | 清 30 天前 info/warn audit | DEL source_audits |
| `dryrun-v2.3.py` | 手動 | 評分規則模擬器 (歷史回放 + 穩態預測) | 純讀 |

### 5.5 lza6 ETag 短路

`sync-lza6.py` 用 `If-None-Match` 抓 lza6/free-VPN README，304 時:
- 不重新提取 / 不寫入 / 不重啟 subs-check
- ETag 存 `metadata` 表 (key=`lza6_etag`)
- `last_sync_at` 給前端展示

實測 ETag 命中率 ≈ 70% (lza6 一週改 2-3 次)。

### 5.6 80 源輪訓 v3 排序 (饿死防止)

```sql
ORDER BY total_checks ASC,        -- 公平: 測得越少越優先
         score ASC,                -- 同次數下低分先翻身
         consecutive_passes DESC,  -- 同分下長期穩定優先
         first_seen ASC
```

選 80 個給 subs-check 跑。僵屍源由 ④ low_score_total ≥ 15 兜底拉黑，**不靠排序冷處理**。

### 5.7 訂閱 token 鑑權

`/opt/subs-check/scripts/free-pool.conf` (mode 600)：
```
TOKEN=<32-hex-token>
DOMAIN=example.duckdns.org
```

訂閱 URL 模板:
```
https://example.duckdns.org/sub/free/<TOKEN>/all.yaml         (Clash/Mihomo)
https://example.duckdns.org/sub/free/<TOKEN>/all-config.yaml  (老 Clash 兼容)
https://example.duckdns.org/sub/free/<TOKEN>/v2ray.txt        (v2rayN/Qv2ray)
https://example.duckdns.org/sub/free/<TOKEN>/base64.txt       (Shadowrocket)
```

監控 JSON (公開, 無 token)：
```
https://example.duckdns.org/sub/free/{stats|nodes|diff|history}.json
```

**輪換 token 流程**:
1. 生成新 token: `python3 -c "import secrets; print(secrets.token_hex(16))"`
2. 改 `free-pool.conf` 的 `TOKEN=`
3. 改 `subs-check config.yaml` 的 `output-dir` 到新 token 子目錄
4. `systemctl restart subs-check` (寫到新目錄)
5. `python3 /opt/subs-check/scripts/convert-formats.py` (生成衍生)
6. 刪老 token 子目錄: `rm -rf /opt/ss-monitor/sub/free/<OLD_TOKEN>`
7. 通知用戶重新 import 訂閱

---

## 六、自動發現 (覓食) — discover-airports

> 完整規則: `snapshots/scripts/discovery-config.yaml` + `discover-airports.py`

### 6.1 設計哲學

1. **零侵入清理系統**: 只 `INSERT OR IGNORE` 到 sources 表, 永遠不 UPDATE 已有行
2. **審計與發現分離**: source_audits 是 discover 私有表, 清理系統不讀它
3. **score 閾值 80**: `sources.score >= 80` 完全跳過審計 (清理系統說「健康」)
4. **SSRF 硬隔離**: 自定義 `socket.getaddrinfo`, 解析到任何私有/loopback/鏈路本地段直接拒
5. **合併通知**: 單次 cron 跑完, critical 合併成 1 條 Telegram

### 6.2 6 層過濾管線

| 層 | 名稱 | 拒絕條件 | 時機 |
|---|---|---|---|
| L1 | 配置層 | 域名不在白名單 / 在黑名單 / 關鍵字命中 | 候選 URL 一抽到就過 |
| L2 | IOC | URL 含 IOC substring (eval/exec/bash -i) | 緊隨 L1 |
| L3 | 路徑形態 | `.html/.php/.asp` 等明顯非訂閱 | 緊隨 L2 |
| L4 | HTTP 響應 | 非 200 / Content-Type 含 text/html / 截斷 | 實際 GET 後 |
| L5 | 內容簽名 | 協議頭 < 3 / html 占比高 / 高熵無協議頭 | L4 通過後 |
| L6 | 跨源去重 | 已存在 sources 表 | 最後 |

### 6.3 配置 (`discovery-config.yaml`)

```yaml
awesome_readme:
  - {key: lza6/free-VPN, url: ..., priority: 10, note: 現行主源}
  - {key: ripaojiedian/freenode, url: ..., priority: 50}
  - {key: freefq/free, url: ..., priority: 50}
  - {key: aiboboxx/v2rayfree, url: ..., priority: 60}
  - {key: chengaopan/AutoMergePublicNodes, url: ..., priority: 60}
  - {key: mahdibland/ShadowsocksAggregator, url: ..., priority: 60}
  - {key: peasoft/NoMoreWalls, url: ..., priority: 70}
  - {key: mfuu/v2ray, url: ..., priority: 70}
  - {key: ts-sf/fly, url: ..., priority: 80}
  - {key: sinspired/airport, url: ..., priority: 80}

github_topic:
  - {key: topic:free-vpn, query: 'topic:free-vpn pushed:>RECENT_30D', priority: 100}
  - {key: topic:free-proxy, query: ..., priority: 100}
  # ... 共 6 條 query

source_audit:
  enabled: true
  threshold_score: 80
  daily_limit: 10
  re_audit_cooldown_days: 7

security:
  domain_whitelist: [raw.githubusercontent.com, fastly.jsdelivr.net, ...]
  domain_blacklist: [openproxylist.com, git.io]
  keyword_blacklist: [/socks, /http.txt, hideip.me, ...]
  fetch_timeout_sec: 15
  global_timeout_sec: 3000      # 50min
  max_response_bytes: 5242880   # 5MB

budget:
  awesome_readme_per_day: 5
  github_topic_per_day: 2
  source_audit_per_day: 10
  http_concurrent: 3

content:
  protocol_markers_min: 3
  html_ratio_max: 0.05
  entropy_max_no_proto: 7.5

notify:
  enabled: true
  config_file: /opt/subs-check/scripts/free-pool.conf
  merge_critical: true
  min_critical_to_notify: 1
```

### 6.4 IOC 列表設計原則

**只放真實惡意模式**, 不放 SSRF / 私有 IP — SSRF 已由 socket layer 強制保證。

```
✓ 進 IOC: eval(  exec(  shell_exec  __import__  /dev/tcp/  <script  javascript:  data:text/html
✗ 不進 IOC: 10.  192.168.  127.0.0.1   (會誤傷 coldwater-10.yaml / project172)
```

### 6.5 維護命令

```bash
# Bootstrap (從 yaml 灌 discovery_state)
python3 discover-airports.py --bootstrap

# Dry-run (不寫表, 不通知)
python3 discover-airports.py --dry-run

# 只跑某類
python3 discover-airports.py --only awesome_readme
python3 discover-airports.py --only github_topic
python3 discover-airports.py --only source_audit

# 強行跑 (忽略 sync-lza6 鎖)
python3 discover-airports.py --ignore-sync-lock
```

退出碼:
- `0` 正常
- `1` 配置/DB 錯誤
- `2` 全局超時被信號 kill
- `3` 讓路 sync-lza6 退出 (避免搶 DB 鎖)



---

## 七、ss-monitor 展示頁 (養雞場控制台)

> 完整素材: `snapshots/ss-monitor/{api.py, index.html, app.css, app.js}`

### 7.1 文件職責

```
/opt/ss-monitor/
├── api.py     (32KB) - Flask, 8 個 endpoint, 連 source-scores.db / history.db (RO)
├── index.html (28KB) - HTML 骨架 + i18n data-* 標記, 無 inline JS/CSS
├── app.css    (24KB) - 外置 CSS, CSP 'self'
├── app.js     (84KB) - 外置 JS, 全部邏輯, defer 加載
```

**改 HTML/CSS/JS 不需要重啟 ss-monitor.service** (nginx alias 直接讀文件)。
改 `api.py` 才需要 `systemctl restart ss-monitor`。

### 7.2 systemd unit (`/etc/systemd/system/ss-monitor.service`)

```ini
[Unit]
Description=Shadowsocks Monitor API
After=network.target shadowsocks-rust.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ss-monitor
ExecStart=/usr/bin/python3 /opt/ss-monitor/api.py
Restart=on-failure
RestartSec=5s

# 資源限制
MemoryMax=50M
CPUQuota=10%

[Install]
WantedBy=multi-user.target
```

實測穩態 24.8M / 50M, 不會超。

### 7.3 8 個 API endpoint

| 路徑 | 用途 | 緩存 |
|---|---|---|
| `GET /api/vps-status` | 系統 CPU / 內存 / 負載 / 磁盤 | 5s |
| `GET /api/ss-status` | shadowsocks-rust 連接數 / 流量 | 5s |
| `GET /api/free-pool` | 蛋池總覽 (進度條 + 統計 + 訂閱 URL) | 5s |
| `GET /api/free-pool/nodes` | 節點列表 (脫敏 server/port) | 10s |
| `GET /api/free-pool/diff` | 上輪 vs 本輪 diff | 10s |
| `GET /api/free-pool/history` | 最近 20 輪趨勢 | 10s |
| `GET /api/free-pool/quality` | 節點評分排行 | 10s |
| `GET /api/free-pool/sources` | 飼料廠 (源評分) | 10s |
| `GET /api/free-pool/discover` | 覓食隊列 + 審計事件 | 10s |

### 7.4 前端架構 (5 張卡片 + 1 個 hero)

| 卡片 | id | 養雞場名 | 默認 | 數據量 | 三檔 |
|---|---|---|---|---|---|
| Hero | `heroPoolProg` | 雞舍狀態 | 永遠展開 | - | - |
| 雞霸王 | (no id) | 雞霸王 (用戶代理) | 展開 | - | - |
| 蛋池 | `poolCard` | 蛋池 · subs-check | 摺疊 | 597 節點 | 5/100/全部 |
| 覓食 | `discoverCard` | 覓食 (rose 配色) | 摺疊 | 16 隊列 | 5/全部 |
| 飼料 | `qualityCard` | 飼料 · 節點評分 | 摺疊 | 30 排行 | 5/全部 |
| 飼料廠 | `srcCard` | 飼料廠 · 源評分 | 摺疊 | 223 源 | 5/50/全部 |

### 7.5 i18n 引擎 (繁/簡/EN)

```javascript
const I18N = {
  'zh-Hant': { /* 134 keys */ },
  'zh-Hans': { /* 134 keys */ },
  'en':      { /* 134 keys */ }
};
function t(key, vars={}) {
  const dict = I18N[currentLang] || I18N['zh-Hant'];
  let s = dict[key] ?? key;
  for (const [k,v] of Object.entries(vars))
    s = s.replace(`{${k}}`, v);
  return s;
}
```

- HTML 靜態文本: `data-i18n="key"` (70 處)
- HTML 輸入框: `data-i18n-placeholder="key"` (3 處)
- HTML title 屬性: `data-i18n-title="key"` (6 處)
- JS 動態渲染: `t('key')`
- 默認 zh-Hant，切換器在 header `[繁][簡][EN]`
- localStorage 記住偏好

加新文本必須同時:
1. 三個字典加 key
2. HTML 加 `data-i18n` 屬性 (或 JS 用 `t('key')`)

### 7.6 安全加固 (9 個 nginx 安全頭 + XSS 防護)

```nginx
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=(), accelerometer=(), gyroscope=()" always;
add_header Cross-Origin-Opener-Policy   "same-origin" always;
add_header Cross-Origin-Resource-Policy "same-origin" always;
add_header Strict-Transport-Security    "max-age=63072000; includeSubDomains" always;
add_header X-Frame-Options              "SAMEORIGIN" always;
add_header X-Content-Type-Options       "nosniff" always;
add_header Referrer-Policy              "strict-origin-when-cross-origin" always;
add_header X-XSS-Protection             "0" always;
```

XSS 工具 (app.js)：
```javascript
const __htmlEntityMap = { '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' };
function esc(s) { if (s==null) return ''; return String(s).replace(/[&<>"']/g, c => __htmlEntityMap[c]); }
function safeUrl(u) { if (!u) return '#'; const s=String(u).trim(); return /^https?:\/\//i.test(s) ? s : '#'; }
```

所有用戶字段進 `innerHTML` 必須 `esc()`：節點名 / URL / 審計 finding 等 (12 處)。
所有 `href=` 用 `safeUrl()` (3 處)。

### 7.7 雞霸王打碼 (隱私保護)

服務器 IP / 端口 / 加密方式不直接顯示，HTML 用 `<span class="masked">` 標記，JS 啟動時重新生成打碼文本（HTML 寫死的不可信）：

```html
<span class="masked"
      data-secret="原值"
      data-mask-mode="domain|port|generic"
      title="...">顯示文本</span>
```

打碼模式:
- `domain`: 前 3 + `***` + 末 3
- `port`: 首位 + `***`
- `generic`: 前 3 + `***` + 末 3

樣式: 灰藍虛線邊框 + monospace + 字母間距加大。**v3.1 已移除點擊展開** (純展示, 不可恢復)。

### 7.8 三檔限制 + localStorage 持久化

5 個列表都走三檔 (5 行 → mid → 全部)：

| 列表 | total | mid | 行為 |
|---|---|---|---|
| nodeTable (節點池) | ~597 | 100 | 5 → 100 → 全部 |
| srcTable (源池) | ~223 | 50 | 5 → 50 → 全部 |
| qTopBody (品質排行) | ~30 | 0 | 5 → 全部 |
| discoverQueue (覓食隊列) | 16 | 0 | 5 → 全部 |
| qBlacklist (黑名單) | ~20 | 0 | 5 → 全部 |

```javascript
const TABLE_LIMIT_KEY = 'ss-monitor.table-limits';
function getTableStage(tableId) { /* localStorage */ }
function setTableStage(tableId, stage) { /* localStorage */ }
function computeLimit(stage, total, mid) { /* { take, nextStage, nextLabel, prevStage, prevLabel } */ }
```

### 7.9 版本號緩存爆破

`index.html` 引用外置資源加 `?v=YYYYMMDD_HHMM` 查詢參數，每次大改 JS/CSS 時更新版本號:

```html
<link rel="stylesheet" href="/ss-monitor/app.css?v=20260527_1055">
<script src="/ss-monitor/app.js?v=20260527_1055" defer></script>
```

nginx 那邊 `Cache-Control: no-cache, must-revalidate`，但加版本號是雙保險。

### 7.10 console guard (生產靜音)

```javascript
const __DEBUG = location.hostname === 'localhost' ||
                location.hostname === '127.0.0.1' ||
                new URLSearchParams(location.search).has('debug');
const dbg = {
  log:   __DEBUG ? console.log.bind(console)  : ()=>{},
  warn:  __DEBUG ? console.warn.bind(console) : ()=>{},
  error: console.error.bind(console)   // 永遠輸出
};
```

開發時 URL 加 `?debug` 打開 console.log。

---

## 八、nginx + TLS + 域名

> 完整素材: `snapshots/nginx/{aicf, one-api, snippets/}`

### 8.1 兩個 vhost 並存

| 域名 | 用途 | 證書 |
|---|---|---|
| `example.duckdns.org` | 主域名, `/` 302 → `/ss-monitor/`, 不暴露 one-api 控制台 | Let's Encrypt ECDSA |
| `example-legacy.duckdns.org` | 舊域名, 兼容老訂閱鏈接 | Let's Encrypt RSA |

### 8.2 aicf vhost 結構

```
HTTP :80 → 301 → HTTPS :443

HTTPS :443 (http2 on)
├── /                       → 302 /ss-monitor/
├── /ss-monitor/            → alias /opt/ss-monitor/  (9 安全頭)
├── /sub/free/(stats|nodes|diff|history).json
│                           → alias /opt/ss-monitor/sub/free/$1.json (公開)
├── /sub/free/<32hex>/(all|all-config|v2ray|base64).(yaml|txt)
│                           → alias /opt/ss-monitor/sub/free/$1/$2.$3 (token 鑑權)
├── /sub/free/.*            → 403 (其他都拒)
├── /api/vps-status         → 127.0.0.1:5000
├── /api/ss-status          → 127.0.0.1:5000
├── /api/free-pool          → 127.0.0.1:5000
├── /api/free-pool/         → 127.0.0.1:5000  (子路徑)
└── /                       → 404 (不暴露 one-api 控制台)
```

### 8.3 共用 snippets

`/etc/nginx/snippets/security-common.conf` (9 個安全頭)：
```nginx
add_header Strict-Transport-Security  "max-age=63072000; includeSubDomains" always;
add_header X-Frame-Options            "SAMEORIGIN" always;
add_header X-Content-Type-Options     "nosniff" always;
add_header Referrer-Policy            "strict-origin-when-cross-origin" always;
add_header X-XSS-Protection           "0" always;
add_header Permissions-Policy         "camera=(), microphone=(), geolocation=(), payment=(), usb=(), accelerometer=(), gyroscope=()" always;
add_header Cross-Origin-Opener-Policy   "same-origin" always;
add_header Cross-Origin-Resource-Policy "same-origin" always;
# CSP 在 location 級別覆蓋, 因為不同路徑要不同策略
```

`/etc/nginx/snippets/ssl-hardening.conf`：
```nginx
ssl_protocols       TLSv1.2 TLSv1.3;
ssl_ciphers         ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM;
ssl_prefer_server_ciphers off;
ssl_session_cache   shared:SSL:10m;
ssl_session_timeout 1d;
ssl_session_tickets off;
ssl_stapling on;
ssl_stapling_verify on;
```

`/etc/nginx/snippets/acme-challenge.conf`：
```nginx
location /.well-known/acme-challenge/ {
    root /var/www/letsencrypt;
}
```

### 8.4 限流 zone (主 nginx.conf)

```nginx
http {
    limit_req_zone $binary_remote_addr zone=ss_api:10m rate=10r/s;
    # ... 其他全局
}
```

vhost 裡用：
```nginx
location /api/free-pool {
    limit_req zone=ss_api burst=12 nodelay;
    ...
}
```

### 8.5 證書自動續期 + nginx reload

`/etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh` (mode 700)：
```bash
#!/bin/bash
set -e
LOG_TAG="certbot-deploy-hook"
LINEAGE="${RENEWED_LINEAGE:-unknown}"
DOMAINS="${RENEWED_DOMAINS:-unknown}"

logger -t "$LOG_TAG" "證書續期完成: $LINEAGE (domains: $DOMAINS), 準備 reload nginx"

# 先語法檢查, 任何錯誤都不重啟 (寧可暫時用舊證書也不能讓 nginx 掛)
if ! nginx -t 2>&1 | logger -t "$LOG_TAG"; then
    logger -t "$LOG_TAG" "❌ nginx -t 失敗, 拒絕 reload"
    exit 1
fi

if nginx -s reload 2>&1 | logger -t "$LOG_TAG"; then
    logger -t "$LOG_TAG" "✓ nginx reload 成功, 新證書已生效"
else
    logger -t "$LOG_TAG" "❌ nginx reload 失敗"
    exit 1
fi
```

> 這個 hook **必須有**, 否則證書 60 天後續成功但 nginx 仍跑舊證書。`certbot.timer` 每天 10:40 跑一次, 命中續期就觸發 hook。

### 8.6 申請新證書

```bash
# 確認 acme-challenge 路徑可達
mkdir -p /var/www/letsencrypt/.well-known/acme-challenge
echo test > /var/www/letsencrypt/.well-known/acme-challenge/test.txt
curl http://example.duckdns.org/.well-known/acme-challenge/test.txt   # 應該返回 'test'

# 申請 (ECDSA 推薦)
certbot certonly --webroot -w /var/www/letsencrypt \
    --key-type ecdsa --elliptic-curve secp384r1 \
    -d example.duckdns.org \
    --email <your-email> --agree-tos --non-interactive

# 證書路徑
ls /etc/letsencrypt/live/example.duckdns.org/
# fullchain.pem  privkey.pem  cert.pem  chain.pem  README

# 啟用 vhost
ln -s /etc/nginx/sites-available/aicf /etc/nginx/sites-enabled/aicf
nginx -t && nginx -s reload
```

### 8.7 nginx 1.24 vs 1.25+ http2 語法差異

```nginx
# 1.24 (Debian 12, 當前版本)
listen 443 ssl http2;
listen [::]:443 ssl http2;

# 1.25+ (Ubuntu 24.04)
listen 443 ssl;
listen [::]:443 ssl;
http2 on;
```

部署時用 `nginx -v` 確認版本，模板對齊。

---


## 九、cron 編排 (11 個任務 + 守護 + 維護)

> 完整素材: `snapshots/cron/root.crontab.snapshot`

### 9.1 cron 全表 (按時間順序)

```cron
# ========================================================================
# AI 養雞場 cron 編排 (single-host)
#
# 設計原則:
#   - 維護窗口集中: 00:00-00:10 + 04:00-04:20 (uptime 監控豁免這兩段)
#   - 通知錯峰: notify :00 / bobdong :01 / aicf-uptime :30 (錯開 :00 高峰)
#   - 隱含時序假設不可破壞 (見 §9.4)
#   - dpkg 鎖窗口 04:00-04:15 必須避開 (apt-security-updates 持鎖)
# ========================================================================

# === DuckDNS IP 推送 (每 5min) ===
*/5 * * * * /opt/duckdns/duck.sh >/dev/null 2>&1

# === 雞舍探活 (每 30min) ===
*/30 * * * * /usr/local/bin/aicf-uptime-monitor.sh >/dev/null 2>&1
# (其他項目: openclaw-uptime, convert-formats 也跑 */30, 共 3 個任務)

# === 雞蛋處理流水線 (subs-check 主管道, 每 30min) ===
*/30 * * * * /opt/subs-check/scripts/convert-formats.py >> /var/log/subs-check-convert.log 2>&1

# === 增量探活 (每小時 :15) ===
15 * * * * /opt/subs-check/scripts/incremental-check.py >> /var/log/subs-check-incremental.log 2>&1

# === Telegram 兜底通知 (每小時 :00) ===
0 * * * * /opt/subs-check/scripts/notify-telegram.py >> /var/log/subs-check-notify.log 2>&1

# === 覓食 (每天 02:00, 自動發現新源) ===
0 2 * * * /opt/subs-check/scripts/discover-airports.py >> /var/log/subs-check-discover.log 2>&1

# === 周日 03:00 健康源 score +5 ===
0 3 * * 0 /opt/subs-check/scripts/weekly-recovery.py >> /var/log/subs-check-recovery.log 2>&1

# === 周日 03:30 清舊 audit log ===
30 3 * * 0 /opt/subs-check/scripts/audit-cleanup.py >> /var/log/subs-check-audit-cleanup.log 2>&1

# === 04:00 同步 lza6 README + 評分 + reload subs-check ===
0 4 * * * /opt/subs-check/scripts/sync-lza6.py >> /var/log/subs-check-sync.log 2>&1

# === 04:05/10/16/22 拓取每源節點映射 ===
5 4,10,16,22 * * * /opt/subs-check/scripts/source-fetcher.py >> /var/log/subs-check-fetcher.log 2>&1

# === 每天 04:33 清 30 天前 source_quality_history ===
33 4 * * * /opt/subs-check/scripts/source-quality-history-cleanup.py >> /var/log/subs-check-cleanup.log 2>&1

# === 每天 04:35 SSL 證書監控 ===
35 4 * * * /usr/local/bin/ssl-monitor.sh --report >> /var/log/ssl-monitor.log 2>&1
```

### 9.2 時序圖 (24h 視窗)

```
00:00 ─┬─ openclaw-auto-update (其他項目, 重啟 nginx 鄰居)
       │  → 維護窗口 00:00-00:10, uptime 監控豁免
00:10 ─┘
00:30 ── aicf-uptime + openclaw-uptime + convert-formats (三 */30 並發)
01:00 ── notify-tg + 其他 :00 任務
02:00 ── 🐛 discover-airports (覓食, ~30-60min)
03:00 ── 周日: weekly-recovery (+5)
03:30 ── 周日: audit-cleanup
04:00 ─┬─ 🥚 sync-lza6 (主源同步)
04:05 ─┤  source-fetcher 第一次跑
       │  apt-security-updates (持 dpkg 鎖)
       │  → 維護窗口 04:00-04:20, uptime 監控豁免
04:15 ─┘
04:20 ── certbot.timer 候選窗口
04:33 ── source-quality-history-cleanup
04:35 ── ssl-monitor.sh --report
04:40 ── certbot.timer 第二窗口 (10:40 主窗口在白天)
09:00 ── (其他項目: 日報通知)
09:01 ── (其他項目: bobdong 預算/速率, 4 次 :01 錯峰)
10:05 ── source-fetcher
10:40 ── certbot.timer (Let's Encrypt 續期主窗口)
13:01 ── bobdong 監控
16:05 ── source-fetcher
17:01 ── bobdong 監控
21:01 ── bobdong 監控
22:05 ── source-fetcher
23:59 ── (週循環邊界)

每 5min: duck.sh (DuckDNS 推送, 4 域名一次推)
每 15min: subs-check 自跑 6h 一輪 (04/10/16/22 對齊)
每 30min: aicf-uptime + convert-formats
每 60min: incremental-check (:15) + notify-tg (:00)
```

### 9.3 timer / certbot

systemd-timer 也佔用一些時間:
```
certbot.timer        每天 10:40 + 04:40 (隨機抖動)  ← 證書續期
e2scrub_all.timer    週日 03:10                    ← 文件系統掃描
sysstat-collect.timer 每 10 分鐘
```

### 9.4 隱含時序假設 (5 條, 不可破壞)

1. `subs-check` 6h 一輪 (04/10/16/22) ← `source-fetcher 5 4,10,16,22` 跟著跑
2. `04:00 sync-lza6` → reload subs-check
3. `convert-formats` 在 subs-check 完成後才有 all.yaml (空跑為 noop)
4. `discover-airports 02:00` 在 sync-lza6 04:00 之前 (避免寫表撞)
5. `weekly-recovery 03:00` → `audit-cleanup 03:30` (30min 間距)

### 9.5 dpkg 鎖窗口

`/etc/cron.d/apt-security-updates` 在 04:00-04:15 跑 `apt upgrade --only-upgrade`，**持 dpkg 鎖 5-10min**。任何維護腳本都不要在這個窗口跑 apt 命令。

### 9.6 共享庫 `uptime-common.sh`

`/usr/local/lib/uptime-common.sh` 提供 5 個函數，被 `aicf-uptime-monitor.sh` 和 `openclaw-uptime-monitor.sh` 共用：

```bash
log <msg>                     # echo + tee 到 $LOG_FILE
get_state <key>               # 從 $STATE_FILE 讀
set_state <key> <val>         # 原子寫 $STATE_FILE (mktemp + mv)
check_url <url> [timeout]     # curl 返回 HTTP code
notify_telegram <title> <body># 發 Telegram (Markdown), 用 /etc/telegram-bot.conf
is_maintenance_window         # 命中 echo window 字串並 return 0
```

調用方需先設置變量：
```bash
LOG_FILE=/var/log/aicf-uptime-monitor.log
STATE_FILE=/var/lib/aicf-uptime-monitor.state
MAINTENANCE_WINDOWS=("00:00-00:10" "04:00-04:20")
CURL_TIMEOUT=10
source /usr/local/lib/uptime-common.sh
```

**坑**: 必須有 `UPTIME_COMMON_LOADED` guard, 否則 source 兩次會 reset `set -e` 狀態。

### 9.7 aicf-uptime-monitor 邏輯

```
每 30min:
  1. 是否在維護窗口? → 命中跳過, 寫 state=maintenance
  2. 同時探活 https://example.duckdns.org/ss-monitor/ + /api/free-pool
  3. 兩個都 200 → 重置 consecutive_fail=0, 標記 last_status=UP
  4. 任一失敗 → consecutive_fail+=1
  5. consecutive_fail >= 2 (=60min) → Telegram 告警 (一次), 寫 last_alert_at
  6. 從 DOWN 恢復 → Telegram 通知, 防 30min 內重複恢復通知
```

不做自動修復 — aicf 只是 nginx vhost, 沒有獨立後端可重啟。如果 nginx 整體掛了由 openclaw-uptime 負責處理。

### 9.8 duck.sh (DuckDNS 4 域名一次推)

```bash
#!/bin/bash
set -uo pipefail
CONF="/etc/duckdns/duckdns.conf"
LOG_FILE="/var/log/duckdns-update.log"
DOMAINS="example-root,example-legacy,example-aux,example"

source "$CONF"   # 讀 token (帶引號, source 比 grep+cut 安全)

URL="https://www.duckdns.org/update?domains=${DOMAINS}&token=${token}&ip="
RESP=$(curl -sk --max-time 15 "$URL")
[ "$RESP" = "OK" ] && exit 0 || exit 1
```

> 「ip 為空」→ DuckDNS 自動用請求源 IP (CGNAT 場景下這是公網出口 IP)，所以一條 cron 推 4 個域名都拿到正確 IP。

---

## 十、SQLite 數據庫 schema

> 完整素材: `snapshots/scripts/{source-scores.schema.sql, history.schema.sql}`

### 10.1 source-scores.db (源級評分 + 覓食)

```sql
CREATE TABLE sources (
    url                       TEXT PRIMARY KEY,
    first_seen                TEXT,
    last_seen                 TEXT,
    last_in_subs_check        TEXT,        -- 最後一次進 sub-urls.txt
    consecutive_fails         INTEGER DEFAULT 0,
    consecutive_passes        INTEGER DEFAULT 0,
    consecutive_low_quality   INTEGER DEFAULT 0,    -- ③ streak
    low_score_total           INTEGER DEFAULT 0,    -- ④ 累計 (v2.3 新增)
    total_checks              INTEGER DEFAULT 0,
    total_passes              INTEGER DEFAULT 0,
    score                     REAL DEFAULT 100.0,   -- v2.3 滿分起步
    status                    TEXT DEFAULT 'candidate',  -- candidate/whitelisted/blacklisted
    blocked_until             TEXT,                 -- 拉黑到期 (30 天)
    first_seen_round          INTEGER,
    note                      TEXT
);
CREATE INDEX idx_score  ON sources(score DESC);
CREATE INDEX idx_status ON sources(status);

CREATE TABLE source_node_map (
    source_url       TEXT NOT NULL,
    canonical_sig    TEXT NOT NULL,    -- server:port:type
    first_seen_round INTEGER,
    last_seen_round  INTEGER,
    PRIMARY KEY (source_url, canonical_sig)
);
CREATE INDEX idx_snm_source ON source_node_map(source_url);
CREATE INDEX idx_snm_sig    ON source_node_map(canonical_sig);

CREATE TABLE source_quality_history (
    source_url        TEXT NOT NULL,
    round_id          INTEGER NOT NULL,
    timestamp         TEXT NOT NULL,
    node_count        INTEGER,
    avg_quality_score REAL,
    below_50          INTEGER DEFAULT 0,
    PRIMARY KEY (source_url, round_id)
);
CREATE INDEX idx_sqh_source ON source_quality_history(source_url, round_id DESC);

-- discover-airports 私有表 (清理系統不讀)
CREATE TABLE discovery_state (
    key                 TEXT PRIMARY KEY,
    kind                TEXT NOT NULL,  -- awesome_readme/github_topic/telegram_channel/source_audit
    url                 TEXT,
    priority            INTEGER DEFAULT 100,
    last_scanned_at     TEXT,
    last_status         TEXT,           -- ok/fail/skipped/quota/blocked
    last_added_count    INTEGER DEFAULT 0,
    total_added_count   INTEGER DEFAULT 0,
    consecutive_empty   INTEGER DEFAULT 0,
    note                TEXT,
    enabled             INTEGER DEFAULT 1
);
CREATE INDEX idx_discovery_kind ON discovery_state(kind, priority);

CREATE TABLE source_audits (
    audit_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url   TEXT NOT NULL,
    audited_at   TEXT NOT NULL,
    severity     TEXT,            -- info/warn/critical
    finding      TEXT,            -- "ioc_hit:eval(", "html_response", ...
    detail_json  TEXT
);
CREATE INDEX idx_audit_source ON source_audits(source_url, audited_at DESC);

CREATE TABLE metadata (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT
);
-- metadata 用途:
--   lza6_etag: sync-lza6 ETag 短路
--   last_round_id: 最後一輪 ID
--   schema_version: v2.3
```

### 10.2 history.db (節點級評分 + 輪次)

```sql
CREATE TABLE rounds (
    round_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    yaml_mtime      TEXT NOT NULL,        -- all.yaml mtime, 同 mtime 不重入庫
    total_nodes     INTEGER,
    protocols_json  TEXT,                  -- {"vless":210,...}
    nodes_hash      TEXT,                  -- 當前輪節點集合穩定哈希
    diff_added      INTEGER DEFAULT 0,
    diff_removed    INTEGER DEFAULT 0,
    diff_kept       INTEGER DEFAULT 0,
    notified        INTEGER DEFAULT 0      -- Telegram 已推送
);
CREATE UNIQUE INDEX idx_rounds_mtime ON rounds(yaml_mtime);
CREATE INDEX idx_rounds_ts ON rounds(timestamp DESC);

CREATE TABLE nodes_history (
    canonical_sig                  TEXT PRIMARY KEY,    -- server:port:type
    first_seen                     TEXT,
    last_seen                      TEXT,
    last_speed_kbps                INTEGER,
    avg_speed_kbps                 REAL DEFAULT 0,
    total_appearances              INTEGER DEFAULT 0,
    consecutive_appearances        INTEGER DEFAULT 0,
    consecutive_fails              INTEGER DEFAULT 0,   -- 探活失敗 streak
    consecutive_low_quality_node   INTEGER DEFAULT 0,   -- ② v2.3 新增
    incremental_pass               INTEGER DEFAULT 0,
    incremental_fail               INTEGER DEFAULT 0,
    blacklisted_until              TEXT,                -- 48h
    quality_score                  REAL DEFAULT 100.0,  -- v2.3 滿分起步
    last_round_id                  INTEGER,
    region                         TEXT,
    protocol                       TEXT,
    sample_name                    TEXT
);
CREATE INDEX idx_nodes_score     ON nodes_history(quality_score DESC);
CREATE INDEX idx_nodes_blacklist ON nodes_history(blacklisted_until);
```

### 10.3 全量重置 SQL (兼容性破壞時)

```sql
-- 源級
UPDATE sources SET
    score = 100.0,
    consecutive_fails = 0,
    consecutive_passes = 0,
    consecutive_low_quality = 0,
    low_score_total = 0
WHERE status != 'blacklisted';

-- 節點級
UPDATE nodes_history SET
    quality_score = 100.0,
    consecutive_fails = 0,
    consecutive_low_quality_node = 0
WHERE blacklisted_until IS NULL OR blacklisted_until < datetime('now');

-- 清舊評分歷史 (公式變了, 舊數據無效)
DELETE FROM source_quality_history;
```

---


## 十一、1:1 部署步驟 (從零拉起)

> **前提**: VPS 已就緒 (Debian 12 / Ubuntu 22.04 LTS, 公網或 CGNAT 都行), 域名已 A 記錄到 VPS

### 11.1 Phase 0: 系統準備

```bash
# 1. 更新系統 + 必要包
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-yaml sqlite3 nginx \
               curl wget jq cron logrotate rsyslog \
               certbot python3-certbot-nginx

# 2. Python 套件
pip3 install --break-system-packages flask pyyaml requests

# 3. 開放 80/443 (UFW 場景)
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 22/tcp
ufw --force enable

# 4. 時區 (避免 cron 時間錯位)
timedatectl set-timezone Asia/Hong_Kong   # 或 Asia/Shanghai / UTC

# 5. 創建用戶/目錄/日誌
mkdir -p /opt/subs-check/scripts /opt/subs-check/config
mkdir -p /opt/ss-monitor/sub/free
mkdir -p /var/www/letsencrypt/.well-known/acme-challenge
mkdir -p /var/log
mkdir -p /var/lib   # state file 目錄
```

### 11.2 Phase 1: DuckDNS + Telegram + 訂閱 token

> 提示: 下面命令裡所有 `__YOUR_XXX__` 都是占位符，部署時替換成你的實際值。

```bash
# === DuckDNS ===
mkdir -p /etc/duckdns
# 把 __YOUR_DUCKDNS_TOKEN__ 換成你在 https://www.duckdns.org/ 賬戶頁拿到的 token
printf 'token="__YOUR_DUCKDNS_TOKEN__"\n' > /etc/duckdns/duckdns.conf
chmod 600 /etc/duckdns/duckdns.conf

mkdir -p /opt/duckdns
cp <repo>/snapshots/cron/duck.sh /opt/duckdns/duck.sh
chmod +x /opt/duckdns/duck.sh

# 改 DOMAINS 行為你的域名 (第 20 行)
vim /opt/duckdns/duck.sh

# 跑一次驗證
/opt/duckdns/duck.sh
tail /var/log/duckdns-update.log
# 預期日誌: ✓ DuckDNS 推送成功 (...)

# === Telegram bot ===
# 1) @BotFather 創建 bot 拿 BOT_TOKEN
# 2) 私聊 bot 一次, 然後訪問:
#    https://api.telegram.org/bot__YOUR_BOT_TOKEN__/getUpdates
#    取 result[0].message.chat.id 作為 CHAT_ID
{
  printf 'TELEGRAM_BOT_TOKEN=__YOUR_BOT_TOKEN__\n'
  printf 'TELEGRAM_CHAT_ID=__YOUR_CHAT_ID__\n'
} > /etc/telegram-bot.conf
chmod 600 /etc/telegram-bot.conf

# 編輯填入真實值
vim /etc/telegram-bot.conf

# 測試發送
set -a; source /etc/telegram-bot.conf; set +a
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
     -d "chat_id=${TELEGRAM_CHAT_ID}" \
     -d "text=AI 養雞場部署測試"
# 預期: TG 收到一條測試訊息

# === 訂閱 token (32 hex) ===
NEW_TOKEN=$(python3 -c 'import secrets; print(secrets.token_hex(16))')
echo "生成的訂閱 token: $NEW_TOKEN"
# 保存到環境變量, 後面 Phase 2 / Phase 5 都用
export NEW_TOKEN
```

### 11.3 Phase 2: subs-check 主二進制 + 配置

```bash
cd /opt/subs-check

# 下載 + 校驗
timeout 120 curl -L -o /tmp/subs-check.tar.gz \
  https://github.com/beck-8/subs-check/releases/latest/download/subs-check_Linux_x86_64.tar.gz
gzip -t /tmp/subs-check.tar.gz   # 必須完整
tar xzf /tmp/subs-check.tar.gz
chmod +x subs-check

# 跑一次生成默認 config
timeout 5 ./subs-check 2>&1 | head -10

# 拷貝模板
cp <repo>/snapshots/scripts/subs-check.config.yaml config/config.yaml

# 改關鍵字段 (Python 安全改, 不用 sed) — 用 Phase 1 生成的 NEW_TOKEN
python3 - <<'PYEOF'
import os, yaml
tok = os.environ['NEW_TOKEN']
p = '/opt/subs-check/config/config.yaml'
c = yaml.safe_load(open(p))
c['output-dir']    = f'/opt/ss-monitor/sub/free/{tok}'
c['listen-port']   = '127.0.0.1:8199'
c['enable-web-ui'] = False
yaml.safe_dump(c, open(p,'w'), allow_unicode=True, sort_keys=False, width=200)
print('config.yaml updated, output-dir=', c['output-dir'])
PYEOF

# 創 token 子目錄 (subs-check 自己也會建, 但提前 mode 750)
mkdir -p /opt/ss-monitor/sub/free/${NEW_TOKEN}
chmod 750 /opt/ss-monitor/sub/free/${NEW_TOKEN}

# free-pool.conf (用 printf 避免 heredoc 觸發 redaction)
{
  printf 'TOKEN=%s\n' "${NEW_TOKEN}"
  printf 'DOMAIN=example.duckdns.org\n'
} > /opt/subs-check/scripts/free-pool.conf
chmod 600 /opt/subs-check/scripts/free-pool.conf

# systemd unit
cp <repo>/snapshots/systemd/subs-check.service /etc/systemd/system/
mkdir -p /etc/systemd/system/subs-check.service.d
cp <repo>/snapshots/systemd/subs-check.service.d/limits.conf /etc/systemd/system/subs-check.service.d/

systemctl daemon-reload
systemctl enable subs-check    # 暫不 start, 先把腳本和 DB 建起來
```

### 11.4 Phase 3: Python 維護腳本 + DB schema

```bash
cd /opt/subs-check/scripts

# 拷貝 11 個腳本 + 配置
cp <repo>/snapshots/scripts/sync-lza6.py .
cp <repo>/snapshots/scripts/convert-formats.py .
cp <repo>/snapshots/scripts/source-fetcher.py .
cp <repo>/snapshots/scripts/incremental-check.py .
cp <repo>/snapshots/scripts/notify-telegram.py .
cp <repo>/snapshots/scripts/weekly-recovery.py .
cp <repo>/snapshots/scripts/source-quality-history-cleanup.py .
cp <repo>/snapshots/scripts/discover-airports.py .
cp <repo>/snapshots/scripts/audit-cleanup.py .
cp <repo>/snapshots/scripts/dryrun-v2.3.py .
cp <repo>/snapshots/scripts/discovery-config.yaml .
cp <repo>/snapshots/scripts/ioc-list.txt .
cp <repo>/snapshots/scripts/SCORING_RULES_v2.md .

chmod +x *.py

# 創建 DB (空表結構)
sqlite3 /opt/subs-check/scripts/source-scores.db < <repo>/snapshots/scripts/source-scores.schema.sql
sqlite3 /opt/subs-check/scripts/history.db       < <repo>/snapshots/scripts/history.schema.sql

# 灌覓食配置
python3 discover-airports.py --bootstrap
sqlite3 source-scores.db "SELECT key, kind FROM discovery_state"
# 應該看到 16 行 (10 awesome + 6 topic)

# sync-lza6 跑一次 (建 sub-urls.txt + 灌 sources)
python3 sync-lza6.py
# 預期: 抓 lza6/free-VPN README, 提 ~80 個源, 寫 sub-urls.txt
sqlite3 source-scores.db "SELECT COUNT(*), AVG(score) FROM sources"
# 預期: 80 行, score=100

# 啟動 subs-check (現在 sub-urls.txt 已備好)
systemctl start subs-check
journalctl -u subs-check -f
# 等 5-30min 跑完一輪
```

### 11.5 Phase 4: ss-monitor 展示頁

```bash
cd /opt/ss-monitor
cp <repo>/snapshots/ss-monitor/api.py .
cp <repo>/snapshots/ss-monitor/index.html .
cp <repo>/snapshots/ss-monitor/app.css .
cp <repo>/snapshots/ss-monitor/app.js .

cp <repo>/snapshots/systemd/ss-monitor.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now ss-monitor

# 探活
curl -s http://127.0.0.1:5000/api/free-pool | jq '.completed'
curl -s http://127.0.0.1:5000/api/free-pool/sources | jq '.rules_version'
# 預期: rules_version="v2.3"
```

### 11.6 Phase 5: nginx + TLS

```bash
# 共用片段
cp <repo>/snapshots/nginx/snippets/* /etc/nginx/snippets/

# vhost (改 server_name + ssl_certificate 路徑為你的域名)
cp <repo>/snapshots/nginx/aicf /etc/nginx/sites-available/aicf
vim /etc/nginx/sites-available/aicf   # 改 example.duckdns.org → 你的域名

# 限流 zone (主 nginx.conf)
grep -q 'limit_req_zone.*ss_api' /etc/nginx/nginx.conf || \
sed -i '/^http {/a\    limit_req_zone $binary_remote_addr zone=ss_api:10m rate=10r/s;' /etc/nginx/nginx.conf

# 申請證書 (用 webroot, 80 端口必須可達)
ln -s /etc/nginx/sites-available/aicf /etc/nginx/sites-enabled/aicf
# 先弄一個臨時 HTTP 80 vhost 跑 ACME challenge
# (或者改 aicf vhost 暫時注釋 SSL block, 申請完再開回來)

certbot certonly --webroot -w /var/www/letsencrypt \
    --key-type ecdsa --elliptic-curve secp384r1 \
    -d example.duckdns.org --email <your-email> \
    --agree-tos --non-interactive

# certbot deploy hook (證書續期自動 reload nginx)
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cp <repo>/snapshots/cron/nginx-reload.sh /etc/letsencrypt/renewal-hooks/deploy/
chmod 700 /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh

# 啟用 vhost + reload
nginx -t && nginx -s reload

# 探活
curl -I https://example.duckdns.org/ss-monitor/
curl -s https://example.duckdns.org/api/free-pool | jq '.completed'

# 訂閱探活 (用你的 token)
curl -s https://example.duckdns.org/sub/free/$TOKEN/all.yaml | head -20
```

### 11.7 Phase 6: cron + 監控

```bash
# 拷貝 uptime 共享庫
cp <repo>/snapshots/cron/uptime-common.sh /usr/local/lib/
chmod 644 /usr/local/lib/uptime-common.sh

# aicf-uptime + ssl-monitor
cp <repo>/snapshots/cron/aicf-uptime-monitor.sh /usr/local/bin/
cp <repo>/snapshots/cron/ssl-monitor.sh /usr/local/bin/   # 可選
chmod +x /usr/local/bin/aicf-uptime-monitor.sh
chmod +x /usr/local/bin/ssl-monitor.sh

# 改 DOMAIN 為你的域名
vim /usr/local/bin/aicf-uptime-monitor.sh   # 看 §9.7

# 安裝 crontab
crontab -l 2>/dev/null > /tmp/old.cron
cat <repo>/snapshots/cron/root.crontab.snapshot >> /tmp/old.cron
# 手工去重 + 改路徑後
crontab /tmp/old.cron

# 驗證
crontab -l | grep -E "(subs-check|aicf|duck|discover)"

# 跑一次驗證
/opt/subs-check/scripts/convert-formats.py
/usr/local/bin/aicf-uptime-monitor.sh
/opt/duckdns/duck.sh
```

### 11.8 Phase 7: 完整自檢清單

```bash
# A. 服務狀態
for s in subs-check ss-monitor nginx shadowsocks-rust; do
    echo -n "$s: "; systemctl is-active $s
done

# B. 監聽端口
ss -tlnp | grep -E "(443|5000|8199|2052)"

# C. 探活 8 endpoints
for ep in vps-status ss-status free-pool free-pool/nodes free-pool/diff \
          free-pool/history free-pool/quality free-pool/sources \
          free-pool/discover; do
    code=$(curl -sk -o /dev/null -w "%{http_code}" https://example.duckdns.org/api/$ep)
    echo "/api/$ep: $code"
done

# D. 訂閱探活 (4 格式)
for f in all.yaml all-config.yaml v2ray.txt base64.txt; do
    code=$(curl -sk -o /dev/null -w "%{http_code}" https://example.duckdns.org/sub/free/$TOKEN/$f)
    echo "$f: $code"
done

# E. 9 安全頭
curl -skI https://example.duckdns.org/ss-monitor/ | grep -iE \
  "strict-transport|x-frame|x-content-type|referrer|x-xss|content-security|permissions-policy|cross-origin-(opener|resource)"
# 應該全部出現

# F. DB 完整性
sqlite3 /opt/subs-check/scripts/source-scores.db "PRAGMA integrity_check"
sqlite3 /opt/subs-check/scripts/history.db       "PRAGMA integrity_check"

# G. 評分 v2.3 標記
sqlite3 /opt/subs-check/scripts/source-scores.db \
  "SELECT COUNT(*), AVG(score), MIN(score), MAX(score) FROM sources"
# 預期 score 在 100 附近

# H. cron 條目齊全
crontab -l | grep -E "(subs-check|discover|duck|aicf|ssl-monitor)" | wc -l
# 預期 ≥ 11
```

---

## 十二、回滾與災備

### 12.1 備份標籤約定

每次大改前打標籤：`.bak.PRE_<TAG>.YYYYMMDD_HHMMSS`

| TAG | 用途 |
|---|---|
| `PRE_V2` | v2.3 評分系統升級備份 (永不清理) |
| `PRE_DISCOVER` | discover-airports 部署前 |
| `PRE_HARDEN` | nginx 安全加固前 |
| `PRE_AICF` | aicf 域名添加前 |
| `PRE_REFACTOR` | cron 重構前 |
| `PRE_TOPN` / `PRE_COLLAPSE` / `PRE_RENAME` | 前端 UI 改動 |

備份命令模板:
```bash
TS=$(date +%Y%m%d_%H%M%S)
TAG=PRE_FOO

# DB
sqlite3 source-scores.db ".backup source-scores.db.bak.$TAG.$TS"
sqlite3 history.db       ".backup history.db.bak.$TAG.$TS"

# 腳本
for f in sync-lza6.py convert-formats.py incremental-check.py; do
    cp -p $f $f.bak.$TAG.$TS
done

# ss-monitor
cp -p /opt/ss-monitor/api.py      /opt/ss-monitor/api.py.bak.$TAG.$TS
cp -p /opt/ss-monitor/index.html  /opt/ss-monitor/index.html.bak.$TAG.$TS
cp -p /opt/ss-monitor/app.js      /opt/ss-monitor/app.js.bak.$TAG.$TS

# crontab
crontab -l > /tmp/crontab.bak.$TAG.$TS
```

### 12.2 完整回滾 (v2.3 → v1)

```bash
TS=20260526_180329   # PRE_V2 時間戳

# 1. 停 cron 和服務
systemctl stop subs-check ss-monitor

# 2. 還原 DB
cd /opt/subs-check/scripts
mv source-scores.db source-scores.db.failed.$(date +%s)
mv history.db       history.db.failed.$(date +%s)
cp source-scores.db.bak.PRE_V2.$TS source-scores.db
cp history.db.bak.PRE_V2.$TS       history.db

# 3. 還原腳本
for f in sync-lza6.py convert-formats.py incremental-check.py; do
    cp -p $f.bak.PRE_V2.$TS $f
done

# 4. 還原 ss-monitor
cp -p /opt/ss-monitor/api.py.bak.PRE_V2.$TS     /opt/ss-monitor/api.py
cp -p /opt/ss-monitor/index.html.bak.PRE_V2.$TS /opt/ss-monitor/index.html

# 5. 還原 crontab
crontab /tmp/crontab.bak.PRE_V2.$TS

# 6. 重啟
systemctl start subs-check ss-monitor
```

### 12.3 covet-airports 單獨回滾

```bash
# 1. 停 cron
crontab -l | grep -v "discover-airports\|audit-cleanup" | crontab -

# 2. 刪私有表 (零數據損失)
sqlite3 /opt/subs-check/scripts/source-scores.db "DROP TABLE discovery_state; DROP TABLE source_audits;"

# 3. (可選) 刪腳本
rm /opt/subs-check/scripts/discover-airports.py
rm /opt/subs-check/scripts/discovery-config.yaml
rm /opt/subs-check/scripts/ioc-list.txt
rm /opt/subs-check/scripts/audit-cleanup.py

# 4. (可選) 刪 discover 引入的源
sqlite3 source-scores.db "DELETE FROM sources WHERE note LIKE 'discovered_by=%'"
# 注意: 已被 sync-lza6 測過有評分歷史的源刪了會丟測試結果, 一般保留
```

### 12.4 災難復原 (整機重裝)

從 `snapshots/` 走 §11 完整 7 個 Phase。預計 1-2 小時可拉起新環境。

如果 DB 沒了，新環境啟動會空跑幾輪，1 周內 sources/nodes_history 自動充滿。

---

## 十三、故障排查 (cheatsheet)

### 13.1 訂閱無法訪問 (403/404)

```bash
# 1. 確認 nginx alias 路徑指向正確的 token 子目錄
grep "alias /opt/ss-monitor/sub/free" /etc/nginx/sites-available/aicf

# 2. 確認 subs-check output-dir 一致
grep "output-dir" /opt/subs-check/config/config.yaml

# 3. 確認文件存在
ls -la /opt/ss-monitor/sub/free/*/all.yaml

# 4. URL 檢查 token 32hex 格式
echo "https://example.duckdns.org/sub/free/$TOKEN/all.yaml" | grep -E "/[a-f0-9]{32}/"
```

### 13.2 ss-monitor 502 / 5xx

```bash
# 1. Flask 是否活著
systemctl status ss-monitor
journalctl -u ss-monitor -n 50

# 2. 內存超限 (MemoryMax=50M)
systemctl show ss-monitor -p MemoryCurrent
# 50M 撞頂會 OOM kill, 重啟即可

# 3. SQLite 鎖
sqlite3 /opt/subs-check/scripts/history.db "PRAGMA busy_timeout=30000; SELECT 1"

# 4. nginx 反代失敗
curl -v http://127.0.0.1:5000/api/free-pool 2>&1 | head -20
```

### 13.3 subs-check 內存爆 / OOM

```bash
# 確認當前佔用
systemctl show subs-check -p MemoryCurrent
# 看 logs
journalctl -u subs-check --since "10 min ago" | grep -i "fatal\|panic\|oom"

# 緊急: 把 sub-urls 從 80 縮到 40
sed -i '40,$d' /opt/subs-check/config/sub-urls.txt
# 同步 config.yaml
python3 /opt/subs-check/scripts/sync-lza6.py
systemctl restart subs-check
```

### 13.4 評分跑偏 / 拉黑雪崩

```bash
# 跑 dry-run 模擬器看新規則影響
python3 /opt/subs-check/scripts/dryrun-v2.3.py
cat /tmp/v2.3-dryrun-report.json | jq '.summary'

# 如果立即拉黑 > 10% → 雪崩, 調阈值
# 改 convert-formats.py 頂部常量, 重跑 dry-run

# 緊急: 全量重置 (見 §10.3)
```

### 13.5 cron 不執行

```bash
# 1. crond 服務
systemctl status cron

# 2. crontab 解析
crontab -l | grep -v "^#"

# 3. 看執行歷史
grep CRON /var/log/syslog | tail -20

# 4. 手動跑一次
bash -x /opt/subs-check/scripts/convert-formats.py 2>&1 | head -30
```

### 13.6 nginx 改完掛了

```bash
# 必查 alias + 嵌套正則 location 不要混用 (歸檔 #10 事故)
nginx -t

# 回滾備份
ls /etc/nginx/sites-available/*.bak.* | tail -1
cp /etc/nginx/sites-available/aicf.bak.PRE_<TAG>.<TS> /etc/nginx/sites-available/aicf
nginx -t && nginx -s reload

# diff 備份和當前確認備份是「乾淨的改前狀態」
diff /etc/nginx/sites-available/aicf /etc/nginx/sites-available/aicf.bak.PRE_<TAG>.<TS>
```

### 13.7 證書到期未自動續

```bash
# 看 certbot 日誌
journalctl -u certbot.timer
journalctl -u certbot.service --since "7 days ago"

# 看 deploy hook 是否跑過
journalctl -t certbot-deploy-hook --since "30 days ago"

# 手動觸發
certbot renew --dry-run
certbot renew --force-renewal -d example.duckdns.org
```

### 13.8 Telegram 不發推送

```bash
# 1. token / chat_id 對不對
source /etc/telegram-bot.conf
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | jq

# 2. notify-telegram.py 看 history.db
sqlite3 /opt/subs-check/scripts/history.db \
  "SELECT round_id, timestamp, total_nodes, notified FROM rounds ORDER BY round_id DESC LIMIT 5"
# notified=1 表示已推, 0 表示未推

# 3. 強制重推某輪
sqlite3 /opt/subs-check/scripts/history.db \
  "UPDATE rounds SET notified=0 WHERE round_id=<N>"
python3 /opt/subs-check/scripts/notify-telegram.py
```

### 13.9 DuckDNS 推送失敗

```bash
# 看日誌
tail /var/log/duckdns-update.log

# 手動跑
/opt/duckdns/duck.sh

# token 對不對
source /etc/duckdns/duckdns.conf
curl "https://www.duckdns.org/update?domains=aicf&token=$token&ip="
# 預期: OK (不是 KO)

# CGNAT 場景: 確認源 IP 是有路由的
curl ifconfig.me
```

---


## 十四、CGNAT 兼容性 (用戶實際場景)

### 14.1 場景

用戶網絡是中國電信 CGNAT，公網 IPv4 不可入站，端口映射對外無效。出口靠：

```
本機 VPS  ←→  Tailscale  ←→  RAX3000M (家庭路由)  ←→  手機 HK relay
```

### 14.2 部署影響

- **訂閱分發**: 走 VPS (它有公網 IP，不在 CGNAT 後面)
- **管理訪問**: 通過 Tailscale 走 (100.x.x.x 內網)
- **DuckDNS**: 推送 VPS 公網 IP，CGNAT 客戶端訪問 VPS 沒問題
- **如果 VPS 自己也在 CGNAT 後**: 換成有公網的 VPS, AI 養雞場必須暴露在公網

### 14.3 IPv6 嘗試 (失敗)

用戶嘗試過 IPv6 方案，但光貓無法分配 PD 前綴，放棄。

---

## 十五、安全清單

### 15.1 文件權限自檢

```bash
# 必須 mode 600
for f in /opt/subs-check/scripts/free-pool.conf \
         /etc/telegram-bot.conf \
         /etc/duckdns/duckdns.conf; do
    p=$(stat -c %a $f)
    [ "$p" = "600" ] && echo "✓ $f $p" || echo "✗ $f $p (應 600)"
done

# 證書私鑰
stat -c %a /etc/letsencrypt/live/example.duckdns.org/privkey.pem  # 應 640 或 600
```

### 15.2 公開接口檢查

```bash
# 訂閱必須 token 鑑權
curl -sk -o /dev/null -w "%{http_code}\n" https://example.duckdns.org/sub/free/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/all.yaml
# 預期 404 或 403 (錯 token)

curl -sk -o /dev/null -w "%{http_code}\n" https://example.duckdns.org/sub/free/random/x.yaml
# 預期 403 (regex 不匹配)

# 監控 JSON 公開無 token
curl -sk -o /dev/null -w "%{http_code}\n" https://example.duckdns.org/sub/free/stats.json
# 預期 200

# nginx admin 接口不暴露
curl -sk -o /dev/null -w "%{http_code}\n" https://example.duckdns.org/api/login
# 預期 404 (one-api 控制台不在 aicf vhost)
```

### 15.3 SSRF 防護驗證

```bash
# discover-airports 嘗試解析私有 IP 應該被拒
python3 -c "
import sys
sys.path.insert(0, '/opt/subs-check/scripts')
from discover_airports import _safe_getaddrinfo
import socket
try:
    socket.getaddrinfo('10.0.0.1', 80)
    print('✗ SSRF 防護失效')
except PermissionError:
    print('✓ SSRF 拒絕私有 IP')
"
```

### 15.4 安全審計腳本

```bash
# 9 個安全頭
HEADERS=$(curl -skI https://example.duckdns.org/ss-monitor/ 2>&1)
for h in "Strict-Transport-Security" "X-Frame-Options" "X-Content-Type-Options" \
         "Referrer-Policy" "X-XSS-Protection" "Content-Security-Policy" \
         "Permissions-Policy" "Cross-Origin-Opener-Policy" "Cross-Origin-Resource-Policy"; do
    echo "$HEADERS" | grep -qi "^$h:" && echo "✓ $h" || echo "✗ $h MISSING"
done

# TLS 強度 (應 A+ 級)
# 在線測: https://www.ssllabs.com/ssltest/analyze.html?d=example.duckdns.org
```

---

## 十六、常見維護場景

### 16.1 加一個新 awesome 源

```bash
# 1. 改 discovery-config.yaml
vim /opt/subs-check/scripts/discovery-config.yaml
# 在 awesome_readme 列表加新條目

# 2. 同步到 DB
python3 /opt/subs-check/scripts/discover-airports.py --bootstrap

# 3. 立即跑一次測試
python3 /opt/subs-check/scripts/discover-airports.py --only awesome_readme --dry-run
# 看 dry-run 多少候選 → 多少通過

# 4. 真跑
python3 /opt/subs-check/scripts/discover-airports.py --only awesome_readme
```

### 16.2 臨時禁用某個發現源

```sql
UPDATE discovery_state SET enabled=0 WHERE key='peasoft/NoMoreWalls';
```

### 16.3 強制重新審計某源

```sql
DELETE FROM source_audits WHERE source_url='https://...';
```

### 16.4 阈值調整 (如 ③ 改成 streak >= 7)

1. 改 `convert-formats.py` 頂部 `SOURCE_KILL_AFTER_LOW_ROUNDS = 7`
2. 改 `api.py` `/api/free-pool/sources` 返回的 `kill_threshold_lq=7`
3. 改 `index.html` srcKillThreshold 默認值
4. 改 `app.js` 顯示文本
5. 跑 dry-run 驗證新阈值的拉黑數量
6. 上線後立即看 ss-monitor 卡片數據

### 16.5 升級 subs-check 二進制

```bash
TS=$(date +%Y%m%d_%H%M%S)
cp /opt/subs-check/subs-check /opt/subs-check/subs-check.bak.$TS

# 下載新版
timeout 120 curl -L -o /tmp/subs-check.tar.gz \
  https://github.com/beck-8/subs-check/releases/latest/download/subs-check_Linux_x86_64.tar.gz
gzip -t /tmp/subs-check.tar.gz
tar xzf /tmp/subs-check.tar.gz -C /tmp
chmod +x /tmp/subs-check
mv /tmp/subs-check /opt/subs-check/subs-check

# 跑 --version 確認
/opt/subs-check/subs-check --version

# 重啟
systemctl restart subs-check
journalctl -u subs-check -f
```

### 16.6 加新監控卡片

1. `api.py` 加 endpoint (返回 JSON)
2. `index.html` 加 `<div class="card collapsible" id="newCard">` + 內部結構 + `data-i18n` 屬性
3. `app.css` 加配色變體 (參考 rose/blue/green)
4. `app.js` 加 `loadNew()` async 函數，註冊到 `refreshAll()` + `setInterval`
5. 三個 i18n 字典加 keys
6. 更新 `?v=YYYYMMDD_HHMM` 版本號
7. 不需要重啟 ss-monitor (api.py 加 endpoint 才需要)

### 16.7 訂閱輸出格式擴展

`convert-formats.py` 已支持 4 格式 (all/all-config/v2ray/base64)。加新格式:
1. `convert_to_xxx(nodes)` 函數
2. 寫到 `/opt/ss-monitor/sub/free/<TOKEN>/xxx.yaml`
3. nginx vhost 加 location regex (`(all|all-config|v2ray|base64|xxx)`)
4. ss-monitor `/api/free-pool` 返回 `urls.xxx`
5. index.html 加訂閱 URL 顯示

---

## 十七、決策追溯 (為什麼這樣設計)

### 17.1 為什麼 v2.3 滿分起步而不是 v1 加權累積

v1: `score = 0.7 * stability + 0.3 * speed`，問題：
- 慢但穩定的節點長期 70 分以下，看起來像差節點
- 「忽好忽壞」源永遠在 50 邊界線附近徘徊
- 黑名單到期後 score=50 立刻又低，下輪馬上拉黑 (循環)

v2.3 改為滿分起步單向減分：
- 節點/源默認 100 給最大善意
- 真有問題才扣分，扣到底再黑
- 黑名單到期 score=100 + 全計數器歸零，給乾淨重來機會
- 4 個源級獨立計數器避免單一信號被誤觸發

### 17.2 為什麼覓食和清理分離

歸檔 #16 的契約：
- discover-airports **永不** UPDATE sources.score/status/note
- 用 `discovery_state` 和 `source_audits` 兩個私有表
- 清理系統 (sync-lza6, convert-formats) 永不讀 discover 私有表

好處：
- 兩個系統可以獨立升級回滾
- 一個系統 bug 不會污染另一個的數據
- audit 發現 critical 不會自動拉黑，必須用戶人工 review

### 17.3 為什麼 ss-monitor 拆成三個外置文件

歸檔 #17：
- 改 HTML/CSS/JS 不需要重啟 service
- 改 api.py 才需要重啟
- 拆分後 CSP 可以 'self' 不放 'unsafe-inline' (安全提升)
- 緩存/版本號控制更精細

### 17.4 為什麼 lza6 ETag 短路

實測 lza6 README 一週改 2-3 次，每次 sync-lza6 都跑 5min 全量提取太浪費。ETag 304 命中率 ≈ 70%，命中時只跑狀態機掃描 (~30s)。

### 17.5 為什麼 cron 重構成共享庫

歸檔 #21：兩個 uptime 監控腳本 80% 重複代碼，每次改一處要記著改另一處。提取 `uptime-common.sh` 5 個函數後：
- 從 372+175 行縮到 311+114 行 (省 122 行)
- 改一處兩個監控同步生效
- 函數名/行為對齊 (`set_state` 都是原子寫)

### 17.6 為什麼三檔限制不是兩檔

歸檔 #23-24：
- 兩檔 (5 / 全部) 對 600 行的節點表很糟，全部展開後滾動疲勞
- 中檔 100/50 給日常瀏覽，全部給審計
- mid=0 的列表 (數據量 <100) 跳過中檔變兩檔

---

## 十八、相關 skill 文檔指引

完整流程已在 Hermes Agent skill 系統中：

| Skill | 路徑 | 用途 |
|---|---|---|
| `devops/subs-check-deployment` | `~/.hermes/skills/devops/subs-check-deployment/SKILL.md` | 部署運維手冊 |
| `devops/subs-check-scoring-v23` | `~/.hermes/skills/devops/subs-check-scoring-v23/SKILL.md` | v2.3 評分機制完整規則 |
| `devops/discover-airports-maintenance` | `~/.hermes/skills/devops/discover-airports-maintenance/SKILL.md` | 覓食系統維護 |
| `devops/cron-orchestration` | `~/.hermes/skills/devops/cron-orchestration/SKILL.md` | cron 編排規範 |
| `devops/nginx-multi-domain-proxy` | `~/.hermes/skills/devops/nginx-multi-domain-proxy/SKILL.md` | 多域名 vhost 實踐 |

歸檔索引 (歷史決策):
- `memory-search "subs-check 评分"` → #14, #12 (v2.3 規則)
- `memory-search "discover-airports"` → #16 (覓食部署)
- `memory-search "ss-monitor i18n"` → #17 (前端拆分)
- `memory-search "ss-monitor 三檔"` → #23, #24 (UI v3)
- `memory-search "aicf 域名"` → #18 (aicf vhost)
- `memory-search "cron 重構"` → #21 (uptime 共享庫)
- `memory-search "Nginx 事故"` → #10 (alias + 正則 location 教訓)

---

## 十九、附錄

### 19.1 環境變量總清單

部署期間用到的：
```bash
# 部署過程
TOKEN=<32-hex-token>            # 訂閱 token (生成一次)
DOMAIN=example.duckdns.org         # 主域名

# 配置文件中
DUCKDNS_TOKEN=<duckdns-token>   # /etc/duckdns/duckdns.conf
TELEGRAM_BOT_TOKEN=<bot-token>  # /etc/telegram-bot.conf
TELEGRAM_CHAT_ID=<chat-id>      # /etc/telegram-bot.conf
```

### 19.2 端口分配

```
80     公網    nginx (HTTP → HTTPS 301)
443    公網    nginx (主入口)
2052   公網    shadowsocks-rust (雞霸王自用)
5000   127.0.0.1  ss-monitor Flask
8199   127.0.0.1  subs-check (內部 API, enable-web-ui=false)
22     公網    SSH
```

### 19.3 日誌路徑表

```
/var/log/subs-check-sync.log              ← sync-lza6
/var/log/subs-check-convert.log           ← convert-formats
/var/log/subs-check-incremental.log       ← incremental-check
/var/log/subs-check-notify.log            ← notify-telegram
/var/log/subs-check-fetcher.log           ← source-fetcher
/var/log/subs-check-recovery.log          ← weekly-recovery
/var/log/subs-check-cleanup.log           ← source-quality-history-cleanup
/var/log/subs-check-discover.log          ← discover-airports
/var/log/subs-check-audit-cleanup.log     ← audit-cleanup
/var/log/aicf-uptime-monitor.log          ← aicf 探活
/var/log/ssl-monitor.log                  ← SSL 證書監控
/var/log/duckdns-update.log               ← DuckDNS 推送
```

### 19.4 logrotate 配置

`/etc/logrotate.d/subs-check`：
```
/var/log/subs-check-*.log
/var/log/aicf-uptime-monitor.log
/var/log/ssl-monitor.log
/var/log/duckdns-update.log
{
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

### 19.5 監控指標 (建議告警)

| 指標 | 閾值 | 告警級別 |
|---|---|---|
| `example.duckdns.org` 連續 2 次 (60min) 失敗 | -- | warn |
| 證書 < 30 天 | -- | warn |
| 證書 < 7 天 | -- | crit |
| `subs-check` 內存 > 480M (94% MemoryMax) | -- | warn |
| `ss-monitor` 內存 > 47M (94%) | -- | warn |
| `convert-formats` 連續 3 次失敗 | -- | warn |
| 新一輪節點數 < 50 (正常 600+) | -- | warn |
| 黑名單源 > 30% (正常 < 10%) | -- | warn |

### 19.6 性能基線 (1.8GB RAM VPS)

| 操作 | 耗時 |
|---|---|
| `subs-check` 一輪 (80 源, 600 節點) | 4-5h |
| `sync-lza6` (有 ETag 短路) | 30s |
| `sync-lza6` (無 ETag 短路) | 2-3min |
| `convert-formats` (idempotent noop) | 2s |
| `convert-formats` (新一輪) | 10-15s |
| `incremental-check` (200 節點 TCP+TLS) | 1-2min |
| `discover-airports` (10 awesome + 6 topic) | 30-60min |
| `weekly-recovery` | 1s |

### 19.7 用語對照英中速查

| 中文 | 英文 | 養雞場 |
|---|---|---|
| 訂閱源 | subscription source | 飼料廠 |
| 節點 | proxy node | 一隻雞 |
| 黑名單 | blacklist | 屠宰場 |
| 候選 | candidate | 新雞 |
| 白名單 | whitelisted | 種雞 |
| 探活 | liveness probe | 摸鳥 |
| 評分 | score | 飼料 |
| 自動發現 | auto-discovery | 覓食 |

---

## 二十、版本歷史

| 日期 | 版本 | 說明 |
|---|---|---|
| 2026-05-25 | v1.0 | 初始部署 (節點 7:3 加權 + 連續 3 輪失敗黑名單) |
| 2026-05-26 | v2.3 | 滿分起步 + 4 源級 + 2 節點級拉黑觸發點 |
| 2026-05-27 02:00 | v2.3 + discover | 自動發現 (覓食) + ss-monitor 卡片 |
| 2026-05-27 07:00 | + i18n | 繁/簡/EN 三語 + 安全加固 + 拆 app.css/app.js |
| 2026-05-27 08:00 | + aicf | example.duckdns.org 主域名 + nginx vhost |
| 2026-05-27 09:00 | + cron 重構 | uptime 共享庫 + certbot deploy hook + duck.sh 4 域名 |
| 2026-05-27 10:00 | + UI v3 | 三檔限制 + 卡片摺疊 + 雞主題重命名 |
| 2026-05-27 11:00 | + UI v3.1 | 三檔回退鏈接 + 黑名單限制 + 評分分佈排序 |
| 2026-05-27 12:30 | 文檔終稿 | 此文檔 (專案改名 AI 養雞場) |

---

**文檔本身**: `<this-repo>/README.md`
**素材根**: `<this-repo>/snapshots/`
**部署根**: `/opt/subs-check/`, `/opt/ss-monitor/`
**主域名**: `https://example.duckdns.org/`
**緊急聯絡**: 看 `/etc/telegram-bot.conf` (Telegram bot 推送)

> AI 養雞場是長期維護的個人項目，所有改動進備份 + 驗證 + 文檔對齊。新人入坑先看本 README 第二章「系統總覽」+ 第十一章「1:1 部署步驟」。改動評分規則前必讀第五章 + 跑 dry-run 模擬器。
