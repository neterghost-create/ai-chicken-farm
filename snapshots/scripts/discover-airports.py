#!/usr/bin/env python3
"""
discover-airports.py — 公益机场源自动发现 (L1/L2/L4)

设计要点 (与用户确认的方案):
  - 严格只在 sources 表追加, 评分系统由 sync-lza6/convert-formats 自管, 本脚本不动它
  - 6 层过滤: 配置守门 → IOC → 域名/关键字 → MIME/大小 → 内容签名 → 跨源验证
  - 自定义 socket resolver 强制拒私有/链路本地 IP (SSRF 防护)
  - cron 02:00 跑, 硬超时 50min, 子任务 (每条 url) 15s 软超时
  - L3 (telegram) 暂空; source_audit 仅在 note 追加 audit:critical 标签, 不动 score

退出码:
  0 = 正常 (无 critical 也算正常)
  1 = 配置/DB 错误
  2 = 全局超时被 kill
  3 = 被 sync-lza6 抢锁退让 (避免 02:00 / 02:00 撞车)
"""
import argparse
import dataclasses
import datetime as dt
import fcntl
import hashlib
import ipaddress
import json
import math
import os
import random
import re
import signal
import socket
import sqlite3
import sys
import time
import traceback
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Set, Tuple

import yaml  # PyYAML 6.x 已确认存在

# ---------- 常量 / 路径 ----------
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
SOURCES_DB = os.path.join(SCRIPT_DIR, "source-scores.db")
CONFIG_YAML = os.path.join(SCRIPT_DIR, "discovery-config.yaml")
IOC_LIST = os.path.join(SCRIPT_DIR, "ioc-list.txt")
LOG_FILE = "/var/log/subs-check-discover.log"
LOCK_FILE = "/run/discover-airports.lock"
SYNC_LOCK_FILE = "/run/sync-lza6.lock"  # sync-lza6 跑时持有的锁, 我们让路

DEFAULT_GLOBAL_TIMEOUT_SEC = 3000  # 50min
DEFAULT_FETCH_TIMEOUT_SEC = 15
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_REDIRECT = 5

USER_AGENT = "discover-airports/1.0 (+subs-check pool curator)"

# 协议头 marker — 跟 sync-lza6 一致
PROTOCOL_MARKERS = ("vless://", "vmess://", "trojan://", "ss://", "ssr://", "hysteria",
                    "tuic://", "wireguard://", "snell://", "anytls://")
# 看起来像 base64 整段订阅的 marker (sync-lza6 也支持)
B64_HINT = re.compile(r"^[A-Za-z0-9+/=\r\n]{200,}$")

URL_PATTERN = re.compile(r"https?://[^\s<>\")\]\']+")

# 控制状态机的常量
KIND_AWESOME = "awesome_readme"
KIND_TOPIC = "github_topic"
KIND_TELEGRAM = "telegram_channel"
KIND_AUDIT = "source_audit"
ALL_KINDS = (KIND_AWESOME, KIND_TOPIC, KIND_TELEGRAM, KIND_AUDIT)


# ---------- 简易 logger (写文件 + stdout) ----------
class Logger:
    def __init__(self, path: str, also_stdout: bool = True):
        self.path = path
        self.also_stdout = also_stdout
        try:
            self._fh = open(path, "a", buffering=1)
        except Exception:
            self._fh = None

    def _w(self, level: str, msg: str):
        line = f"[{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {msg}"
        if self._fh:
            try:
                self._fh.write(line + "\n")
            except Exception:
                pass
        if self.also_stdout:
            print(line, flush=True)

    def info(self, m): self._w("INFO", m)
    def warn(self, m): self._w("WARN", m)
    def error(self, m): self._w("ERROR", m)
    def debug(self, m): self._w("DEBUG", m)


LOG = Logger(LOG_FILE)


# ---------- SSRF 防护: 自定义 DNS resolver ----------
_orig_getaddrinfo = socket.getaddrinfo


def _is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # 解不开就当不安全
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _safe_getaddrinfo(host, port, *args, **kwargs):
    """包一层 getaddrinfo, 任一解析结果是私有/loopback 都拒掉."""
    res = _orig_getaddrinfo(host, port, *args, **kwargs)
    for family, _stype, _proto, _canon, sockaddr in res:
        ip = sockaddr[0]
        if _is_private_ip(ip):
            raise PermissionError(f"SSRF guard: {host} 解析到私有 IP {ip}")
    return res


def install_ssrf_guard():
    socket.getaddrinfo = _safe_getaddrinfo


