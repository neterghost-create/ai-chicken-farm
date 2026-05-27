# 评分机制 v2.3 — 最终规则定稿

> **版本**: v2.3
> **定稿日期**: 2026-05-26
> **部署状态**: ✅ 已上线 (2026-05-26 18:40 CST)
> **部署时间戳**: `20260526_180329`
> **核心改动**: 满分起步 + 4 个源级拉黑触发点 + 2 个节点级拉黑触发点
> **v2.3 相对 v2.2 修订**:
> - 升白时清零所有计数器（漏洞 1 修复）
> - lq_node 判定仅由 convert-formats round 切换时触发，且仅本轮出现的节点参与（漏洞 2、3 修复）
> - 新增源级触发点 ④：score 累计低分 ≥ 15 拉黑（漏洞 4 修复）
> - source_quality_history 表 30 天清理 cron

---

## 一、源级评分（sources 表）

### 1.1 默认值

```python
score = 100.0
status = 'candidate'
consecutive_fails = 0           # 仅由网络硬故障累加
consecutive_passes = 0
consecutive_low_quality = 0     # 节点质量连续低累加（streak）
low_score_total = 0             # ★ v2.3 新增: score<30 累计轮数（不重置）
first_seen_round = NULL
```

### 1.2 信号 A — 网络可达性（sync-lza6, 每天 04:00）

| 事件 | score | fails | passes |
|------|------|------|------|
| 拉取失败（HTTP 4xx/5xx/timeout） | -15 | +1 | 0 |
| 拉取成功但 0 节点 | -10 | +1 | 0 |
| 拉取成功且 ≥1 节点 | 0 | 0 | +1 |

### 1.3 信号 B — 节点质量（update_source_quality, 每轮 round 切换）

5 轮窗口贡献节点均分：

| 均分 | score | low_quality (streak) | fails |
|------|------|------|------|
| ≥ 70 | 0 | 重置 0 | 不变 |
| 50-69 | -2 | +1 | 不变 |
| 30-49 | -5 | +1 | 不变 |
| < 30 | -10 | +1 | 不变 |
| 节点 < 5 不评估 | 0 | 重置 0 | 不变 |

### 1.4 信号 C — 周期恢复（每周日 03:00）

```sql
UPDATE sources SET score = MIN(100, score + 5)
WHERE status='candidate'
  AND consecutive_fails=0
  AND consecutive_low_quality=0
  AND low_score_total=0;        -- ★ v2.3: 累计低分清零的源才恢复
```

### 1.5 低分累计判定（每轮 round 切换，update_source_quality 之后执行）

```python
if score < 30:
    low_score_total += 1
# else: 保持累积, 不重置 (这是与 lq streak 的关键区别)
```

`low_score_total` 字段**只有在黑名单到期、升白、新源初始化时才重置**。

### 1.6 拉黑触发（4 个，按优先级）

```python
# ① candidate 网络硬故障 (streak)
if status == 'candidate' and consecutive_fails >= 3:
    blacklist(30 天)

# ② whitelisted 大量失败 (streak, 直接黑)
if status == 'whitelisted' and consecutive_fails >= 60:
    blacklist(30 天)

# ③ 持续低质量 (streak)
if consecutive_low_quality >= 5:
    blacklist(30 天)

# ④ 累计低分 (total) ★ v2.3 新增
if low_score_total >= 15:
    blacklist(30 天)
```

> **触发点功能矩阵**：
> - ①② = 网络层故障
> - ③ = 节点质量"连续低 5 轮"（持续垃圾源）
> - ④ = 综合分"累计低 15 轮"（忽好忽坏的间歇垃圾源）

### 1.7 升白触发（v2.3 修订：清零所有计数器）

```python
if status == 'candidate' and consecutive_passes >= 30:
    status = 'whitelisted'
    score = 100
    consecutive_fails = 0           # ★ v2.3 补充
    consecutive_low_quality = 0     # ★ v2.3 补充
    low_score_total = 0             # ★ v2.3 新增字段, 升白时清零
```

