CREATE TABLE rounds (
    round_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    yaml_mtime TEXT NOT NULL,           -- all.yaml 的 mtime, 同 mtime 不重复入库
    total_nodes INTEGER,
    protocols_json TEXT,                -- {"vless":210,...}
    nodes_hash TEXT,                    -- 当前轮节点集合的稳定哈希
    diff_added INTEGER DEFAULT 0,
    diff_removed INTEGER DEFAULT 0,
    diff_kept INTEGER DEFAULT 0,
    notified INTEGER DEFAULT 0          -- Telegram 是否已推送
);
CREATE TABLE sqlite_sequence(name,seq);
CREATE UNIQUE INDEX idx_rounds_mtime ON rounds(yaml_mtime);
CREATE INDEX idx_rounds_ts ON rounds(timestamp DESC);
CREATE TABLE nodes_history (
    canonical_sig TEXT PRIMARY KEY,    -- server:port:type, 跨 cdn 同主机视为同节点
    first_seen TEXT,
    last_seen TEXT,
    last_speed_kbps INTEGER,           -- 上一次测速结果
    avg_speed_kbps REAL DEFAULT 0,     -- 历史均值
    total_appearances INTEGER DEFAULT 0,    -- 出现轮次数
    consecutive_appearances INTEGER DEFAULT 0,  -- 连续出现轮次
    consecutive_fails INTEGER DEFAULT 0,    -- 增量测试连续失败次数
    incremental_pass INTEGER DEFAULT 0,     -- 增量测试通过次数
    incremental_fail INTEGER DEFAULT 0,     -- 增量测试失败次数
    blacklisted_until TEXT,            -- 节点级黑名单到期 (48h)
    quality_score REAL DEFAULT 50.0,   -- 综合质量分 (0-100)
    last_round_id INTEGER,             -- 最后出现的 round_id
    region TEXT,
    protocol TEXT,
    sample_name TEXT                   -- 最近一次的展示名
, consecutive_low_quality_node INTEGER DEFAULT 0);
CREATE INDEX idx_nodes_score ON nodes_history(quality_score DESC);
CREATE INDEX idx_nodes_blacklist ON nodes_history(blacklisted_until);