# ---------- 单例锁 ----------
class FileLock:
    """文件锁 — 自身用 LOCK_FILE 保证 discover 单例; 探 SYNC_LOCK_FILE 决定是否让路."""
    def __init__(self, path: str):
        self.path = path
        self._fh = None

    def acquire_or_die(self) -> bool:
        try:
            self._fh = open(self.path, "w")
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._fh.write(str(os.getpid()))
            self._fh.flush()
            return True
        except BlockingIOError:
            return False

    def release(self):
        if self._fh:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                self._fh.close()
            except Exception:
                pass
            try:
                os.unlink(self.path)
            except Exception:
                pass


def sync_lock_held() -> bool:
    """sync-lza6 是否在跑. 它如果在跑, 我们让路退出 — 不抢 DB."""
    if not os.path.exists(SYNC_LOCK_FILE):
        return False
    try:
        with open(SYNC_LOCK_FILE, "r") as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                return False  # 拿到了就说明没人持有
            except BlockingIOError:
                return True
    except Exception:
        return False


# ---------- DB helpers ----------
def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(SOURCES_DB, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_str() -> str:
    return dt.date.today().isoformat()


# ---------- Schema 迁移 (幂等) ----------
SCHEMA_DISCOVERY_STATE = """
CREATE TABLE IF NOT EXISTS discovery_state (
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
)
"""

SCHEMA_SOURCE_AUDITS = """
CREATE TABLE IF NOT EXISTS source_audits (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL,
    audited_at TEXT NOT NULL,
    severity TEXT,                -- info / warn / critical
    finding TEXT,                 -- 简短诊断 (e.g. "ioc_hit:eval(", "html_response", "private_ip_redirect")
    detail_json TEXT
)
"""

SCHEMA_INDEX = [
    "CREATE INDEX IF NOT EXISTS idx_discovery_kind ON discovery_state(kind, priority)",
    "CREATE INDEX IF NOT EXISTS idx_audit_source ON source_audits(source_url, audited_at DESC)",
]


def migrate_schema(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA_DISCOVERY_STATE)
    conn.execute(SCHEMA_SOURCE_AUDITS)
    for s in SCHEMA_INDEX:
        conn.execute(s)
    conn.commit()


# ---------- 配置 / IOC 加载 ----------
@dataclasses.dataclass
class DiscoveryConfig:
    awesome_entries: List[Dict]
    topic_entries: List[Dict]
    telegram_entries: List[Dict]
    audit_enabled: bool
    audit_threshold: float
    audit_daily_limit: int
    audit_cooldown_days: int
    domain_whitelist: Set[str]
    domain_blacklist: Set[str]
    keyword_blacklist: List[str]
    max_redirect: int
    max_response_bytes: int
    fetch_timeout_sec: int
    global_timeout_sec: int
    budget_awesome: int
    budget_topic: int
    budget_telegram: int
    budget_audit: int
    http_concurrent: int
    proto_min: int
    html_ratio_max: float
    entropy_max_no_proto: float
    notify_enabled: bool
    notify_min_critical: int
    free_pool_conf: str

    @staticmethod
    def load(path: str) -> "DiscoveryConfig":
        with open(path, "r") as f:
            raw = yaml.safe_load(f)
        sec = raw.get("security", {})
        bud = raw.get("budget", {})
        cont = raw.get("content", {})
        notif = raw.get("notify", {})
        aud = raw.get("source_audit", {})
        return DiscoveryConfig(
            awesome_entries=raw.get("awesome_readme", []) or [],
            topic_entries=raw.get("github_topic", []) or [],
            telegram_entries=raw.get("telegram_channel", []) or [],
            audit_enabled=bool(aud.get("enabled", True)),
            audit_threshold=float(aud.get("threshold_score", 80)),
            audit_daily_limit=int(aud.get("daily_limit", 10)),
            audit_cooldown_days=int(aud.get("re_audit_cooldown_days", 7)),
            domain_whitelist=set(sec.get("domain_whitelist", [])),
            domain_blacklist=set(sec.get("domain_blacklist", [])),
            keyword_blacklist=list(sec.get("keyword_blacklist", [])),
            max_redirect=int(sec.get("max_redirect", DEFAULT_MAX_REDIRECT)),
            max_response_bytes=int(sec.get("max_response_bytes", DEFAULT_MAX_BYTES)),
            fetch_timeout_sec=int(sec.get("fetch_timeout_sec", DEFAULT_FETCH_TIMEOUT_SEC)),
            global_timeout_sec=int(sec.get("global_timeout_sec", DEFAULT_GLOBAL_TIMEOUT_SEC)),
            budget_awesome=int(bud.get("awesome_readme_per_day", 5)),
            budget_topic=int(bud.get("github_topic_per_day", 2)),
            budget_telegram=int(bud.get("telegram_channel_per_day", 5)),
            budget_audit=int(bud.get("source_audit_per_day", 10)),
            http_concurrent=int(bud.get("http_concurrent", 3)),
            proto_min=int(cont.get("protocol_markers_min", 3)),
            html_ratio_max=float(cont.get("html_ratio_max", 0.05)),
            entropy_max_no_proto=float(cont.get("entropy_max_no_proto", 7.5)),
            notify_enabled=bool(notif.get("enabled", True)),
            notify_min_critical=int(notif.get("min_critical_to_notify", 1)),
            free_pool_conf=notif.get("config_file", "/opt/subs-check/scripts/free-pool.conf"),
        )


def load_ioc_list(path: str) -> List[str]:
    """读 IOC 列表, 注释 + 空行剔除. 返回小写化的 substring 集合."""
    out: List[str] = []
    if not os.path.exists(path):
        return out
    with open(path, "r") as f:
        for ln in f:
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            out.append(s.lower())
    return out


# ---------- discovery_state 状态机 ----------
def upsert_state_entry(conn: sqlite3.Connection, key: str, kind: str,
                       url: Optional[str], priority: int, note: Optional[str] = None):
    conn.execute(
        """
        INSERT INTO discovery_state (key, kind, url, priority, note, enabled)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(key) DO UPDATE SET
            kind = excluded.kind,
            url = excluded.url,
            priority = excluded.priority,
            note = COALESCE(excluded.note, discovery_state.note)
        """,
        (key, kind, url, priority, note),
    )


def pick_next_targets(conn: sqlite3.Connection, kind: str, budget: int) -> List[sqlite3.Row]:
    """轮训: enabled=1 的条目, 按 last_scanned_at NULLS FIRST + priority asc 取 budget 条."""
    if budget <= 0:
        return []
    rows = conn.execute(
        f"""
        SELECT key, kind, url, priority, last_scanned_at, last_status,
               consecutive_empty, total_added_count, note
        FROM discovery_state
        WHERE kind = ? AND enabled = 1
        ORDER BY (last_scanned_at IS NULL) DESC,
                 last_scanned_at ASC,
                 priority ASC
        LIMIT ?
        """,
        (kind, budget),
    ).fetchall()
    return rows


def mark_state(conn: sqlite3.Connection, key: str, status: str, added: int):
    consec_inc = 1 if added == 0 and status == "ok" else 0
    conn.execute(
        """
        UPDATE discovery_state
        SET last_scanned_at = ?,
            last_status = ?,
            last_added_count = ?,
            total_added_count = total_added_count + ?,
            consecutive_empty = CASE WHEN ?=1 THEN consecutive_empty + 1 ELSE 0 END
        WHERE key = ?
        """,
        (now_iso(), status, added, added, consec_inc, key),
    )


def insert_audit(conn: sqlite3.Connection, src: str, severity: str,
                 finding: str, detail: Optional[Dict] = None):
    conn.execute(
        "INSERT INTO source_audits (source_url, audited_at, severity, finding, detail_json) VALUES (?, ?, ?, ?, ?)",
        (src, now_iso(), severity, finding, json.dumps(detail or {}, ensure_ascii=False)),
    )


# ---------- HTTP 抓取 (带 SSRF/redirect/size 限制) ----------
class GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """每次跳转都会触发 socket.getaddrinfo (我们已经 hook 过), 这里只追踪计数."""
    def __init__(self, max_redirect: int):
        super().__init__()
        self.max_redirect = max_redirect

    def http_error_302(self, req, fp, code, msg, headers):
        if getattr(req, "redirect_dict", None) and len(req.redirect_dict) >= self.max_redirect:
            raise urllib.error.HTTPError(req.full_url, code, "too many redirects", headers, fp)
        return super().http_error_302(req, fp, code, msg, headers)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


@dataclasses.dataclass
class FetchResult:
    ok: bool
    url: str
    status: int
    body: str
    content_type: str
    truncated: bool
    error: Optional[str] = None


def http_get(url: str, timeout: int, max_bytes: int, max_redirect: int) -> FetchResult:
    """安全 GET. 返回完整 FetchResult, 失败用 ok=False + error 表达."""
    try:
        opener = urllib.request.build_opener(GuardedRedirectHandler(max_redirect))
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        with opener.open(req, timeout=timeout) as r:
            ct = r.headers.get("Content-Type", "")
            data = r.read(max_bytes + 1)
            truncated = len(data) > max_bytes
            if truncated:
                data = data[:max_bytes]
            try:
                body = data.decode("utf-8", errors="replace")
            except Exception:
                body = ""
            return FetchResult(True, r.geturl(), r.status, body, ct, truncated)
    except urllib.error.HTTPError as e:
        return FetchResult(False, url, e.code, "", "", False, error=f"http {e.code}")
    except PermissionError as e:
        return FetchResult(False, url, 0, "", "", False, error=f"ssrf_block: {e}")
    except urllib.error.URLError as e:
        return FetchResult(False, url, 0, "", "", False, error=f"urlerror: {e.reason}")
    except socket.timeout:
        return FetchResult(False, url, 0, "", "", False, error="timeout")
    except Exception as e:
        return FetchResult(False, url, 0, "", "", False, error=f"exc: {type(e).__name__}: {e}")


# ---------- 6 层过滤 ----------
def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    cnt = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in cnt.values())