### 1.8 黑名单到期（30 天）— 完整复活

```python
status = 'candidate'
score = 100
consecutive_fails = 0
consecutive_passes = 0
consecutive_low_quality = 0
low_score_total = 0                  # ★ v2.3 新增字段, 到期清零
first_seen_round = current_round     # 重置 grace 期 (如沿用)
```

---

## 二、节点级评分（nodes_history 表）

### 2.1 默认值

```python
quality_score = 100.0
consecutive_fails = 0                    # 探活/测速超时计数
consecutive_low_quality_node = 0         # 持续低质计数（仅本轮出现节点累加）
blacklisted_until = NULL
```

### 2.2 信号 A — 探活（每小时 :15, incremental-check.py）

| 事件 | quality_score | fails |
|------|------|------|
| 探活失败（TCP/TLS 不通） | -10 | +1 |
| 探活通过 | +3 | 重置 0 |

⚠️ **incremental-check.py 不触发 lq_node 判定**，只更新 score 和 fails。

### 2.3 信号 B — 轮次（subs-check 每轮）

| 事件 | quality_score | fails |
|------|------|------|
| 本轮未出现 | -3 | 不变 |
| 本轮出现 | +2 | — |
| 出现 + 连续 ≥5 | 额外 +3（叠加） | — |

### 2.4 信号 C — 测速（subs-check 测了速）

| KB/s | quality_score | fails |
|------|------|------|
| ≥ 2048 | +3 | — |
| 1024-2047 | 0 | — |
| 512-1023 | -3 | — |
| 100-511 | **-12** ★ v2.2 加大 | 不变 |
| < 100 | -15 | 不变 |
| 测速超时 | -10 | +1 |

> 同轮多信号可叠加，最终 cap 在 [0, 100]

### 2.5 持续低质判定（v2.3 修订：限定执行点 + 范围）

```python
# 仅在 convert-formats.py 检测到 round_id 变化时执行 (一轮一次)
if new_round_detected:
    重算所有节点 quality_score    # 含信号 ABC 累积

    # ★ v2.3 关键: 只有本轮出现的节点参与 lq_node 判定
    for node where last_round_id == current_round:
        if node.quality_score < 30:
            node.consecutive_low_quality_node += 1
        else:
            node.consecutive_low_quality_node = 0

    # 拉黑判定
    for node where consecutive_low_quality_node >= 5:
        blacklist 48h
```

⚠️ **incremental-check.py 第 213-230 行的 quality_score 重算 SQL 不触发 lq_node 判定**，只更新 score 字段。

### 2.6 拉黑触发（2 个）

```python
# ① 真故障 (探活失败 / 测速超时累计)
if consecutive_fails >= 4:
    blacklisted_until = now + 48h

# ② 持续低质量 (本轮出现 AND score<30 持续 5 轮)
if consecutive_low_quality_node >= 5:
    blacklisted_until = now + 48h
```

### 2.7 黑名单到期（48h）— 完整复活

```python
blacklisted_until = NULL
quality_score = 100
consecutive_fails = 0
consecutive_low_quality_node = 0
```

### 2.8 死亡淘汰

```python
if current_round - last_round_id > 30:    # ≈7 天
    DELETE FROM nodes_history
```

---

## 三、80 源轮询 v3

```sql
-- 1. 用户白名单 (永久, 来自 sub-urls-whitelist.txt)

-- 2. status='whitelisted'
SELECT url FROM sources WHERE status='whitelisted'
ORDER BY score DESC, consecutive_passes DESC, total_passes DESC;

-- 3. 探索预算 (新源, 完全没测过的)
SELECT url FROM sources WHERE status='candidate' AND total_checks=0
ORDER BY first_seen ASC, url ASC;

-- 4. 公平轮训 + 低分翻身 (已测过的 candidate)
SELECT url FROM sources WHERE status='candidate' AND total_checks>0
ORDER BY total_checks ASC,        -- 公平: 测得越少越优先
         score ASC,                -- 同次数下低分优先翻身
         consecutive_passes DESC,  -- 同分下长期稳定优先
         first_seen ASC;
```

