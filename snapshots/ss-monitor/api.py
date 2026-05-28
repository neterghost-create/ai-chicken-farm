#!/usr/bin/env python3
"""
Shadowsocks 监控 API + Subs-Check 免费池监控
提供服务状态、连接数、内存占用、节点池统计等信息
"""

from flask import Flask, jsonify, request, Response
import subprocess
import re
import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Subs-Check 相关路径
SUBS_CHECK_OUTPUT = "/opt/ss-monitor/sub/free"
SUBS_CHECK_STATS = "/opt/ss-monitor/sub/free/stats.json"
SUBS_CHECK_DB = "/opt/subs-check/scripts/source-scores.db"
SUBS_CHECK_CONFIG = "/opt/subs-check/config/config.yaml"
CN_PROXY_SOURCES_DB = "/opt/subs-check/scripts/cn-proxy-sources.db"

def run_command(cmd):
    """执行系统命令 (全部硬编码, 无用户输入)"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        return result.stdout.strip()
    except Exception:
        return ""

def get_service_status():
    """检查服务是否运行"""
    output = run_command("systemctl is-active shadowsocks-rust.service")
    return output == "active"

def get_active_connections():
    """获取活跃连接数"""
    output = run_command("netstat -anp | grep ESTABLISHED | grep 2052 | wc -l")
    try:
        return int(output)
    except Exception:
        return 0

def get_connection_list():
    """获取连接列表"""
    output = run_command("netstat -anp | grep ESTABLISHED | grep 2052 | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn")
    connections = []
    for line in output.split('\n'):
        if line.strip():
            parts = line.strip().split()
            if len(parts) >= 2:
                count = parts[0]
                ip = parts[1]
                connections.append(f"{ip} ({count} 连接)")
    return connections

def get_total_connections():
    """获取总连接数（包括 TIME_WAIT）"""
    output = run_command("netstat -an | grep 2052 | wc -l")
    try:
        return int(output)
    except Exception:
        return 0

def get_uptime():
    """获取服务运行时间"""
    output = run_command("systemctl show shadowsocks-rust.service --property=ActiveEnterTimestamp --value")
    if not output:
        return "-"
    
    try:
        # 解析时间戳
        start_time_str = output.split(';')[0].strip()
        # 格式: Thu 2026-05-21 14:46:43 CST
        start_time = datetime.strptime(start_time_str, "%a %Y-%m-%d %H:%M:%S %Z")
        uptime = datetime.now() - start_time
        
        days = uptime.days
        hours = uptime.seconds // 3600
        minutes = (uptime.seconds % 3600) // 60
        
        if days > 0:
            return f"{days}天{hours}小时"
        elif hours > 0:
            return f"{hours}小时{minutes}分钟"
        else:
            return f"{minutes}分钟"
    except Exception:
        return "-"

def get_memory_usage():
    """获取内存占用"""
    output = run_command("ps aux | grep ssserver-rust | grep -v grep | awk '{print $6}'")
    try:
        kb = int(output)
        if kb < 1024:
            return f"{kb} KB"
        else:
            mb = kb / 1024
            return f"{mb:.1f} MB"
    except Exception:
        return "-"

@app.route('/api/ss-status')
def get_status():
    """获取 Shadowsocks 状态"""
    return jsonify({
        'service_running': get_service_status(),
        'active_connections': get_active_connections(),
        'total_connections': get_total_connections(),
        'uptime': get_uptime(),
        'memory': get_memory_usage(),
        'connections': get_connection_list(),
        'timestamp': datetime.now().isoformat()
    })


# ===== Subs-Check (Free Node Pool) =====

def get_subs_check_status():
    """检查 subs-check service 是否在跑"""
    output = run_command("systemctl is-active subs-check.service")
    return output == "active"


def get_subs_check_uptime():
    output = run_command("systemctl show subs-check.service --property=ActiveEnterTimestamp --value")
    if not output:
        return "-"
    try:
        start_time_str = output.split(';')[0].strip()
        start_time = datetime.strptime(start_time_str, "%a %Y-%m-%d %H:%M:%S %Z")
        uptime = datetime.now() - start_time
        days = uptime.days
        hours = uptime.seconds // 3600
        minutes = (uptime.seconds % 3600) // 60
        if days > 0:
            return f"{days}天{hours}小时"
        elif hours > 0:
            return f"{hours}小时{minutes}分钟"
        return f"{minutes}分钟"
    except Exception:
        return "-"


def get_subs_check_memory():
    """subs-check 内存占用 (RSS)"""
    output = run_command("systemctl show subs-check.service --property=MemoryCurrent --value")
    try:
        bytes_n = int(output)
        if bytes_n == 0:
            return "-"
        mb = bytes_n / 1024 / 1024
        return f"{mb:.1f} MB"
    except Exception:
        return "-"


def get_subs_check_progress():
    """从 journalctl 提取最新流水线进度

    窗口必须 > check-interval (默认 6h), 否则两轮之间的空窗会让上一轮
    最后一行进度被滑出窗口, 当前轮还没出第一条 '流水线: 测活' 时
    progress 全空 → 前端显示 '-'.

    按时序处理事件 (不再用 tail -3 截断):
      流水线: 测活 ...   → 更新 tested/total/alive/...; completed=False (新一轮启动)
      检测完成           → completed=True
      下次检查时间: ...  → next_check
    新一轮的 '流水线: 测活' 会自然把 completed 翻回 False, 避免 tail -3 残留
    上轮 '检测完成' 让前端在新一轮前 ~6 分钟仍显示 ✓ 已完成.
    """
    output = run_command(
        "journalctl -u subs-check --no-pager --since '8 hours ago' -o cat 2>&1 "
        "| grep -E '流水线: 测活|检测完成|下次检查'"
    )
    lines = output.split('\n') if output else []
    progress = {
        'tested': None, 'total': None, 'alive': None,
        'media_pass': None, 'speed_pass': None,
        'next_check': None, 'completed': False
    }
    for line in lines:
        # 流水线: 测活 N/M (存活:K) | 媒体 X/K (通过:Y) | 测速 通过:Z
        m = re.search(
            r'测活 (\d+)/(\d+) \(存活:(\d+)\).*媒体 \d+/\d+ \(通过:(\d+)\).*测速 通过:(\d+)',
            line
        )
        if m:
            progress['tested'] = int(m.group(1))
            progress['total'] = int(m.group(2))
            progress['alive'] = int(m.group(3))
            progress['media_pass'] = int(m.group(4))
            progress['speed_pass'] = int(m.group(5))
            # 新一轮启动 → 翻回 running, 抹掉上轮残留的 completed
            progress['completed'] = False
            continue
        if '检测完成' in line:
            progress['completed'] = True
            continue
        m2 = re.search(r'下次检查时间: (\S+ \S+)', line)
        if m2:
            progress['next_check'] = m2.group(1)
    return progress


def get_pool_stats():
    """读 stats.json (由 convert-formats.py 生成)"""
    if not os.path.exists(SUBS_CHECK_STATS):
        return None
    try:
        with open(SUBS_CHECK_STATS) as f:
            return json.load(f)
    except Exception:
        return None


def get_cn_proxy_stats():
    """读 cn-proxy-sources.db 统计 CN 代理源状态"""
    if not os.path.exists(CN_PROXY_SOURCES_DB):
        return None
    try:
        db = sqlite3.connect(f"file:{CN_PROXY_SOURCES_DB}?mode=ro", uri=True)
        rows = db.execute(
            "SELECT name, protocol, last_status, last_proxy_count, last_checked_at "
            "FROM cn_proxy_sources WHERE enabled = 1 ORDER BY last_status DESC, last_proxy_count DESC"
        ).fetchall()
        total_sources = len(rows)
        available = sum(1 for r in rows if r[2] == 'ok')
        total_proxies = sum(r[3] or 0 for r in rows if r[2] == 'ok')
        last_discovery = db.execute(
            "SELECT MAX(last_checked_at) FROM cn_proxy_sources WHERE enabled = 1"
        ).fetchone()[0]
        db.close()
        return {
            'total_sources': total_sources,
            'available_sources': available,
            'total_proxies': total_proxies,
            'last_discovery': last_discovery,
            'sources': [
                {
                    'name': r[0],
                    'protocol': r[1],
                    'status': r[2],
                    'proxy_count': r[3] or 0,
                    'last_checked': r[4],
                } for r in rows
            ],
        }
    except Exception as e:
        logger.exception("Error in get_cn_proxy_stats")
        return {'error': 'Internal server error'}


def get_source_db_stats():
    """读 SQLite 评分库统计"""
    if not os.path.exists(SUBS_CHECK_DB):
        return None
    try:
        db = sqlite3.connect(f"file:{SUBS_CHECK_DB}?mode=ro", uri=True)
        rows = db.execute("SELECT status, COUNT(*) FROM sources GROUP BY status").fetchall()
        status_counts = {s: c for s, c in rows}
        # top 5 按分数
        top_sources = db.execute("""
            SELECT url, score, total_passes, total_checks, status
            FROM sources WHERE status != 'blacklisted'
            ORDER BY score DESC, total_passes DESC LIMIT 5
        """).fetchall()
        # metadata
        last_etag = db.execute("SELECT value FROM metadata WHERE key='lza6_etag'").fetchone()
        last_sync = db.execute("SELECT value FROM metadata WHERE key='last_sync_at'").fetchone()
        db.close()
        return {
            'status_counts': status_counts,
            'total_sources': sum(status_counts.values()),
            'top_sources': [
                {
                    'url': u, 'score': round(s, 1),
                    'passes': p, 'checks': c, 'status': st
                }
                for u, s, p, c, st in top_sources
            ],
            'last_etag': (last_etag[0][:16] + '...') if last_etag else None,
            'last_sync_at': last_sync[0] if last_sync else None,
        }
    except Exception as e:
        logger.exception("Error in get_source_db_stats")
        return {'error': 'Internal server error'}


@app.route('/api/free-pool')
def get_free_pool():
    """免费节点池状态 (subs-check + lza6 同步器). 不返回订阅 URL (token-protected)."""
    pool = get_pool_stats()
    db = get_source_db_stats()
    progress = get_subs_check_progress()

    # Latest incremental-check result (30min probe)
    _inc = _read_json("/opt/ss-monitor/sub/free/incremental-history.json")
    inc_latest = (_inc.get('history') or [None])[-1] if _inc else None

    # State distribution from history.db (v3.0 三态机)
    _HISTORY_DB = "/opt/subs-check/scripts/history.db"
    state_dist = {}
    if os.path.exists(_HISTORY_DB):
        try:
            _hdb = sqlite3.connect(f"file:{_HISTORY_DB}?mode=ro", uri=True)
            for s, c in _hdb.execute("SELECT state, COUNT(*) FROM nodes_history GROUP BY state"):
                state_dist[(s or 'testing')] = c
            _hdb.close()
        except Exception:
            pass

    return jsonify({
        'service_running': get_subs_check_status(),
        'service_uptime': get_subs_check_uptime(),
        'service_memory': get_subs_check_memory(),
        'pool': pool,           # 节点统计 (last_run, total_nodes, protocols)
        'sources_db': db,        # 订阅源评分库
        'progress': progress,    # 当前一轮进度
        'incremental_check': inc_latest,   # 最新增量探活 (30min)
        'state_distribution': state_dist,   # 节点状态分布 (testing/decaying/recovering)
        'token_protected': True,  # 提示订阅 URL 受保护
        'timestamp': datetime.now().isoformat()
    })


def _read_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _serve_json_conditional(path):
    """讀 JSON 檔，帶 ETag/Last-Modified 條件請求支援 (Step 17: 304 省流量)"""
    if not os.path.exists(path):
        return jsonify({})
    try:
        st = os.stat(path)
        etag = f'W/"{st.st_mtime_ns:x}-{st.st_size:x}"'
        last_modified = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        last_modified_http = last_modified.strftime('%a, %d %b %Y %H:%M:%S GMT')

        # 條件檢查: If-None-Match 優先, fallback If-Modified-Since
        inm = request.headers.get('If-None-Match')
        if inm and inm == etag:
            return Response(status=304, headers={'ETag': etag, 'Last-Modified': last_modified_http, 'Cache-Control': 'no-cache'})
        ims = request.headers.get('If-Modified-Since')
        if ims and not inm:
            try:
                ims_dt = datetime.strptime(ims, '%a, %d %b %Y %H:%M:%S GMT').replace(tzinfo=timezone.utc)
                if int(ims_dt.timestamp()) >= int(last_modified.timestamp()):
                    return Response(status=304, headers={'ETag': etag, 'Last-Modified': last_modified_http, 'Cache-Control': 'no-cache'})
            except Exception:
                pass

        with open(path, 'rb') as f:
            data = f.read()
        resp = Response(data, mimetype='application/json')
        resp.headers['ETag'] = etag
        resp.headers['Last-Modified'] = last_modified_http
        resp.headers['Cache-Control'] = 'no-cache'  # 必須向源驗證, 不能來不打
        return resp
    except Exception:
        return jsonify({})


@app.route('/api/free-pool/nodes')
def get_nodes():
    """当前轮节点详情列表 (脱敏) - 带 ETag"""
    return _serve_json_conditional("/opt/ss-monitor/sub/free/nodes.json")


@app.route('/api/free-pool/diff')
def get_diff():
    """这轮 vs 上轮 diff - 带 ETag"""
    return _serve_json_conditional("/opt/ss-monitor/sub/free/diff.json")


@app.route('/api/free-pool/history')
def get_history():
    """最近 20 轮趋势 - 带 ETag"""
    return _serve_json_conditional("/opt/ss-monitor/sub/free/history.json")


@app.route('/api/free-pool/incremental-history')
def get_incremental_history():
    """最近 20 轮增量探活趋势 - 带 ETag"""
    return _serve_json_conditional("/opt/ss-monitor/sub/free/incremental-history.json")


@app.route('/api/free-pool/quality')
def get_quality():
    """节点级评分 TOP 排行 (从 history.db nodes_history 表) — v3.0 三态机"""
    import sqlite3 as sq
    HISTORY_DB = "/opt/subs-check/scripts/history.db"
    if not os.path.exists(HISTORY_DB):
        return jsonify({'error': 'history.db not found'}), 503
    try:
        db = sq.connect(f"file:{HISTORY_DB}?mode=ro", uri=True)
        # 总览
        total = db.execute("SELECT COUNT(*) FROM nodes_history").fetchone()[0]
        # v3.0 状态分布
        try:
            state_rows = db.execute(
                "SELECT state, COUNT(*) FROM nodes_history GROUP BY state"
            ).fetchall()
            state_counts = {(s or 'testing'): c for s, c in state_rows}
            has_state = True
        except sq.OperationalError:
            state_counts = {}
            has_state = False
        # v3.0: active = testing + decaying + recovering
        active = db.execute(
            "SELECT COUNT(*) FROM nodes_history WHERE state != 'recovering' OR state IS NULL"
        ).fetchone()[0]
        # 评分分布
        bands = db.execute("""
            SELECT
              CASE
                WHEN quality_score >= 90 THEN '90-100 (优秀)'
                WHEN quality_score >= 70 THEN '70-89 (良好)'
                WHEN quality_score >= 50 THEN '50-69 (中等)'
                WHEN quality_score >= 30 THEN '30-49 (弱)'
                ELSE '<30 (危险)'
              END as band,
              COUNT(*) as cnt
            FROM nodes_history
            GROUP BY band ORDER BY band DESC
        """).fetchall()
        # TOP 30 高分节点 (v3.0: 加 state 字段)
        if has_state:
            top = db.execute("""
                SELECT canonical_sig, quality_score, total_appearances, consecutive_appearances,
                       last_speed_kbps, avg_speed_kbps, incremental_pass, incremental_fail,
                       region, protocol, sample_name, consecutive_low_quality_node, consecutive_fails,
                       COALESCE(state, 'testing') as state
                FROM nodes_history
                ORDER BY quality_score DESC, total_appearances DESC
                LIMIT 30
            """).fetchall()
        else:
            top = db.execute("""
                SELECT canonical_sig, quality_score, total_appearances, consecutive_appearances,
                       last_speed_kbps, avg_speed_kbps, incremental_pass, incremental_fail,
                       region, protocol, sample_name, consecutive_low_quality_node, consecutive_fails
                FROM nodes_history
                WHERE blacklisted_until IS NULL
                ORDER BY quality_score DESC, total_appearances DESC
                LIMIT 30
            """).fetchall()
        # 低分节点 (v3.0: state=recovering 或 quality_score < 30)
        bl = db.execute("""
            SELECT canonical_sig, COALESCE(state, 'testing') as state, region, protocol,
                   quality_score, sample_name
            FROM nodes_history
            WHERE quality_score < 30 OR state = 'recovering'
            ORDER BY quality_score ASC
            LIMIT 20
        """).fetchall()
        db.close()
        return jsonify({
            'summary': {
                'total': total,
                'active': active,
                'state_counts': state_counts,   # v3.0
            },
            'score_bands': [{'band': b, 'count': c} for b, c in bands],
            'top_nodes': [
                {
                    'sig': r[0],
                    'quality_score': round(r[1], 1) if r[1] is not None else 50.0,
                    'appearances': r[2],
                    'consecutive': r[3],
                    'last_speed_kbps': r[4],
                    'avg_speed_kbps': round(r[5]) if r[5] else 0,
                    'inc_pass': r[6],
                    'inc_fail': r[7],
                    'region': r[8],
                    'protocol': r[9],
                    'name': r[10],
                    'lq_node': r[11] if r[11] is not None else 0,
                    'cons_fails': r[12],
                    'state': r[13] if has_state else 'testing',
                } for r in top
            ],
            'low_quality_nodes': [
                {
                    'sig': r[0],
                    'state': r[1],   # v3.0: state 名 (recovering 等)
                    'region': r[2],
                    'protocol': r[3],
                    'quality_score': round(r[4], 1) if r[4] is not None else 0,
                    'name': r[5],
                } for r in bl
            ],
            'cn_proxy': get_cn_proxy_stats(),
            'rules_version': 'v3.0',
            'state_threshold': 50,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.exception("Error in get_quality")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        try: db.close()
        except Exception: pass


@app.route('/api/free-pool/sources')
def get_sources():
    """订阅源质量评分 (节点平均分 + v3.0 状态).

    返回 sources 表里全部源 (默认 184), 用 data_maturity 字段标记数据成熟度:
      - 'scored':  source_quality_history 有记录 (最完整, 当轮真实贡献节点)
      - 'mapped':  source_node_map 有记录但 quality_history 没 (fetcher 抓过但当轮无节点)
      - 'known':   sources 表有但 fetcher 还没抓 (lza6 刚同步进来)
    """
    import sqlite3 as sq
    SCORES_DB = "/opt/subs-check/scripts/source-scores.db"
    if not os.path.exists(SCORES_DB):
        return jsonify({'error': 'source-scores.db not found'}), 503
    try:
        db = sq.connect(f"file:{SCORES_DB}?mode=ro", uri=True)
        # 总览 (v3.0: 用 state 而非 status, 但兼容旧 status 字段)
        try:
            rows = db.execute(
                "SELECT state, COUNT(*) FROM sources GROUP BY state"
            ).fetchall()
            state_counts = {(s or 'testing'): c for s, c in rows}
        except sq.OperationalError:
            state_counts = {}
        rows = db.execute(
            "SELECT status, COUNT(*) FROM sources GROUP BY status"
        ).fetchall()
        status_counts = {s: c for s, c in rows}

        # mapped 集合 (fetcher 抓过)
        mapped_urls = {
            r[0] for r in db.execute(
                "SELECT DISTINCT source_url FROM source_node_map"
            ).fetchall()
        }
        # scored 集合 (有评分历史)
        scored_urls = {
            r[0] for r in db.execute(
                "SELECT DISTINCT source_url FROM source_quality_history"
            ).fetchall()
        }

        # 全部源 + 最新一轮均分 (LEFT JOIN, 没评分的源也返回)
        # v3.0: 加上 state 字段
        try:
            sources = db.execute("""
                SELECT s.url, s.status, s.consecutive_low_quality, s.first_seen_round,
                       s.blocked_until,
                       (SELECT avg_quality_score FROM source_quality_history h
                          WHERE h.source_url = s.url ORDER BY round_id DESC LIMIT 1) as latest_avg,
                       (SELECT node_count FROM source_quality_history h
                          WHERE h.source_url = s.url ORDER BY round_id DESC LIMIT 1) as latest_count,
                       s.score, s.total_checks, s.total_passes, s.last_seen,
                       s.consecutive_fails, s.consecutive_passes, s.low_score_total,
                       COALESCE(s.state, 'testing') as state
                FROM sources s
                ORDER BY
                    (latest_avg IS NULL) ASC,
                    latest_avg DESC,
                    s.score DESC
            """).fetchall()
            has_state = True
        except sq.OperationalError:
            sources = db.execute("""
                SELECT s.url, s.status, s.consecutive_low_quality, s.first_seen_round,
                       s.blocked_until,
                       (SELECT avg_quality_score FROM source_quality_history h
                          WHERE h.source_url = s.url ORDER BY round_id DESC LIMIT 1) as latest_avg,
                       (SELECT node_count FROM source_quality_history h
                          WHERE h.source_url = s.url ORDER BY round_id DESC LIMIT 1) as latest_count,
                       s.score, s.total_checks, s.total_passes, s.last_seen,
                       s.consecutive_fails, s.consecutive_passes, s.low_score_total
                FROM sources s
                ORDER BY
                    (latest_avg IS NULL) ASC,
                    latest_avg DESC,
                    s.score DESC
            """).fetchall()
            has_state = False

        # 历史分布: 最近 10 轮每源的均分趋势 (只对 scored 源有意义)
        trends = {}
        for url in scored_urls:
            history = db.execute("""
                SELECT round_id, avg_quality_score, below_50
                FROM source_quality_history
                WHERE source_url = ?
                ORDER BY round_id DESC LIMIT 10
            """, (url,)).fetchall()
            trends[url] = [
                {'round': r[0], 'avg': round(r[1], 1), 'below_50': bool(r[2])}
                for r in history
            ]

        db.close()

        # 组装 + 标 data_maturity
        sources_out = []
        maturity_counts = {'scored': 0, 'mapped': 0, 'known': 0}
        for r in sources:
            url = r[0]
            if url in scored_urls:
                maturity = 'scored'
            elif url in mapped_urls:
                maturity = 'mapped'
            else:
                maturity = 'known'
            maturity_counts[maturity] += 1
            sources_out.append({
                'url': url,
                'status': r[1],
                'state': r[14] if has_state else 'testing',  # v3.0
                'low_streak': r[2],            # consecutive_low_quality (v2.3 遗留, v3 不用)
                'first_seen_round': r[3],
                'blocked_until': r[4],
                'latest_avg_score': round(r[5], 1) if r[5] else None,
                'latest_node_count': r[6],
                'source_score': round(r[7], 1) if r[7] is not None else None,
                'total_checks': r[8],
                'total_passes': r[9],
                'last_seen': r[10],
                'cons_fails': r[11],
                'cons_passes': r[12],
                'low_score_total': r[13],
                'data_maturity': maturity,
                'recent_trend': trends.get(url, []),
            })

        return jsonify({
            'status_counts': status_counts,
            'state_counts': state_counts,    # v3.0: testing / decaying / recovering
            'maturity_counts': maturity_counts,
            'total_sources': len(sources_out),
            'sources': sources_out,
            # v3.0 阈值元数据 (前端展示用)
            'rules_version': 'v3.0',
            'state_threshold': 50,             # 三态机阈值 (decaying/recovering ↔ testing)
            'default_score': 50,               # v3.0: 中点起步
            'fetch_ok_bonus': 3,
            'fetch_empty_penalty': 5,
            'fetch_fail_penalty': 10,
            'fetch_timeout_penalty': 8,
            'nq_high_bonus': 2,
            'nq_low_penalty': 3,
            'nq_terrible_penalty': 8,
            'low_score_cutoff': 30,            # 报告阈值
            'low_quality_cutoff': 50,          # 节点质量分档分界
            # 兼容旧前端字段 (v2.3 命名, 仍渲染但不再触发拉黑)
            'kill_threshold_lq': 5,
            'kill_threshold_lst': 15,
            'fail_threshold_candidate': 3,
            'fail_threshold_whitelist': 60,
            'pass_threshold_promote': 30,
            'blacklist_days': 30,
            'kill_threshold': 5,
            'grace_period_rounds': 0,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.exception("Error in get_sources")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        try: db.close()
        except Exception: pass


# ===== VPS 服务器状态 (基于 /proc, 不依赖 psutil) =====

# 模块级缓存: CPU 采样需要两次差值
_VPS_CACHE = {
    'cpu_total_prev': 0,
    'cpu_idle_prev': 0,
    'net_rx_prev': 0,
    'net_tx_prev': 0,
    'net_ts_prev': 0,
}


def _read_proc_stat():
    """返回 (total_jiffies, idle_jiffies)"""
    try:
        with open('/proc/stat') as f:
            line = f.readline()
        # cpu  user nice system idle iowait irq softirq steal guest guest_nice
        parts = line.split()[1:]
        nums = [int(x) for x in parts]
        total = sum(nums)
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)  # idle + iowait
        return total, idle
    except Exception:
        return 0, 0


def _read_meminfo():
    """返回 dict, 单位 bytes"""
    info = {}
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                key, _, val = line.partition(':')
                val = val.strip().split()
                if val:
                    info[key] = int(val[0]) * 1024  # kB → bytes
    except Exception:
        pass
    return info


def _read_net_dev(iface='eth0'):
    """返回 (rx_bytes, tx_bytes), 找不到接口返回 (0, 0)"""
    try:
        with open('/proc/net/dev') as f:
            for line in f:
                if ':' in line and line.split(':')[0].strip() == iface:
                    parts = line.split(':')[1].split()
                    return int(parts[0]), int(parts[8])
    except Exception:
        pass
    return 0, 0


def _detect_primary_iface():
    """找主网卡: 跳过 lo / docker* / br-* / veth*, 取流量最大的"""
    candidates = []
    try:
        with open('/proc/net/dev') as f:
            for line in f:
                if ':' not in line:
                    continue
                name = line.split(':')[0].strip()
                if name in ('lo',) or name.startswith(('docker', 'br-', 'veth', 'tun', 'tap')):
                    continue
                parts = line.split(':')[1].split()
                rx = int(parts[0])
                candidates.append((rx, name))
    except Exception:
        return 'eth0'
    if not candidates:
        return 'eth0'
    candidates.sort(reverse=True)
    return candidates[0][1]


def _read_disk_usage(path='/'):
    """返回 (total, used, free) bytes"""
    try:
        st = os.statvfs(path)
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        used = total - (st.f_bfree * st.f_frsize)
        return total, used, free
    except Exception:
        return 0, 0, 0


def _read_uptime():
    try:
        with open('/proc/uptime') as f:
            return float(f.read().split()[0])
    except Exception:
        return 0.0


def _read_loadavg():
    """返回 (load1, load5, load15, running, total)"""
    try:
        with open('/proc/loadavg') as f:
            parts = f.read().split()
        running, total = parts[3].split('/')
        return float(parts[0]), float(parts[1]), float(parts[2]), int(running), int(total)
    except Exception:
        return 0.0, 0.0, 0.0, 0, 0


def _read_cpu_model():
    try:
        with open('/proc/cpuinfo') as f:
            for line in f:
                if line.startswith('model name'):
                    return line.split(':', 1)[1].strip()
    except Exception:
        pass
    return '-'


def _read_os_pretty():
    try:
        with open('/etc/os-release') as f:
            for line in f:
                if line.startswith('PRETTY_NAME='):
                    return line.split('=', 1)[1].strip().strip('"')
    except Exception:
        pass
    return '-'


def _format_uptime_seconds(secs):
    secs = int(secs)
    days = secs // 86400
    hours = (secs % 86400) // 3600
    minutes = (secs % 3600) // 60
    if days > 0:
        return f"{days}天{hours}小时{minutes}分"
    if hours > 0:
        return f"{hours}小时{minutes}分"
    return f"{minutes}分"


@app.route('/api/vps-status')
def get_vps_status():
    """VPS 服务器整机状态: CPU / 内存 / 磁盘 / 网络 / 负载."""
    import time as _time

    # CPU 使用率: 用上次采样差值
    total_now, idle_now = _read_proc_stat()
    total_prev = _VPS_CACHE.get('cpu_total_prev', 0)
    idle_prev = _VPS_CACHE.get('cpu_idle_prev', 0)
    cpu_pct = None
    if total_prev > 0 and total_now > total_prev:
        delta_total = total_now - total_prev
        delta_idle = idle_now - idle_prev
        if delta_total > 0:
            cpu_pct = round((1 - delta_idle / delta_total) * 100, 1)
    _VPS_CACHE['cpu_total_prev'] = total_now
    _VPS_CACHE['cpu_idle_prev'] = idle_now

    # 内存
    mem = _read_meminfo()
    mem_total = mem.get('MemTotal', 0)
    mem_avail = mem.get('MemAvailable', 0)
    mem_used = max(mem_total - mem_avail, 0)
    swap_total = mem.get('SwapTotal', 0)
    swap_free = mem.get('SwapFree', 0)
    swap_used = max(swap_total - swap_free, 0)

    # 磁盘
    disk_total, disk_used, disk_free = _read_disk_usage('/')

    # 网络: 主网卡 + 速率
    iface = _detect_primary_iface()
    rx_now, tx_now = _read_net_dev(iface)
    ts_now = _time.time()
    rx_prev = _VPS_CACHE.get('net_rx_prev', 0)
    tx_prev = _VPS_CACHE.get('net_tx_prev', 0)
    ts_prev = _VPS_CACHE.get('net_ts_prev', 0)
    rx_rate = tx_rate = None
    if ts_prev > 0 and ts_now > ts_prev:
        dt = ts_now - ts_prev
        if rx_now >= rx_prev:
            rx_rate = round((rx_now - rx_prev) / dt)  # bytes/s
        if tx_now >= tx_prev:
            tx_rate = round((tx_now - tx_prev) / dt)
    _VPS_CACHE['net_rx_prev'] = rx_now
    _VPS_CACHE['net_tx_prev'] = tx_now
    _VPS_CACHE['net_ts_prev'] = ts_now

    # 负载 + 进程
    l1, l5, l15, run, total_proc = _read_loadavg()
    cores = os.cpu_count() or 1

    # 启动时间
    boot_secs = _read_uptime()

    return jsonify({
        'host': {
            'hostname': os.uname().nodename,
            'os': _read_os_pretty(),
            'kernel': os.uname().release,
            'arch': os.uname().machine,
            'cpu_model': _read_cpu_model(),
            'cpu_cores': cores,
            'uptime_seconds': boot_secs,
            'uptime_human': _format_uptime_seconds(boot_secs),
        },
        'cpu': {
            'usage_percent': cpu_pct,   # 第一次调用为 None, 第二次后才有数
            'cores': cores,
            'load': {'1m': l1, '5m': l5, '15m': l15},
            'load_per_core': {
                '1m': round(l1 / cores, 2),
                '5m': round(l5 / cores, 2),
                '15m': round(l15 / cores, 2),
            },
        },
        'memory': {
            'total': mem_total,
            'used': mem_used,
            'available': mem_avail,
            'used_percent': round(mem_used / mem_total * 100, 1) if mem_total else 0,
            'swap_total': swap_total,
            'swap_used': swap_used,
            'swap_used_percent': round(swap_used / swap_total * 100, 1) if swap_total else 0,
        },
        'disk': {
            'mount': '/',
            'total': disk_total,
            'used': disk_used,
            'free': disk_free,
            'used_percent': round(disk_used / disk_total * 100, 1) if disk_total else 0,
        },
        'network': {
            'iface': iface,
            'rx_bytes_total': rx_now,
            'tx_bytes_total': tx_now,
            'rx_bytes_per_sec': rx_rate,   # 第一次调用为 None
            'tx_bytes_per_sec': tx_rate,
        },
        'process': {
            'running': run,
            'total': total_proc,
        },
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/free-pool/discover')
def get_discover():
    """discover-airports 状态 + 最近审计报告.

    返回:
      - queue: 4 个 kind 的队列状态 (扫描进度 / 错误)
      - last_run: 最近一次跑的开始/结束时间 + 总用时
      - recent_added: 最近 7 天 INSERT 进 sources 表的源 (note 含 'discovered_by=')
      - audits: 最近 30 天 audit 记录摘要 (按严重度 + 最新 20 条)
    """
    import sqlite3 as sq
    SCORES_DB = "/opt/subs-check/scripts/source-scores.db"
    if not os.path.exists(SCORES_DB):
        return jsonify({'error': 'source-scores.db not found'}), 503
    try:
        db = sq.connect(f"file:{SCORES_DB}?mode=ro", uri=True)
        # 队列状态
        queue = []
        for row in db.execute("""
            SELECT key, kind, priority, last_scanned_at, last_status,
                   last_added_count, total_added_count, consecutive_empty,
                   enabled, note
            FROM discovery_state
            ORDER BY kind, priority, key
        """).fetchall():
            queue.append({
                'key': row[0], 'kind': row[1], 'priority': row[2],
                'last_scanned_at': row[3], 'last_status': row[4],
                'last_added_count': row[5], 'total_added_count': row[6],
                'consecutive_empty': row[7], 'enabled': bool(row[8]),
                'note': row[9],
            })

        # kind 汇总
        kind_summary = {}
        for q in queue:
            k = q['kind']
            d = kind_summary.setdefault(k, {
                'total': 0, 'enabled': 0, 'scanned_24h': 0,
                'errors': 0, 'last_added_total': 0,
            })
            d['total'] += 1
            if q['enabled']:
                d['enabled'] += 1
            d['last_added_total'] += q['total_added_count'] or 0
            if q['last_status'] and q['last_status'] != 'ok':
                d['errors'] += 1
            if q['last_scanned_at']:
                # 简单判定 24h: ISO 字符串字典序比较, 取 24h 前作 cutoff
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
                if q['last_scanned_at'] >= cutoff:
                    d['scanned_24h'] += 1

        # 最近 7 天新增源 (sources.note 含 'discovered_by=')
        cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ')
        recent_added = []
        for r in db.execute("""
            SELECT url, first_seen, score, status, note
            FROM sources
            WHERE note LIKE 'discovered_by=%' AND first_seen >= ?
            ORDER BY first_seen DESC LIMIT 50
        """, (cutoff_7d,)).fetchall():
            recent_added.append({
                'url': r[0], 'first_seen': r[1],
                'score': round(r[2], 1) if r[2] is not None else None,
                'status': r[3], 'note': r[4],
            })

        # 审计统计 (最近 30 天 + 各严重度计数)
        cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
        sev_counts = dict(db.execute("""
            SELECT severity, COUNT(*) FROM source_audits
            WHERE audited_at >= ?
            GROUP BY severity
        """, (cutoff_30d,)).fetchall())

        audit_recent = []
        for r in db.execute("""
            SELECT audited_at, source_url, severity, finding
            FROM source_audits
            ORDER BY audited_at DESC LIMIT 20
        """).fetchall():
            audit_recent.append({
                'audited_at': r[0], 'source_url': r[1],
                'severity': r[2], 'finding': r[3],
            })

        # 最近一次跑 (从 discovery_state.last_scanned_at 取最大)
        last_run = db.execute(
            "SELECT MAX(last_scanned_at) FROM discovery_state WHERE last_scanned_at IS NOT NULL"
        ).fetchone()[0]

        # discovery_state 总数 (用于无数据状态判断)
        total_states = db.execute("SELECT COUNT(*) FROM discovery_state").fetchone()[0]

        db.close()
        return jsonify({
            'rules_version': 'discover-v1',
            'last_run_at': last_run,
            'total_states': total_states,
            'kind_summary': kind_summary,
            'queue': queue,
            'recent_added_7d': recent_added,
            'audit_severity_30d': sev_counts,
            'audit_recent_20': audit_recent,
        })
    except Exception as e:
        logger.exception("Error in get_discover")
        return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
