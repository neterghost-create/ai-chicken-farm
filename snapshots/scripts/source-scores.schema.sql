CREATE TABLE sources (
    url TEXT PRIMARY KEY,
    first_seen TEXT,
    last_seen TEXT,
    last_in_subs_check TEXT,    -- 最后一次进 sub-urls.txt 的时间
    consecutive_fails INTEGER DEFAULT 0,
    total_checks INTEGER DEFAULT 0,
    total_passes INTEGER DEFAULT 0,
    score REAL DEFAULT 50.0,    -- 0-100
    note TEXT
, consecutive_passes INTEGER DEFAULT 0, status TEXT DEFAULT 'candidate', blocked_until TEXT, consecutive_low_quality INTEGER DEFAULT 0, first_seen_round INTEGER, low_score_total INTEGER DEFAULT 0);
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);
CREATE TABLE source_node_map (
    source_url TEXT NOT NULL,
    canonical_sig TEXT NOT NULL,
    first_seen_round INTEGER,
    last_seen_round INTEGER,
    PRIMARY KEY (source_url, canonical_sig)
);
CREATE TABLE source_quality_history (
    source_url TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    node_count INTEGER,                  -- 该源该轮提供了多少节点
    avg_quality_score REAL,              -- 节点级评分平均值
    below_50 INTEGER DEFAULT 0,          -- 这轮均分是否 <50 (布尔, 累计 5 轮就拉黑)
    PRIMARY KEY (source_url, round_id)
);
CREATE TABLE discovery_state (
    key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,           -- awesome_readme / github_topic / telegram_channel / source_audit
    url TEXT,                     -- 拉取入口 (audit 时是被审计的源 url)
    priority INTEGER DEFAULT 100,
    last_scanned_at TEXT,
    last_status TEXT,             -- ok / fail / skipped / quota / blocked
    last_added_count INTEGER DEFAULT 0,
    total_added_count INTEGER DEFAULT 0,
    consecutive_empty INTEGER DEFAULT 0,
    note TEXT,
    enabled INTEGER DEFAULT 1
);
CREATE TABLE source_audits (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL,
    audited_at TEXT NOT NULL,
    severity TEXT,                -- info / warn / critical
    finding TEXT,                 -- 简短诊断 (e.g. "ioc_hit:eval(", "html_response", "private_ip_redirect")
    detail_json TEXT
);
CREATE TABLE sqlite_sequence(name,seq);
CREATE INDEX idx_score ON sources(score DESC);
CREATE INDEX idx_status ON sources(status);
CREATE INDEX idx_snm_source ON source_node_map(source_url);
CREATE INDEX idx_snm_sig ON source_node_map(canonical_sig);
CREATE INDEX idx_sqh_source ON source_quality_history(source_url, round_id DESC);
CREATE INDEX idx_discovery_kind ON discovery_state(kind, priority);
CREATE INDEX idx_audit_source ON source_audits(source_url, audited_at DESC);