每层都隐含 `WHERE status != 'blacklisted'`，黑名单永远跳过。

---

## 四、Schema 迁移 SQL

```sql
-- 节点表新增字段
ALTER TABLE nodes_history ADD COLUMN consecutive_low_quality_node INTEGER DEFAULT 0;

-- 源表新增字段 ★ v2.3
ALTER TABLE sources ADD COLUMN low_score_total INTEGER DEFAULT 0;

-- 源表全部 score 重置 100 (黑名单不强制解封, 等 TTL)
UPDATE sources SET
    score = 100.0,
    consecutive_fails = 0,
    consecutive_passes = 0,
    consecutive_low_quality = 0,
    low_score_total = 0
WHERE status != 'blacklisted';

-- 节点表 score 重置 100 (黑名单不强制解封, 等 48h TTL)
UPDATE nodes_history SET
    quality_score = 100.0,
    consecutive_fails = 0,
    consecutive_low_quality_node = 0
WHERE blacklisted_until IS NULL OR blacklisted_until < datetime('now');
```

---

## 五、配置常量速查

```python
# === sync-lza6.py ===
SOURCE_DEFAULT_SCORE = 100              # 50 → 100
SOURCE_FETCH_FAIL_PENALTY = 15
SOURCE_PARSE_EMPTY_PENALTY = 10
FAIL_THRESHOLD_CANDIDATE = 3
FAIL_THRESHOLD_WHITELIST = 60
PASS_THRESHOLD_PROMOTE = 30
SOURCE_BLACKLIST_DAYS = 30
WEEKLY_RECOVERY_AMOUNT = 5

# === convert-formats.py (源级) ===
SOURCE_QUALITY_PENALTY_LOW = 2          # 50-69
SOURCE_QUALITY_PENALTY_MID = 5          # 30-49
SOURCE_QUALITY_PENALTY_HIGH = 10        # <30
SOURCE_KILL_AFTER_LOW_ROUNDS = 5        # ③ lq streak 阈值
SOURCE_KILL_AFTER_LOW_TOTAL = 15        # ★ v2.3: ④ low_score_total 阈值
SOURCE_LOW_SCORE_THRESHOLD = 30         # ★ v2.3: 低分判定阈值
MIN_NODES_FOR_QUALITY_EVAL = 5

# === convert-formats.py + incremental-check.py (节点级) ===
NODE_DEFAULT_SCORE = 100                # 50 → 100
NODE_FAIL_THRESHOLD = 4                 # 3 → 4
NODE_BLACKLIST_HOURS = 48
NODE_LOW_QUALITY_THRESHOLD = 30         # 节点低质判定阈值
NODE_KILL_AFTER_LOW_ROUNDS = 5

# 探活
NODE_PROBE_FAIL_PENALTY = 10
NODE_PROBE_PASS_BONUS = 3

# 轮次
NODE_ABSENT_PENALTY = 3
NODE_PRESENT_BONUS = 2
NODE_CONSECUTIVE_BONUS = 3

# 测速
NODE_SPEED_HIGH_BONUS = 3               # ≥2048 KB/s
NODE_SPEED_LOW_PENALTY = 3              # 512-1023
NODE_SPEED_VLOW_PENALTY = 12            # ★ v2.2: 100-511 (原 -8)
NODE_SPEED_DEAD_PENALTY = 15            # <100
NODE_SPEED_TIMEOUT_PENALTY = 10

# === 新 cron ===
# 0 3 * * 0  weekly-recovery.py                  # 周日 03:00 周期恢复
# 33 4 * * * source-quality-history-cleanup.py   # 每天 04:33 清理 30 天前数据 (错开 04:30 openclaw-restart)
```

