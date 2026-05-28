#!/usr/bin/env python3
"""
free-pool Telegram 通知器

逻辑:
  1. 读 history.db 最新一行
  2. 如果 notified=1 → skip (避免重复推送)
  3. 拼摘要 + 上一轮 diff
  4. 发 Telegram (复用 /etc/telegram-bot.conf)
  5. 成功后标记 notified=1

cron: 每 5 分钟跑一次, 抓到新轮次立刻推
  */5 * * * * /opt/subs-check/scripts/notify-telegram.py >> /var/log/subs-check-notify.log 2>&1
"""
import os
import sys
import json
import sqlite3
import urllib.request
import urllib.parse
from datetime import datetime, timezone

HISTORY_DB = "/opt/subs-check/scripts/history.db"
TELEGRAM_CONF = "/etc/telegram-bot.conf"
FREE_POOL_CONF = "/opt/subs-check/scripts/free-pool.conf"


def load_free_pool_conf():
    """读 token + domain"""
    cfg = {}
    if not os.path.exists(FREE_POOL_CONF):
        return cfg
    with open(FREE_POOL_CONF) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                k, v = line.split('=', 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def load_telegram_conf():
    if not os.path.exists(TELEGRAM_CONF):
        return None, None
    cfg = {}
    with open(TELEGRAM_CONF) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                k, v = line.split('=', 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg.get('TELEGRAM_BOT_TOKEN'), cfg.get('TELEGRAM_CHAT_ID')


def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        'chat_id': chat_id,
        'parse_mode': 'Markdown',
        'text': text,
    }).encode()
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"  ✗ Telegram 发送失败: {e}", file=sys.stderr)
        return False


def main():
    if not os.path.exists(HISTORY_DB):
        print(f"  ℹ️  {HISTORY_DB} 不存在, 跳过 (subs-check 还没出过结果)")
        return 0

    db = sqlite3.connect(HISTORY_DB)
    # 找最新未推送的轮次
    row = db.execute("""
        SELECT round_id, timestamp, total_nodes, protocols_json,
            diff_added, diff_removed, diff_kept
        FROM rounds
        WHERE notified = 0
        ORDER BY round_id DESC LIMIT 1
    """).fetchone()

    if not row:
        # 全部推过, noop
        return 0

    rid, ts, tot, protos_json, da, dr, dk = row

    # 上一轮 (round_id - 1)
    prev_row = db.execute("""
        SELECT total_nodes FROM rounds WHERE round_id < ? ORDER BY round_id DESC LIMIT 1
    """, (rid,)).fetchone()
    prev_tot = prev_row[0] if prev_row else None

    try:
        protos = json.loads(protos_json) if protos_json else {}
    except Exception:
        protos = {}

    # 拼消息
    dt_local = datetime.fromisoformat(ts).astimezone()
    delta = (tot - prev_tot) if prev_tot is not None else None
    delta_str = ''
    if delta is not None:
        sign = '+' if delta >= 0 else ''
        emoji = '📈' if delta > 0 else ('📉' if delta < 0 else '➡️')
        delta_str = f"{emoji} 较上轮 {sign}{delta}"
    proto_str = ' · '.join(f"{k}:{v}" for k, v in sorted(protos.items(), key=lambda x: -x[1]))

    # 拼带 token 的订阅 URL
    fp_cfg = load_free_pool_conf()
    token = fp_cfg.get('TOKEN', '')
    domain = fp_cfg.get('DOMAIN', 'example-legacy.duckdns.org')
    if token:
        sub_base = f"https://{domain}/sub/free/{token}"
        sub_block = f"""📡 订阅 (含鉴权 token, 勿外传):
• Clash/Mihomo (Provider): {sub_base}/all.yaml
• Clash/Mihomo (完整 config): {sub_base}/all-config.yaml
• v2rayN/v2rayNG: {sub_base}/v2ray.txt
• Shadowrocket (base64): {sub_base}/base64.txt
• CN 代理 (Clash/Mihomo): {sub_base}/cn.yaml"""
    else:
        sub_block = "⚠️  TOKEN 未配置, 订阅 URL 未生成"

    # 读 CN 代理统计 (cn-refresh.py 写入)
    cn_block = ""
    cn_stats_path = "/opt/ss-monitor/sub/free/cn-stats.json"
    if os.path.exists(cn_stats_path):
        try:
            with open(cn_stats_path) as f:
                cn = json.load(f)
            cn_block = f"\n🛜 CN 代理: *{cn['alive']}*/{cn['total']} ({cn['proto_str']})"
        except Exception:
            pass

    text = f"""*🆓 免费节点池 #{rid}*

⏰ {dt_local.strftime('%Y-%m-%d %H:%M:%S')}
✅ 可用节点: *{tot}*  {delta_str}
🔄 Diff: +{da} / -{dr} / ={dk}
📊 协议: {proto_str}{cn_block}

{sub_block}

🖥 Dashboard: https://{domain}/ss-monitor/"""

    token, chat_id = load_telegram_conf()
    if not token or not chat_id:
        print(f"  ℹ️  Telegram 未配置, 跳过推送")
        # 仍标记为已推送, 避免堆积
        db.execute("UPDATE rounds SET notified = 1 WHERE round_id = ?", (rid,))
        db.commit()
        return 0

    if send_telegram(token, chat_id, text):
        print(f"  ✓ 推送成功 round_id={rid}, total_nodes={tot}, delta={delta}")
        db.execute("UPDATE rounds SET notified = 1 WHERE round_id = ?", (rid,))
        db.commit()
        return 0
    else:
        print(f"  ✗ 推送失败 round_id={rid}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