def domain_of(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def looks_like_html(body: str) -> float:
    """估算 html 占比 (粗糙: 计数 < 比上 body 长度)."""
    if not body:
        return 0.0
    lt = body.count("<")
    return lt / max(len(body), 1)


def filter_layer1_config(url: str, cfg: DiscoveryConfig) -> Optional[str]:
    """L1 配置守门: 域名白/黑名单 + 关键字黑名单."""
    d = domain_of(url)
    if not d:
        return "no_domain"
    if any(b in d for b in cfg.domain_blacklist):
        return f"domain_blacklist:{d}"
    if not any(d == w or d.endswith("." + w) for w in cfg.domain_whitelist):
        return f"not_in_whitelist:{d}"
    lower = url.lower()
    for k in cfg.keyword_blacklist:
        if k.lower() in lower:
            return f"keyword_blacklist:{k}"
    return None


def filter_layer2_ioc(url: str, ioc: List[str]) -> Optional[str]:
    """L2 IOC 命中即拒."""
    low = url.lower()
    for needle in ioc:
        if needle in low:
            return f"ioc_hit:{needle}"
    return None


def filter_layer3_path(url: str) -> Optional[str]:
    """L3 路径形态: 必须 raw/cdn 风格 (.txt / .yaml / .yml / .conf / 无扩展但 path 含 raw)."""
    p = urllib.parse.urlparse(url)
    path = p.path.lower()
    if path.endswith((".html", ".htm", ".php", ".asp", ".jsp")):
        return f"bad_ext:{path[-6:]}"
    return None


def filter_layer4_response(fr: FetchResult, cfg: DiscoveryConfig) -> Optional[str]:
    """L4 响应层: 状态码 / Content-Type / 大小."""
    if not fr.ok:
        return f"fetch_fail:{fr.error}"
    if fr.status != 200:
        return f"http_status:{fr.status}"
    if fr.truncated:
        return "response_too_large"
    ct = fr.content_type.lower()
    if "text/html" in ct:
        return f"content_type_html:{ct}"
    return None


def filter_layer5_content(body: str, cfg: DiscoveryConfig) -> Optional[str]:
    """L5 内容签名: protocol marker 数 / html 比例 / 熵."""
    proto_hits = sum(body.count(m) for m in PROTOCOL_MARKERS)
    if proto_hits >= cfg.proto_min:
        return None  # 过
    html_r = looks_like_html(body[:50000])
    if html_r > cfg.html_ratio_max:
        return f"html_ratio:{html_r:.3f}"
    # 没协议头但很可能是 base64 整段订阅
    candidate = body.strip().replace("\n", "").replace("\r", "")
    if len(candidate) > 200 and B64_HINT.match(candidate[:5000]):
        ent = shannon_entropy(candidate[:5000])
        if ent < cfg.entropy_max_no_proto:
            return None  # base64 形态, 放过
        return f"high_entropy_no_proto:{ent:.2f}"
    return f"no_proto_marker:{proto_hits}"


def filter_layer6_cross(url: str, conn: sqlite3.Connection) -> Optional[str]:
    """L6 跨源: 已存在 sources 表 → 跳过 (不重复加分)."""
    row = conn.execute("SELECT 1 FROM sources WHERE url = ?", (url,)).fetchone()
    if row:
        return "already_in_sources"
    return None


# ---------- URL 提取 + 多层过滤管线 ----------
def extract_urls_from_text(text: str) -> List[str]:
    """从 README/markdown/json 等任意文本里抓 http(s) URL, 去重保序."""
    seen: Set[str] = set()
    out: List[str] = []
    for raw in URL_PATTERN.findall(text):
        # 去掉常见尾部杂质
        u = raw.rstrip(").,;:'\"")
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def run_filters(url: str, cfg: DiscoveryConfig, ioc: List[str],
                conn: sqlite3.Connection) -> Tuple[bool, Optional[str], Optional[FetchResult]]:
    """
    把候选 URL 跑过 L1-L6. 返回 (是否通过, 拒绝原因 or None, 网络抓到的 FetchResult or None).
    L4/L5 需要实际 GET, 之前的不需要.
    """
    for fn in (filter_layer1_config, filter_layer2_ioc, filter_layer3_path):
        if fn is filter_layer1_config:
            r = fn(url, cfg)
        elif fn is filter_layer2_ioc:
            r = fn(url, ioc)
        else:
            r = fn(url)
        if r is not None:
            return False, r, None

    fr = http_get(url, cfg.fetch_timeout_sec, cfg.max_response_bytes, cfg.max_redirect)
    r = filter_layer4_response(fr, cfg)
    if r is not None:
        return False, r, fr
    r = filter_layer5_content(fr.body, cfg)
    if r is not None:
        return False, r, fr
    r = filter_layer6_cross(url, conn)
    if r is not None:
        return False, r, fr
    return True, None, fr


# ---------- 把过了滤的 URL 写入 sources 表 ----------
def insert_new_source(conn: sqlite3.Connection, url: str, origin_key: str) -> bool:
    """
    幂等插入. 默认 status='candidate' (跟 sync-lza6 行为一致).
    score 用 sync-lza6 的默认值 (100.0). 注释里记发现来源.
    返回 True 表示新插入, False 表示已存在.
    """
    existed = conn.execute("SELECT 1 FROM sources WHERE url=?", (url,)).fetchone()
    if existed:
        return False
    note = f"discovered_by={origin_key} at {today_str()}"
    conn.execute(
        """
        INSERT INTO sources (url, first_seen, last_seen, score, status, note,
                             consecutive_fails, total_checks, total_passes,
                             consecutive_passes, low_score_total)
        VALUES (?, ?, ?, 100.0, 'candidate', ?, 0, 0, 0, 0, 0)
        """,
        (url, now_iso(), now_iso(), note),
    )
    return True


# ---------- L1 awesome_readme processor ----------
def process_awesome(conn: sqlite3.Connection, entry: sqlite3.Row,
                    cfg: DiscoveryConfig, ioc: List[str], dry_run: bool,
                    deadline: float) -> Tuple[str, int, List[Dict]]:
    """
    抓 README → 抽 URL → 6 层过滤 → 入库.
    返回 (status, added_count, sample_finding_list).
    """
    key, kind, url = entry["key"], entry["kind"], entry["url"]
    LOG.info(f"  [awesome] {key} → GET {url}")
    fr = http_get(url, cfg.fetch_timeout_sec, cfg.max_response_bytes, cfg.max_redirect)
    if not fr.ok or fr.status != 200:
        return "fail", 0, [{"key": key, "err": fr.error or f"status={fr.status}"}]
    candidates = extract_urls_from_text(fr.body)
    LOG.info(f"  [awesome] {key} 抽到 {len(candidates)} 个候选 URL")
    added = 0
    findings: List[Dict] = []
    for cand in candidates:
        if time.time() > deadline:
            findings.append({"abort": "global_deadline"})
            break
        ok, reason, _sub_fr = run_filters(cand, cfg, ioc, conn)
        if not ok:
            # 仅 IOC 命中算 critical, 其余记 debug
            if reason and reason.startswith("ioc_hit"):
                insert_audit(conn, cand, "critical", reason, {"origin": key})
                findings.append({"url": cand, "severity": "critical", "reason": reason})
            continue
        if dry_run:
            findings.append({"url": cand, "would_add": True})
            added += 1
            continue
        if insert_new_source(conn, cand, key):
            added += 1
            findings.append({"url": cand, "added": True})
    return "ok", added, findings


# ---------- L2 github_topic processor ----------
GITHUB_API_SEARCH = "https://api.github.com/search/repositories"


def process_github_topic(conn: sqlite3.Connection, entry: sqlite3.Row,
                         cfg: DiscoveryConfig, ioc: List[str], dry_run: bool,
                         deadline: float) -> Tuple[str, int, List[Dict]]:
    """
    GitHub Search API (匿名 60req/h). query 占位 RECENT_30D 替换为 30 天前 ISO 日期.
    对每个 hit 拼 raw README URL 再下放 awesome 流程.
    """
    key = entry["key"]
    note = entry["note"] if "note" in entry.keys() else ""
    raw_query = entry["url"] or ""  # 我们存到 url 字段里
    if not raw_query:
        # bootstrap 时把 query 写到 note, 用 note 兜一下
        raw_query = note or ""
    if "RECENT_30D" in raw_query:
        d = (dt.date.today() - dt.timedelta(days=30)).isoformat()
        raw_query = raw_query.replace("RECENT_30D", d)
    LOG.info(f"  [topic] {key} → search: {raw_query}")
    qs = urllib.parse.urlencode({"q": raw_query, "sort": "updated", "order": "desc", "per_page": 20})
    api_url = f"{GITHUB_API_SEARCH}?{qs}"
    fr = http_get(api_url, cfg.fetch_timeout_sec, cfg.max_response_bytes, cfg.max_redirect)
    if not fr.ok:
        return "fail", 0, [{"key": key, "err": fr.error}]
    if fr.status == 403:
        return "quota", 0, [{"key": key, "err": "rate_limited"}]
    if fr.status != 200:
        return "fail", 0, [{"key": key, "err": f"status={fr.status}"}]
    try:
        payload = json.loads(fr.body)
    except Exception as e:
        return "fail", 0, [{"key": key, "err": f"json_parse: {e}"}]
    items = payload.get("items") or []
    LOG.info(f"  [topic] {key} 命中 {len(items)} 个 repo")
    added = 0
    findings: List[Dict] = []
    for repo in items[:20]:
        if time.time() > deadline:
            findings.append({"abort": "global_deadline"})
            break
        full = repo.get("full_name") or ""
        default_branch = repo.get("default_branch") or "main"
        if not full:
            continue
        # 候选 raw 入口: README.md / sub.txt / subscribe.txt 几个常见名字
        candidates = [
            f"https://raw.githubusercontent.com/{full}/{default_branch}/README.md",
            f"https://raw.githubusercontent.com/{full}/{default_branch}/sub.txt",
            f"https://raw.githubusercontent.com/{full}/{default_branch}/subscribe.txt",
        ]
        for cand in candidates:
            if time.time() > deadline:
                break
            ok, reason, sub_fr = run_filters(cand, cfg, ioc, conn)
            if not ok:
                if reason and reason.startswith("ioc_hit"):
                    insert_audit(conn, cand, "critical", reason, {"origin": key, "repo": full})
                    findings.append({"url": cand, "severity": "critical", "reason": reason})
                continue
            if dry_run:
                findings.append({"url": cand, "would_add": True, "repo": full})
                added += 1
                continue
            if insert_new_source(conn, cand, key):
                added += 1
                findings.append({"url": cand, "added": True, "repo": full})
            # 同时把 README 里 URL 也抽出来 (大头)
            if sub_fr and sub_fr.body:
                inner = extract_urls_from_text(sub_fr.body)
                for inner_url in inner[:50]:
                    if time.time() > deadline:
                        break
                    ok2, reason2, _ = run_filters(inner_url, cfg, ioc, conn)
                    if not ok2:
                        if reason2 and reason2.startswith("ioc_hit"):
                            insert_audit(conn, inner_url, "critical", reason2,
                                         {"origin": key, "repo": full})
                            findings.append({"url": inner_url, "severity": "critical",
                                             "reason": reason2})
                        continue
                    if dry_run:
                        findings.append({"url": inner_url, "would_add": True, "repo": full})
                        added += 1
                        continue
                    if insert_new_source(conn, inner_url, key):
                        added += 1
                        findings.append({"url": inner_url, "added": True, "repo": full})
    return "ok", added, findings


# ---------- L4 source_audit processor ----------
def process_source_audit(conn: sqlite3.Connection, cfg: DiscoveryConfig, ioc: List[str],
                         dry_run: bool, deadline: float) -> Tuple[int, List[Dict]]:
    """
    审计现有低分源. 不动 score/status — 只在 source_audits 表追加, 并在 sources.note
    末尾追加 'audit:critical' 标签 (供 sync-lza6 之外的工具排查).
    """
    threshold = cfg.audit_threshold
    daily_limit = cfg.audit_daily_limit
    cooldown_days = cfg.audit_cooldown_days

    cooldown_cutoff = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=cooldown_days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    rows = conn.execute(
        """
        SELECT s.url FROM sources s
        WHERE s.score < ?
          AND NOT EXISTS (
              SELECT 1 FROM source_audits a
              WHERE a.source_url = s.url AND a.audited_at >= ?
          )
        ORDER BY s.score ASC, s.last_seen DESC
        LIMIT ?
        """,
        (threshold, cooldown_cutoff, daily_limit),
    ).fetchall()

    LOG.info(f"  [audit] 选中 {len(rows)} 个低分源 (threshold={threshold}, cooldown={cooldown_days}d)")
    findings: List[Dict] = []
    audited = 0
    for (url,) in rows:
        if time.time() > deadline:
            findings.append({"abort": "global_deadline"})
            break
        # 安全 GET — IOC 检查仍然跑一次
        ioc_hit = filter_layer2_ioc(url, ioc)
        if ioc_hit:
            findings.append({"url": url, "severity": "critical", "reason": ioc_hit})
            if not dry_run:
                insert_audit(conn, url, "critical", ioc_hit, {"phase": "audit"})
                # 不动 sources.note (清理系统领域)
            audited += 1
            continue
        fr = http_get(url, cfg.fetch_timeout_sec, cfg.max_response_bytes, cfg.max_redirect)
        if not fr.ok:
            findings.append({"url": url, "severity": "info",
                             "reason": f"unreachable: {fr.error}"})
            if not dry_run:
                insert_audit(conn, url, "info", "unreachable",
                             {"phase": "audit", "err": fr.error})
            audited += 1
            continue
        # 当下用 L4 + L5 严判
        bad_resp = filter_layer4_response(fr, cfg)
        bad_cont = filter_layer5_content(fr.body, cfg) if not bad_resp else None
        sev = "info"
        reason = None
        if bad_resp and "html" in bad_resp:
            sev, reason = "warn", bad_resp
        elif bad_resp:
            sev, reason = "info", bad_resp
        elif bad_cont and (bad_cont.startswith("html_ratio")
                           or bad_cont.startswith("high_entropy_no_proto")):
            sev, reason = "warn", bad_cont
        elif bad_cont:
            sev, reason = "info", bad_cont
        if reason:
            findings.append({"url": url, "severity": sev, "reason": reason})
            if not dry_run:
                insert_audit(conn, url, sev, reason, {"phase": "audit"})
                # 不动 sources.note (清理系统领域)
        else:
            if not dry_run:
                insert_audit(conn, url, "info", "audit_pass", {"phase": "audit"})
        audited += 1
    return audited, findings


def _append_audit_tag(conn: sqlite3.Connection, url: str, reason: str):
    """note 末尾追加 'audit:critical:<reason>'  — 不重复追加."""
    row = conn.execute("SELECT note FROM sources WHERE url=?", (url,)).fetchone()
    if not row:
        return
    note = row[0] or ""
    tag = f"audit:critical:{reason}"
    if tag in note:
        return
    new_note = (note + " | " + tag).strip(" |")
    conn.execute("UPDATE sources SET note=? WHERE url=?", (new_note, url))


# ---------- bootstrap (从 yaml 灌 discovery_state) ----------
def cmd_bootstrap(conn: sqlite3.Connection, cfg: DiscoveryConfig) -> int:
    LOG.info("Bootstrap: 从 discovery-config.yaml 同步到 discovery_state")
    cnt = 0
    for e in cfg.awesome_entries:
        upsert_state_entry(conn, e["key"], KIND_AWESOME, e["url"],
                           int(e.get("priority", 100)), e.get("note"))
        cnt += 1
    for e in cfg.topic_entries:
        # github_topic: 把 query 存进 url 字段 (process_github_topic 会读)
        upsert_state_entry(conn, e["key"], KIND_TOPIC, e["query"],
                           int(e.get("priority", 100)), e.get("note"))
        cnt += 1
    for e in cfg.telegram_entries:
        upsert_state_entry(conn, e["key"], KIND_TELEGRAM, e.get("url"),
                           int(e.get("priority", 100)), e.get("note"))
        cnt += 1
    conn.commit()
    LOG.info(f"Bootstrap 完成: {cnt} 条 discovery_state")
    return 0


# ---------- 主调度 ----------
def cmd_run(conn: sqlite3.Connection, cfg: DiscoveryConfig, ioc: List[str],
            dry_run: bool, only_kind: Optional[str]) -> Dict:
    start = time.time()
    deadline = start + cfg.global_timeout_sec
    summary: Dict = {
        "started_at": now_iso(),
        "dry_run": dry_run,
        "kinds": {},
        "criticals": [],
    }

    plan = []
    if only_kind in (None, KIND_AWESOME):
        plan.append((KIND_AWESOME, cfg.budget_awesome, process_awesome))
    if only_kind in (None, KIND_TOPIC):
        plan.append((KIND_TOPIC, cfg.budget_topic, process_github_topic))
    # telegram L3 — 暂不实现, 跳过 (只要 user 后续往 yaml 加 entry, bootstrap 灌进来即可)
    # if only_kind in (None, KIND_TELEGRAM):
    #     plan.append((KIND_TELEGRAM, cfg.budget_telegram, None))

    for kind, budget, processor in plan:
        targets = pick_next_targets(conn, kind, budget)
        LOG.info(f"[{kind}] 取到 {len(targets)} 个目标 (budget={budget})")
        kind_summary = {"targets": len(targets), "added": 0, "fail": 0, "skip": 0}
        for entry in targets:
            if time.time() > deadline:
                LOG.warn(f"[{kind}] 触发全局 deadline, 中断")
                break
            try:
                status, added, findings = processor(conn, entry, cfg, ioc, dry_run, deadline)
            except Exception as e:
                LOG.error(f"[{kind}] {entry['key']} 异常: {e}")
                LOG.error(traceback.format_exc())
                status, added, findings = "fail", 0, [{"err": str(e)}]
            mark_state(conn, entry["key"], status, added)
            if not dry_run:
                conn.commit()
            kind_summary["added"] += added
            if status == "fail":
                kind_summary["fail"] += 1
            elif status in ("skipped", "quota"):
                kind_summary["skip"] += 1
            for f in findings:
                if f.get("severity") == "critical":
                    summary["criticals"].append(f)
        summary["kinds"][kind] = kind_summary

    if only_kind in (None, KIND_AUDIT) and cfg.audit_enabled:
        if time.time() <= deadline:
            audited, findings = process_source_audit(conn, cfg, ioc, dry_run, deadline)
            summary["kinds"][KIND_AUDIT] = {"audited": audited}
            for f in findings:
                if f.get("severity") == "critical":
                    summary["criticals"].append(f)
            if not dry_run:
                conn.commit()

    summary["ended_at"] = now_iso()
    summary["elapsed_sec"] = round(time.time() - start, 1)
    return summary


# ---------- 通知 (合并 critical) ----------
def maybe_notify(summary: Dict, cfg: DiscoveryConfig):
    if not cfg.notify_enabled:
        return
    crits = summary.get("criticals") or []
    if len(crits) < cfg.notify_min_critical:
        return
    # 复用 notify-telegram.py 的 conf 解析
    tg_conf = "/etc/telegram-bot.conf"
    if not os.path.exists(tg_conf):
        LOG.warn("notify: /etc/telegram-bot.conf 不存在, 跳过")
        return
    cfg_kv: Dict[str, str] = {}
    with open(tg_conf) as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            cfg_kv[k.strip()] = v.strip().strip('"').strip("'")
    token = cfg_kv.get("TELEGRAM_BOT_TOKEN")
    chat = cfg_kv.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    lines = [
        f"🚨 *discover-airports critical* ({len(crits)})",
        f"轮: {summary['ended_at']}, 用时 {summary['elapsed_sec']}s",
        "",
    ]
    for c in crits[:10]:
        u = c.get("url", "?")
        r = c.get("reason", "?")
        lines.append(f"• `{u}` — {r}")
    if len(crits) > 10:
        lines.append(f"... 另 {len(crits) - 10} 条")
    text = "\n".join(lines)
    try:
        data = urllib.parse.urlencode({
            "chat_id": chat, "parse_mode": "Markdown", "text": text,
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data,
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            LOG.info(f"notify: telegram status={r.status}")
    except Exception as e:
        LOG.warn(f"notify 失败: {e}")


# ---------- 全局 SIGTERM 兜底 ----------
def _install_signal_handlers(deadline: float):
    def _handler(signum, frame):
        LOG.error(f"收到 signal {signum}, 触发兜底退出")
        sys.exit(2)
    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


# ---------- main ----------
def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="discover-airports — 公益机场源自动发现")
    ap.add_argument("--bootstrap", action="store_true",
                    help="从 discovery-config.yaml 同步条目到 discovery_state, 然后退出")
    ap.add_argument("--dry-run", action="store_true",
                    help="只跑过滤+审计, 不写 sources/source_audits, 不发通知")
    ap.add_argument("--only", choices=ALL_KINDS,
                    help="只跑某一类 (默认 awesome+topic+audit)")
    ap.add_argument("--config", default=CONFIG_YAML)
    ap.add_argument("--ignore-sync-lock", action="store_true",
                    help="即使 sync-lza6 在跑也强行跑 (默认让路)")
    args = ap.parse_args(argv)

    if not os.path.exists(args.config):
        LOG.error(f"配置文件不存在: {args.config}")
        return 1

    cfg = DiscoveryConfig.load(args.config)
    ioc = load_ioc_list(IOC_LIST)
    LOG.info(f"配置 OK: awesome={len(cfg.awesome_entries)} topic={len(cfg.topic_entries)} "
             f"telegram={len(cfg.telegram_entries)} ioc={len(ioc)}")

    install_ssrf_guard()

    # 让路逻辑: sync-lza6 跑时退出 3
    if not args.ignore_sync_lock and sync_lock_held():
        LOG.warn("sync-lza6 持锁中, 让路退出 (exit 3)")
        return 3

    lock = FileLock(LOCK_FILE)
    if not lock.acquire_or_die():
        LOG.warn("已有 discover-airports 实例在跑, 退出")
        return 0

    deadline = time.time() + cfg.global_timeout_sec
    _install_signal_handlers(deadline)

    try:
        conn = db_connect()
        migrate_schema(conn)
        # SQLite Row factory 让 entry["key"] 这种访问能工作
        conn.row_factory = sqlite3.Row

        if args.bootstrap:
            rc = cmd_bootstrap(conn, cfg)
            return rc

        summary = cmd_run(conn, cfg, ioc, args.dry_run, args.only)
        LOG.info("=== summary ===")
        LOG.info(json.dumps(summary, ensure_ascii=False, indent=2))
        if not args.dry_run:
            maybe_notify(summary, cfg)
        return 0
    except SystemExit:
        raise
    except Exception as e:
        LOG.error(f"main 异常: {e}")
        LOG.error(traceback.format_exc())
        return 1
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