---

## 六、行为预测时序

### 6.1 慢节点拉黑（200 KB/s, 假设连续出现）

每轮：出现+2 + 测速-12 = 净 -10；第 5 轮起加连续奖励 +3 = 净 -7

| 轮 | quality_score | lq_node | 状态 |
|----|------|------|------|
| 1-4 | 90→80→70→60 | 0 | active |
| 5-8 | 53→46→39→32 | 0 | active |
| 9 | 25 | 1 | active |
| 10 | 18 | 2 | active |
| 11 | 11 | 3 | active |
| 12 | 4 | 4 | active |
| **13** | **0** | **5** | **🔒 BLACKLIST 48h** |

实际拉黑时间: 13 轮 ≈ 3.25 天

### 6.2 极慢节点（< 100 KB/s）

约 10 轮 ≈ 2.5 天

### 6.3 中等慢节点（512-1023 KB/s）

70 轮 ≈ 17 天 — 实际不会被拉黑（合理）

### 6.4 优秀节点（≥1024 KB/s）

**永远不会被拉黑** ✅

### 6.5 忽好忽坏源（v2.3 新场景）

一轮均分 25（lq+1, score-10），一轮均分 75（lq=0, score+0）

| 轮 | 均分 | score | lq | low_score_total | 触发 |
|----|------|------|------|------|------|
| 1-13 | 交替 | 100→…→30 | 0/1 跳 | 0 | 不触发 ③、score 还没<30 |
| 14 | 25 | 20 | 1 | **1** | low_score 累加 |
| 16 | 25 | 10 | 1 | **2** | |
| 18 | 25 | 0 | 1 | **3** | |
| ... | | | | | 每 2 轮 +1 |
| **42** | 25 | 0 | 1 | **15** | **🔒 ④ 触发拉黑 30 天** |

约 42 轮 ≈ 10.5 天拉黑（合理：忽好忽坏给充足观察期）

### 6.6 持续垃圾源（v2.2 验证）

| 轮 | 均分 | score | lq | 触发 |
|----|------|------|------|------|
| 1 | 25 | 90 | 1 | |
| 2 | 25 | 80 | 2 | |
| 3 | 25 | 70 | 3 | |
| 4 | 25 | 60 | 4 | |
| **5** | 25 | 50 | **5** | **🔒 ③ 触发拉黑** |

5 轮 ≈ 1.25 天（快速处理）

---

## 七、自检清单（v2.3）

| 检查项 | 状态 | 说明 |
|------|------|------|
| 源不会因节点质量被直接拖黑 | ✅ | 源 fails 仅"网络硬故障"累加 |
| 源会因持续节点低质拉黑 | ✅ | ③ lq streak ≥ 5（约 1.25 天）|
| 源会因间歇低分拉黑（忽好忽坏） | ✅ | ④ low_score_total ≥ 15（约 10.5 天）★ v2.3 |
| 节点会因真故障拉黑 | ✅ | ① fails ≥ 4 |
| 节点会因持续低质拉黑 | ✅ | ② lq_node ≥ 5（约 3.25 天）|
| 节点未出现不冤死 | ✅ | last_round_id == current_round 才参与判定 ★ v2.3 |
| 慢节点不会被探活通过冤死 | ✅ | 探活只清 fails, 不清 lq_node |
| 黑名单到期完整复活 | ✅ | score + 所有计数器都重置 |
| 升白时清零计数器 | ✅ | ★ v2.3 修订 |
| 新源公平 | ✅ | 100 满分起步 + 探索预算层 |
| 死源自动淘汰 | ✅ | 30 轮没出现 DELETE |
| 80 源轮询保证 | ✅ | 4 层兜底, candidate≥80 时必满 |
| 低分源翻身机会 | ✅ | 同 total_checks 下 score ASC |
| 黑名单循环消除 | ✅ | 30 天到期 score 重置 100 |
| 4 个源触发点功能区分 | ✅ | ①② 网络层, ③ streak 持续, ④ total 累计 |
| lq_node 判定不重复触发 | ✅ | 仅 convert-formats round 切换时执行 ★ v2.3 |
| source_quality_history 不无限增长 | ✅ | ★ v2.3: 30 天清理 cron |

