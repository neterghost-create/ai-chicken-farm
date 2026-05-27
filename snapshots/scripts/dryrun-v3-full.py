#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dryrun-v3-full.py — 節點+源 聯合評分模擬 (v3.0)

驗證:
  1. 節點評分: 均勻 0-100 初始化, TESTING/DECAYING/RECOVERING
  2. 源評分: 均勻 0-100 初始化, 拉取+質量反饋
  3. 聯動: 節點質量 → 源評分 (單向)
  4. 選源: score ≥ 50 才選
  5. 邏輯問題: 循環/死鎖/資源爆炸
"""
import sqlite3
import random
import sys
import os
from collections import defaultdict

# ============================================================
# 常量
# ============================================================
PASSIVE_RATE = 1
JITTER = 0.3

# 節點級
NODE_PASS = +5
NODE_FAIL = -10
NODE_SPEED_EXCEL = +3
NODE_SPEED_GOOD = +1
NODE_SPEED_OK = 0
NODE_SPEED_POOR = -2
NODE_SPEED_TERRIBLE = -5
NODE_SPEED_TIMEOUT = -8
NODE_PRESENT = +1
NODE_ABSENT = -3

# 源級
SOURCE_FETCH_OK = +3
SOURCE_FETCH_EMPTY = -5
SOURCE_FETCH_FAIL = -10
SOURCE_FETCH_TIMEOUT = -8
SOURCE_NQ_HIGH = +2
SOURCE_NQ_MID = 0
SOURCE_NQ_LOW = -3
SOURCE_NQ_TERRIBLE = -8
SOURCE_MIN_NODES = 5

MAX_SOURCES = 80

# ============================================================
# 節點
# ============================================================
class Node:
    TESTING = 'testing'
    DECAYING = 'decaying'
    RECOVERING = 'recovering'
    
    def __init__(self, sig, is_good, score=None):
        self.sig = sig
        self.is_good = is_good
        self.score = score if score is not None else random.uniform(0, 100)
        self.state = self.TESTING
        self.history = [self.score]
        self.state_history = [self.state]
        self.tested_rounds = 0
        self.first_stable = None
    
    def tick(self, round_id):
        tested = False
        
        if self.state == self.DECAYING:
            self.score -= (PASSIVE_RATE + random.uniform(-JITTER, JITTER))
            if self.score <= 50:
                self.score = 50
                self.state = self.TESTING
        elif self.state == self.RECOVERING:
            self.score += (PASSIVE_RATE + random.uniform(-JITTER, JITTER))
            if self.score >= 50:
                self.score = 50
                self.state = self.TESTING
        elif self.state == self.TESTING:
            tested = True
            self.tested_rounds += 1
            delta = 0
            
            # 測活
            if self.is_good:
                if random.random() < 0.92:
                    delta += NODE_PASS
                else:
                    delta += NODE_FAIL
            else:
                if random.random() < 0.15:
                    delta += NODE_PASS
                else:
                    delta += NODE_FAIL
            
            # 測速
            if delta > 0:
                r = random.random()
                if r < 0.15: delta += NODE_SPEED_EXCEL
                elif r < 0.35: delta += NODE_SPEED_GOOD
                elif r < 0.60: delta += NODE_SPEED_OK
                elif r < 0.80: delta += NODE_SPEED_POOR
                elif r < 0.95: delta += NODE_SPEED_TERRIBLE
                else: delta += NODE_SPEED_TIMEOUT
            
            # 出現
            delta += NODE_PRESENT
            
            self.score += delta
            
            if self.score >= 100:
                self.score = 100
                self.state = self.DECAYING
            elif self.score <= 0:
                self.score = 0
                self.state = self.RECOVERING
        
        self.score = max(0.0, min(100.0, self.score))
        self.history.append(self.score)
        self.state_history.append(self.state)
        
        if self.first_stable is None and len(self.history) > 3:
            if all(s >= 95 for s in self.history[-3:]):
                self.first_stable = round_id
        
        return tested


# ============================================================
# 源
# ============================================================
class Source:
    TESTING = 'testing'
    DECAYING = 'decaying'
    RECOVERING = 'recovering'
    
    def __init__(self, url, is_good, score=None):
        self.url = url
        self.is_good = is_good
        self.score = score if score is not None else random.uniform(0, 100)
        self.state = self.TESTING
        self.history = [self.score]
        self.state_history = [self.state]
        self.tested_rounds = 0
        self.nodes_contributed = 0  # 本源貢獻的節點數
    
    def tick(self, round_id, fetched_today=False, node_avg_quality=None):
        tested = False
        
        if self.state == self.DECAYING:
            self.score -= (PASSIVE_RATE + random.uniform(-JITTER, JITTER))
            if self.score <= 50:
                self.score = 50
                self.state = self.TESTING
        elif self.state == self.RECOVERING:
            self.score += (PASSIVE_RATE + random.uniform(-JITTER, JITTER))
            if self.score >= 50:
                self.score = 50
                self.state = self.TESTING
        elif self.state == self.TESTING:
            tested = True
            self.tested_rounds += 1
            delta = 0
            
            # 拉取事件 (每天只觸發一次)
            if fetched_today:
                if self.is_good:
                    if random.random() < 0.95:
                        delta += SOURCE_FETCH_OK
                        self.nodes_contributed = random.randint(10, 200)
                    else:
                        delta += SOURCE_FETCH_FAIL
                        self.nodes_contributed = 0
                else:
                    if random.random() < 0.12:
                        delta += SOURCE_FETCH_OK
                        self.nodes_contributed = random.randint(1, 50)
                    else:
                        delta += SOURCE_FETCH_FAIL
                        self.nodes_contributed = 0
            
            # 節點質量反饋
            if node_avg_quality is not None and self.nodes_contributed >= SOURCE_MIN_NODES:
                if node_avg_quality >= 70:
                    delta += SOURCE_NQ_HIGH
                elif node_avg_quality >= 50:
                    delta += SOURCE_NQ_MID
                elif node_avg_quality >= 30:
                    delta += SOURCE_NQ_LOW
                else:
                    delta += SOURCE_NQ_TERRIBLE
            
            self.score += delta
            
            if self.score >= 100:
                self.score = 100
                self.state = self.DECAYING
            elif self.score <= 0:
                self.score = 0
                self.state = self.RECOVERING
        
        self.score = max(0.0, min(100.0, self.score))
        self.history.append(self.score)
        self.state_history.append(self.state)
        return tested


# ============================================================
# 一輪模擬
# ============================================================
def simulate_round(nodes, sources, round_id, is_fetch_day=False):
    # 1. 選源: 未測試的優先, 再按分數降序
    untested = [s for s in sources if s.score >= 50 and s.tested_rounds == 0]
    tested_active = [s for s in sources if s.score >= 50 and s.tested_rounds > 0]
    tested_active.sort(key=lambda s: -s.score)
    
    selected = untested + tested_active
    selected = selected[:MAX_SOURCES]
    selected_urls = {s.url for s in selected}
    
    # 2. 節點 tick
    nodes_tested = 0
    for n in nodes:
        if n.tick(round_id):
            nodes_tested += 1
    
    # 3. 源 tick (只有選中的)
    #    計算每個源的節點質量反饋
    sources_tested = 0
    source_node_quality = {}  # url → avg_quality
    
    # 先模擬源的拉取結果
    for s in sources:
        if s.url in selected_urls:
            fetched = is_fetch_day  # 每天只拉取一次
            # 模擬節點質量 (如果有貢獻節點)
            nq = None
            if s.nodes_contributed > 0:
                if s.is_good:
                    nq = random.uniform(70, 100)
                else:
                    nq = random.uniform(10, 50)
            if s.tick(round_id, fetched_today=fetched, node_avg_quality=nq):
                sources_tested += 1
    
    # 統計
    n_dist = defaultdict(int)
    for n in nodes:
        if n.state == 'testing': n_dist['testing'] += 1
        elif n.state == 'decaying': n_dist['decaying'] += 1
        elif n.state == 'recovering': n_dist['recovering'] += 1
    
    s_dist = defaultdict(int)
    for s in sources:
        if s.state == 'testing': s_dist['testing'] += 1
        elif s.state == 'decaying': s_dist['decaying'] += 1
        elif s.state == 'recovering': s_dist['recovering'] += 1
    
    return {
        'nodes_tested': nodes_tested,
        'sources_selected': len(selected),
        'sources_tested': sources_tested,
        'n_dist': dict(n_dist),
        's_dist': dict(s_dist),
    }


# ============================================================
# 載入數據
# ============================================================
def load_data():
    scripts = "/opt/subs-check/scripts"
    sources, nodes = [], []
    db = sqlite3.connect(f"{scripts}/source-scores.db")
    for url, score in db.execute("SELECT url, score FROM sources").fetchall():
        sources.append({'url': url, 'score': score or 100.0})
    db.close()
    db = sqlite3.connect(f"{scripts}/history.db")
    for sig, score, apps, cons, proto in db.execute(
        "SELECT canonical_sig, quality_score, total_appearances, consecutive_appearances, protocol "
        "FROM nodes_history").fetchall():
        nodes.append({'sig': sig, 'score': score or 100.0, 'proto': proto})
    db.close()
    return sources, nodes


def run_sim(sources_data, nodes_data, rounds=100, seed=42):
    random.seed(seed)
    # 均勻 0-100 初始化
    nodes = [Node(nd['sig'], nd['score'] >= 80) for nd in nodes_data]
    sources = [Source(sd['url'], sd['score'] >= 80) for sd in sources_data]
    
    stats = []
    for r in range(1, rounds + 1):
        is_fetch = (r % 6 == 0)  # 模擬每 6 輪拉取一次 (24h / 6h)
        stats.append(simulate_round(nodes, sources, r, is_fetch_day=is_fetch))
    
    return nodes, sources, stats


def report(nodes, sources, stats, verbose=False):
    rounds = len(stats)
    total_n = len(nodes)
    total_s = len(sources)
    
    good_n = [n for n in nodes if n.is_good]
    bad_n = [n for n in nodes if not n.is_good]
    good_s = [s for s in sources if s.is_good]
    bad_s = [s for s in sources if not s.is_good]
    
    gn_f = [n.score for n in good_n]
    bn_f = [n.score for n in bad_n]
    gs_f = [s.score for s in good_s]
    bs_f = [s.score for n in bad_s] if bad_s else []
    
    avg_nt = sum(r['nodes_tested'] for r in stats) / rounds
    avg_ss = sum(r['sources_selected'] for r in stats) / rounds
    
    # 狀態統計
    n_testing = sum(1 for n in nodes if n.state == 'testing')
    n_decaying = sum(1 for n in nodes if n.state == 'decaying')
    n_recovering = sum(1 for n in nodes if n.state == 'recovering')
    s_testing = sum(1 for s in sources if s.state == 'testing')
    s_decaying = sum(1 for s in sources if s.state == 'decaying')
    s_recovering = sum(1 for s in sources if s.state == 'recovering')
    
    # 節點穩定性
    gn_stable = [n.first_stable for n in good_n if n.first_stable]
    
    print(f"\n{'═'*70}")
    print(f"  {len(good_n)} 好節點 | {len(bad_n)} 差節點 | {total_s} 源")
    print(f"{'═'*70}")
    
    print(f"\n  📊 節點級:")
    print(f"     好: 均分 {sum(gn_f)/len(gn_f):>5.1f} | 最低 {min(gn_f):>5.1f} | "
          f"測 {sum(n.tested_rounds for n in good_n)/len(good_n):.0f}/{rounds} 輪")
    if bad_n:
        print(f"     差: 均分 {sum(bn_f)/len(bn_f):>5.1f} | 最低 {min(bn_f):>5.1f} | "
              f"測 {sum(n.tested_rounds for n in bad_n)/len(bad_n):.0f}/{rounds} 輪")
    print(f"     狀態: 測試 {n_testing} | 退化 {n_decaying} | 恢復 {n_recovering}")
    print(f"     分差: {sum(gn_f)/len(gn_f) - sum(bn_f)/len(bn_f):.1f}")
    
    print(f"\n  📊 源級:")
    print(f"     好: {len(good_s)} 個 | 均分 {sum(gs_f)/len(gs_f):.1f}" if gs_f else f"     好: {len(good_s)} 個")
    if bad_s:
        print(f"     差: {len(bad_s)} 個 | 均分 {sum(s.score for s in bad_s)/len(bad_s):.1f}")
    print(f"     狀態: 測試 {s_testing} | 退化 {s_decaying} | 恢復 {s_recovering}")
    
    # 源分數分佈
    print(f"\n  📊 源分數分佈 (第 {rounds} 輪):")
    for lo, hi, label in [(90, 100.5, '≥90'), (70, 90, '70-89'), (50, 70, '50-69'),
                          (30, 50, '30-49'), (10, 30, '10-29'), (0, 10, '<10')]:
        c = len([s for s in sources if lo <= s.score < hi])
        pct = c * 100 // total_s if total_s else 0
        bar = '█' * (pct // 2)
        print(f"     {label:>8}: {c:>4} ({pct:>2}%) {bar}")
    
    print(f"\n  📊 資源 ({rounds} 輪平均):")
    print(f"     每輪測試節點: {avg_nt:.0f} / {total_n} ({avg_nt*100/total_n:.0f}%)")
    print(f"     每輪選源: {avg_ss:.1f} / {MAX_SOURCES}")
    
    # 趨勢
    if verbose:
        print(f"\n  📊 趨勢 (每 10 輪):")
        for i in range(0, rounds, 10):
            chunk = stats[i:i+10]
            avg_tt = sum(r['nodes_tested'] for r in chunk) / len(chunk)
            avg_ss2 = sum(r['sources_selected'] for r in chunk) / len(chunk)
            d = chunk[-1]['n_dist']
            sd = chunk[-1]['s_dist']
            print(f"     輪 {i+1:>2}-{i+10:>2}: 測 {avg_tt:>5.0f} 節點 | 選 {avg_ss2:>5.1f} 源 | "
                  f"節點[測{d.get('testing',0):>4} 退{d.get('decaying',0):>4} 恢{d.get('recovering',0):>3}] | "
                  f"源[測{sd.get('testing',0):>3} 退{sd.get('decaying',0):>3} 恢{sd.get('recovering',0):>3}]")
    
    # 邏輯檢查
    print(f"\n  🔍 邏輯檢查:")
    issues = []
    
    # 1. 好差分離
    sep = sum(gn_f)/len(gn_f) - sum(bn_f)/len(bn_f) if bad_n else 0
    if sep < 30:
        issues.append(f"⚠️ 好差分離不足: {sep:.1f} (理想 > 30)")
    else:
        print(f"     ✅ 好差分離: {sep:.1f}")
    
    # 2. 好節點不低於 50
    below_50 = len([n for n in good_n if n.score < 50])
    if below_50 > 0:
        issues.append(f"⚠️ {below_50} 個好節點低於 50 分")
    else:
        print(f"     ✅ 好節點全部 ≥ 50")
    
    # 3. 差節點不高於 50
    above_50 = len([n for n in bad_n if n.score >= 50]) if bad_n else 0
    if above_50 > len(bad_n) * 0.1:
        issues.append(f"⚠️ {above_50} 個差節點 ≥ 50 分 ({above_50*100//max(len(bad_n),1)}%)")
    else:
        print(f"     ✅ 差節點 ≤ 50: {above_50}/{len(bad_n)}")
    
    # 4. 源不會全部停選
    eligible = len([s for s in sources if s.score >= 50])
    if eligible < 20:
        issues.append(f"⚠️ 只有 {eligible} 個源可選 (太少)")
    else:
        print(f"     ✅ 可選源: {eligible}/{total_s}")
    
    # 5. 無死鎖 (所有節點/源都在恢復或退化)
    if n_testing == 0 and s_testing == 0:
        issues.append(f"⚠️ 無任何節點/源在測試 (可能死鎖)")
    else:
        print(f"     ✅ 測試中: {n_testing} 節點 + {s_testing} 源")
    
    # 6. 峰谷比
    trend = [r['nodes_tested'] for r in stats[5:]]  # 排除初始
    if trend:
        peak = max(trend)
        valley = min(trend)
        ratio = peak / max(valley, 1)
        if ratio > 10:
            issues.append(f"⚠️ 測試峰谷比: {ratio:.1f} (理想 < 10)")
        else:
            print(f"     ✅ 測試峰谷比: {ratio:.1f}")
    
    if issues:
        print(f"\n  ❌ 發現 {len(issues)} 個問題:")
        for issue in issues:
            print(f"     {issue}")
    else:
        print(f"\n  ✅ 無邏輯問題!")
    
    return issues


# ============================================================
# Main
# ============================================================
def main():
    print("═" * 70)
    print("  dryrun-v3-full.py — 節點+源 聯合評分模擬")
    print("  初始分: 均勻 [0, 100] | 閾值: 50 | Jitter: ±0.3")
    print("═" * 70)
    
    print("\n📦 載入真實數據...")
    sources_data, nodes_data = load_data()
    print(f"   源: {len(sources_data)} 個 | 節點: {len(nodes_data)} 個")
    
    print(f"\n🔄 跑 100 輪模擬...")
    nodes, sources, stats = run_sim(sources_data, nodes_data, rounds=100)
    
    issues = report(nodes, sources, stats, verbose=True)
    
    # 場景追蹤
    print(f"\n{'═'*70}")
    print(f"  🔍 場景追蹤")
    print(f"{'═'*70}")
    
    random.seed(999)
    good_sample = random.choice([n for n in nodes if n.is_good])
    bad_sample = random.choice([n for n in nodes if not n.is_good])
    good_src = random.choice([s for s in sources if s.is_good])
    
    print(f"\n  好節點 [{good_sample.sig[:25]}...]:")
    for i in range(0, min(30, len(good_sample.history)), 10):
        chunk = [f"{x:.0f}" for x in good_sample.history[i:i+10]]
        states = good_sample.state_history[i:i+10]
        print(f"    輪{i+1:>2}-{i+10:>2}: {chunk} | {states[0]}")
    
    print(f"\n  差節點 [{bad_sample.sig[:25]}...]:")
    for i in range(0, min(30, len(bad_sample.history)), 10):
        chunk = [f"{x:.0f}" for x in bad_sample.history[i:i+10]]
        states = bad_sample.state_history[i:i+10]
        print(f"    輪{i+1:>2}-{i+10:>2}: {chunk} | {states[0]}")
    
    print(f"\n  好源 [{good_src.url[:40]}...]:")
    for i in range(0, min(30, len(good_src.history)), 10):
        chunk = [f"{x:.0f}" for x in good_src.history[i:i+10]]
        states = good_src.state_history[i:i+10]
        print(f"    輪{i+1:>2}-{i+10:>2}: {chunk} | {states[0]}")
    
    return 0 if not issues else 1


if __name__ == '__main__':
    sys.exit(main())