---

## 八、实施清单（待执行）

### Phase 0 - 准备
- [ ] 备份 source-scores.db, history.db (.bak.YYYYMMDD_HHMMSS)
- [ ] 备份 sync-lza6.py, convert-formats.py, incremental-check.py

### Phase 1 - 单元测试 + dry-run（不动生产）
- [ ] 写测试用例覆盖所有触发点 + 自检清单全部场景
- [ ] 写 dry-run 模拟器：用历史数据跑新规则，对比新旧拉黑/score 输出
- [ ] 评估迁移影响（多少源会即时拉黑、多少节点会即时拉黑）

### Phase 2 - 代码改造
- [ ] 写 weekly-recovery.py 脚本
- [ ] 写 source-quality-history-cleanup.py 脚本
- [ ] 改 sync-lza6.py: 默认值 100, 减分表, 拉黑触发 ①②
- [ ] 改 convert-formats.py:
  - 删除旧 calc_quality_score 加权公式
  - 改为信号 ABC 累积 + 单向减分
  - 加 lq_node 判定（仅 round 切换 + 仅本轮出现节点）
  - 加 low_score_total 累加 + ④ 拉黑判定
- [ ] 改 incremental-check.py: 探活信号写法（fails 累加规则更新，不动 lq_node）

### Phase 3 - DB 迁移
- [ ] ALTER TABLE 加新字段
- [ ] UPDATE 重置 score 100

### Phase 4 - 部署
- [ ] 加 cron: 周日 03:00 weekly-recovery, 04:33 history cleanup
- [ ] 重启 subs-check / 等下一个 cron 周期
- [ ] 观察 24h，看 sync-lza6 / convert-formats 行为

### Phase 5 - 观察期
- [ ] 一周后看真实拉黑数据（多少源/节点被 ③ ④ 触发）
- [ ] 调整阈值（如有必要）

---

## 九、回滚预案

```bash
#!/bin/bash
# 一键回滚 v2.3 → 旧版
TS=$(date +%Y%m%d_%H%M%S)
echo "回滚时间戳: $TS"

cd /opt/subs-check/scripts

# 恢复 DB
cp source-scores.db source-scores.db.failed_v2.$TS  # 失败版备份
cp source-scores.db.bak.PRE_V2 source-scores.db
cp history.db history.db.failed_v2.$TS
cp history.db.bak.PRE_V2 history.db

# 恢复脚本
cp sync-lza6.py.bak.PRE_V2 sync-lza6.py
cp convert-formats.py.bak.PRE_V2 convert-formats.py
cp incremental-check.py.bak.PRE_V2 incremental-check.py

# 移除新 cron
crontab -l | grep -v weekly-recovery | grep -v history-cleanup | crontab -

# 重启
systemctl restart subs-check
```

⚠️ **回滚前提**：在 Phase 0 备份时必须用统一标签 `PRE_V2`，便于一键恢复。

---

## 十、决策追溯（用户拍板记录）

| # | 议题 | 用户决策 |
|---|------|------|
| 0 | 评分制式 | 满分 100 起步, 单向减分 |
| 1 | 节点未出现是否算 fails | C 不算（只扣 score） |
| 2 | 节点测速慢是否算 fails | 改用方案 C 持续低质拉黑路径 |
| 3 | 节点黑白二态 vs 分级 | 直接拉黑, 按解封规则重新计算 |
| 4 | 迁移已测过的源 | A 全部重置 100 |
| 5 | 80 源保证 | 每轮 80, 评分低再次循环 |
| 6 | 1D vs 低分翻身 | 保留低分翻身排序 + 拉黑兜底僵尸源 |
| 7 | 升白源失败 60 次 | 直接黑（无 candidate 缓冲） |
| 8 | 周期恢复差异化 | D 加 consecutive_passes DESC 排序键 |
| 9 | 节点持续低质处理 | 方案 C: 引入 lq_node, 直接拉黑 48h |
| 10 | 慢节点拉黑速度 | E 加大 100-511 档扣分 -8→-12 |
| 11 | 节点未出现是否算 lq | B 仅本轮出现节点参与判定 ★ v2.3 |
| 12 | 忽好忽坏源处理 | B 引入触发点 ④ ★ v2.3 |
| 13 | 低分判定阈值 | C score<30（与节点级统一）|
| 14 | streak vs total | B 双保险：streak ≥ 5 OR total ≥ 15 |
| 15 | ③ ④ 关系 | C 分工：③ lq streak, ④ score total |

---

## 十一、部署记录 (2026-05-26 18:40 CST)

### 部署阶段（D → A → B 全流程）

| 阶段 | 状态 | 关键操作 |
|------|------|---------|
| Phase D dry-run | ✅ | `dryrun-v2.3.py` 模拟 0 立即拉黑, 33 慢节点 30 轮内拉黑 |
| Phase A 观察 | ⏳ | 后台 cron 自动跑, 每天 04:00 跑 sync-lza6 |
| Phase B0 备份 | ✅ | `.bak.PRE_V2.20260526_180329` (10 个文件) |
| Phase B1 DB 迁移 | ✅ | ALTER + 全量重置 184 源 + 2018 节点 |
| Phase B2 incremental-check | ✅ | 探活 ±10/+3, fails ≥4 拉黑 |
| Phase B3 convert-formats | ✅ | calc_round_delta + apply_lq_node_and_blacklist + 触发 ③④ |
| Phase B4 sync-lza6 | ✅ | 默认 100 + score-15 + 触发 ①② + 选源 v3 |
| Phase B5 weekly-recovery | ✅ | 周日 03:00 cron |
| Phase B6 history-cleanup | ✅ | 每天 04:33 cron (2026-05-27 错开 04:30 调整) |
| Phase B7 ss-monitor api.py | ✅ | rules_version=v2.3, 新字段全返回 |
| Phase B8 ss-monitor index.html | ✅ | scorePillClass 阈值, 卡片文案 v2.3 |
| Phase B9 重启 + 公网验证 | ✅ | HTTP 200, 文案显示正确 |

### 上线后即时数据

| 项 | 值 |
|----|----|
| 源总数 | 184 (全 candidate, score=100) |
| 节点总数 | 2035 |
| 节点 score=100 | 2018 (99.2%) |
| 节点黑名单中 | 17 (旧黑名单等 48h TTL) |
| source_node_map | 66031 (跨源-节点映射) |
| nodes_history score 90-100 | 2012 |
| nodes_history score 70-89 | 6 |
| 当前 round_id | 5 |
| ss-monitor 内存 | 24.8M / 96M (健康) |
| 公网响应 | HTTP 200, 78KB, 36ms |

### 已固化的资产

```
/opt/subs-check/scripts/SCORING_RULES_v2.md       # 本文档 (v2.3 终版)
/opt/subs-check/scripts/dryrun-v2.3.py             # 纯只读模拟器
/opt/subs-check/scripts/weekly-recovery.py         # 周期恢复
/opt/subs-check/scripts/source-quality-history-cleanup.py  # 历史清理
~/.hermes/skills/devops/subs-check-scoring-v23/    # Hermes skill 维护手册
```

### 备份文件清单 (一键回滚用)

```
/opt/subs-check/scripts/source-scores.db.bak.PRE_V2.20260526_180329
/opt/subs-check/scripts/history.db.bak.PRE_V2.20260526_180329
/opt/subs-check/scripts/sync-lza6.py.bak.PRE_V2.20260526_180329
/opt/subs-check/scripts/convert-formats.py.bak.PRE_V2.20260526_180329
/opt/subs-check/scripts/incremental-check.py.bak.PRE_V2.20260526_180329
/opt/ss-monitor/api.py.bak.PRE_V2.20260526_180329
/opt/ss-monitor/index.html.bak.PRE_V2.20260526_180329
/tmp/crontab.bak.PRE_V2.20260526_180329
```

### 接下来 7 天的自动行为预期

| 时间 | 触发 | 预期效果 |
|------|------|---------|
| 18:30 起每 30min | convert-formats | 节点/源继续累积 v2.3 信号 |
| 每小时 :15 | incremental-check | 探活信号触发 |
| 明早 04:00 | sync-lza6 状态机首跑 | 观察是否有源被 ① 拉黑 |
| 明早 04:33 | history-cleanup | 清空 30 天前 history 数据 |
| 周日 03:00 | weekly-recovery | 第一次周期恢复 +5 |
| 7-10 天 | 触发点 ④ 首次激活 | 忽好忽坏源累积 low_score_total ≥ 15 |
| 14 天 | 评分稳态 | candidate 池 score 真实分布 |

### 监控查询语句

```bash
# 每日早查 (建议加到 cron 04:35)
journalctl -u subs-check --since "04:00" -o cat | grep -E "拉黑|ERR" | head

# 触发点累计统计
sqlite3 /opt/subs-check/scripts/source-scores.db <<SQL
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN consecutive_fails >= 1 THEN 1 ELSE 0 END) as has_fails,
  SUM(CASE WHEN consecutive_low_quality >= 1 THEN 1 ELSE 0 END) as has_lq,
  SUM(CASE WHEN low_score_total >= 1 THEN 1 ELSE 0 END) as has_lst,
  SUM(CASE WHEN status='blacklisted' THEN 1 ELSE 0 END) as blacklisted
FROM sources;
SQL

# 节点拉黑趋势
sqlite3 /opt/subs-check/scripts/history.db <<SQL
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN consecutive_fails >= 1 THEN 1 ELSE 0 END) as has_fails,
  SUM(CASE WHEN consecutive_low_quality_node >= 1 THEN 1 ELSE 0 END) as has_lq_node,
  SUM(CASE WHEN blacklisted_until IS NOT NULL THEN 1 ELSE 0 END) as blacklisted
FROM nodes_history;
SQL
```

---

## 十二、上线后修复记录

### Hotfix 1 (2026-05-26 18:50): 测速 21 个节点显示 —

**根因**: `convert-formats.py:extract_speed_from_name` 正则只匹配 `KB/s` 不匹配 `MB/s`,
导致带 `1.0MB/s` 命名的好节点 `speed_kbps=None`, 监控页显示 —, 历史均速一直 0.

**修复**: 同时支持两种单位:
```python
# KB/s
m = re.search(r'\|(\d+(?:\.\d+)?)KB/s', name)
if m: return int(float(m.group(1)))
# MB/s → KB/s
m = re.search(r'\|(\d+(?:\.\d+)?)MB/s', name)
if m: return int(float(m.group(1)) * 1024)
return None
```

**验证**: 单元测试 8 个 case 全过, force 重跑后 `speed_kbps=None` 从 21 → 0.

### Hotfix 2 (2026-05-26 18:50): 轮次趋势用箭头代替 Δ 符号

**改动**: `index.html` 历史趋势 + diff 区块视觉化:
- `Δ+12` (绿) → `↑+12` (绿)
- `Δ-3` (红) → `↓-3` (红)
- `Δ0` (灰) → `·0` (灰)
- diff: `+593/−592` → `↑+593/↓-592`

**生效**: 静态 HTML, nginx no-cache, 浏览器刷新立即可见, 无需重启服务.
