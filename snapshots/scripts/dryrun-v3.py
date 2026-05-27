#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dryrun-v3.py — v3.0 評分機制模擬器 (狀態機版)

核心邏輯 (嚴格按用戶設計):
  到 0 → 停測 → 被動 +1/輪 → 直到 50 → 重新評分
  到 100 → 停測 → 被動 -1/輪 → 直到 50 → 重新評分
  
  0→50 和 100→50 期間完全不做測試，純被動漂移
  只有在 50→100 區間才做測試加減分
"""
import sqlite3
import random
import sys
import os
from collections import defaultdict

# ============================================================
# v3.0 源級常量
# ============================================================
SOURCE_FETCH_OK = +3
SOURCE_FETCH_EMPTY = -5
SOURCE_FETCH_FAIL = -10
SOURCE_NQ_HIGH = +2
SOURCE_NQ_MID = 0
SOURCE_NQ_LOW = -3
SOURCE_NQ_TERRIBLE = -8

# ============================================================
# v3.0 節點級常量
# ============================================================
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

PASSIVE_RATE = 1
JITTER_RANGE = 0.3  # 被動漂移隨機偏移 ±0.3

# ============================================================
# 節點狀態機
# ============================================================
class Node:
    """
    狀態: TESTING / DECAYING / RECOVERING
    
    TESTING: 測試中 (score 50→100 區間)
      - 每輪 apply 測試結果
      - score >= 100 → 切換到 DECAYING
      
    DECAYING: 被動退化 (score 100→50 區間)
      - 每輪 -1, 不做測試
      - score <= 50 → 切換到 TESTING
      
    RECOVERING: 被動恢復 (score 0→50 區間)
      - 每輪 +1, 不做測試
      - score >= 50 → 切換到 TESTING
    """
    TESTING = 'testing'
    DECAYING = 'decaying'
    RECOVERING = 'recovering'
    
    def __init__(self, sig, is_good, score=100.0):
        self.sig = sig
        self.is_good = is_good
        self.score = score
        # 新節點從 100 開始 → DECAYING
        self.state = self.DECAYING if score >= 100 else (
            self.TESTING if score >= 50 else self.RECOVERING
        )
        self.history = [score]
        self.state_history = [self.state]
        self.tested_rounds = 0
        self.pass_count = 0
        self.fail_count = 0
        self.first_stable = None
    
    def tick(self, round_id):
        """一輪 tick, 返回是否被測試"""
        tested = False
        
        if self.state == self.DECAYING:
            # 被動退化: -1 ± jitter, 不測試
            jitter = random.uniform(-JITTER_RANGE, JITTER_RANGE)
            self.score -= (PASSIVE_RATE + jitter)
            if self.score <= 50:
                self.score = 50
                self.state = self.TESTING
        elif self.state == self.RECOVERING:
            # 被動恢復: +1 ± jitter, 不測試
            jitter = random.uniform(-JITTER_RANGE, JITTER_RANGE)
            self.score += (PASSIVE_RATE + jitter)
            if self.score >= 50:
                self.score = 50
                self.state = self.TESTING
        elif self.state == self.TESTING:
            # 活躍測試
            tested = True
            self.tested_rounds += 1
            delta = 0
            
            # 測活
            if self.is_good:
                if random.random() < 0.92:
                    delta += NODE_PASS
                    self.pass_count += 1
                else:
                    delta += NODE_FAIL
                    self.fail_count += 1
            else:
                if random.random() < 0.15:
                    delta += NODE_PASS
                    self.pass_count += 1
                else:
                    delta += NODE_FAIL
                    self.fail_count += 1
            
            # 測速 (僅測活通過時)
            if delta > 0:
                r = random.random()
                if r < 0.15:
                    delta += NODE_SPEED_EXCEL
                elif r < 0.35:
                    delta += NODE_SPEED_GOOD
                elif r < 0.60:
                    delta += NODE_SPEED_OK
                elif r < 0.80:
                    delta += NODE_SPEED_POOR
                elif r < 0.95:
                    delta += NODE_SPEED_TERRIBLE
                else:
                    delta += NODE_SPEED_TIMEOUT
            
            # 出現獎勵
            delta += NODE_PRESENT
            
            self.score += delta
            
            # 狀態轉換
            if self.score >= 100:
                self.score = 100
                self.state = self.DECAYING
            elif self.score <= 0:
                self.score = 0
                self.state = self.RECOVERING
            # 否則保持 TESTING
        
        self.score = max(0.0, min(100.0, self.score))
        self.history.append(self.score)
        self.state_history.append(self.state)
        
        # 穩定追蹤
        if self.first_stable is None and len(self.history) > 3:
            if all(s >= 95 for s in self.history[-3:]):
                self.first_stable = round_id
        
        return tested


# ============================================================
# 源狀態機
# ============================================================
class Source:
    TESTING = 'testing'
    DECAYING = 'decaying'
    RECOVERING = 'recovering'
    
    def __init__(self, url, is_good, score=100.0):
        self.url = url
        self.is_good = is_good
        self.score = score
        self.state = self.DECAYING if score >= 100 else (
            self.TESTING if score >= 50 else self.RECOVERING
        )
        self.history = [score]
        self.state_history = [self.state]
        self.tested_rounds = 0
    
    def tick(self, round_id, node_avg_quality=None):
        tested = False
        
        if self.state == self.DECAYING:
            jitter = random.uniform(-JITTER_RANGE, JITTER_RANGE)
            self.score -= (PASSIVE_RATE + jitter)
            if self.score <= 50:
                self.score = 50
                self.state = self.TESTING
        elif self.state == self.RECOVERING:
            jitter = random.uniform(-JITTER_RANGE, JITTER_RANGE)
            self.score += (PASSIVE_RATE + jitter)
            if self.score >= 50:
                self.score = 50
                self.state = self.TESTING
        elif self.state == self.TESTING:
            tested = True
            self.tested_rounds += 1
            delta = 0
            
            # 拉取事件
            if self.is_good:
                if random.random() < 0.95:
                    delta += SOURCE_FETCH_OK
                else:
                    delta += SOURCE_FETCH_FAIL
            else:
                if random.random() < 0.12:
                    delta += SOURCE_FETCH_OK
                else:
                    delta += SOURCE_FETCH_FAIL
            
            # 節點質量反饋
            if node_avg_quality is not None:
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
def simulate_round(nodes, sources, round_id, threshold, max_sources=80):
    # 源選擇: state=TESTING 且 score >= threshold
    eligible = [s for s in sources if s.state == 'testing' and s.score >= threshold]
    eligible.sort(key=lambda s: -s.score)
    selected = eligible[:max_sources]
    selected_urls = {s.url for s in selected}
    
    # 節點 tick
    nodes_tested = 0
    for n in nodes:
        if n.tick(round_id):
            nodes_tested += 1
    
    # 源 tick
    sources_tested = 0
    for s in sources:
        if s.url in selected_urls:
            nq = random.uniform(70, 100) if s.is_good else random.uniform(10, 50)
            if s.tick(round_id, nq):
                sources_tested += 1
    
    # 統計
    dist = defaultdict(int)
    for n in nodes:
        if n.state == 'decaying': dist['decaying'] += 1
        elif n.state == 'recovering': dist['recovering'] += 1
        elif n.state == 'testing': dist['testing'] += 1
    
    s_dist = defaultdict(int)
    for s in sources:
        if s.state == 'decaying': s_dist['decaying'] += 1
        elif s.state == 'recovering': s_dist['recovering'] += 1
        elif s.state == 'testing': s_dist['testing'] += 1
    
    return {
        'nodes_tested': nodes_tested,
        'sources_selected': len(selected),
        'sources_tested': sources_tested,
        'node_dist': dict(dist),
        'src_dist': dict(s_dist),
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


def run_sim(sources_data, nodes_data, threshold, rounds=50, seed=42, init_score=50.0):
    random.seed(seed)
    nodes = [Node(nd['sig'], nd['score'] >= 80, init_score) for nd in nodes_data]
    sources = [Source(sd['url'], sd['score'] >= 80, init_score) for sd in sources_data]
    stats = []
    for r in range(1, rounds + 1):
        stats.append(simulate_round(nodes, sources, r, threshold))
    return nodes, sources, stats


def report(threshold, nodes, sources, stats, verbose=False):
    good_n = [n for n in nodes if n.is_good]
    bad_n = [n for n in nodes if not n.is_good]
    good_s = [s for s in sources if s.is_good]
    bad_s = [s for s in sources if not s.is_good]
    rounds = len(stats)
    total_n = len(nodes)
    
    gn_f = [n.score for n in good_n]
    bn_f = [n.score for n in bad_n]
    gn_t = [n.tested_rounds for n in good_n]
    bn_t = [n.tested_rounds for n in bad_n]
    gn_stable = [n.first_stable for n in good_n if n.first_stable]
    gs_f = [s.score for s in good_s]
    bs_f = [s.score for s in bad_s]
    
    avg_t = sum(r['nodes_tested'] for r in stats) / rounds
    avg_s = sum(r['sources_selected'] for r in stats) / rounds
    last_n = stats[-1]['node_dist']
    last_s = stats[-1]['src_dist']
    
    # 狀態分佈
    n_testing = sum(1 for n in nodes if n.state == 'testing')
    n_decaying = sum(1 for n in nodes if n.state == 'decaying')
    n_recovering = sum(1 for n in nodes if n.state == 'recovering')
    s_testing = sum(1 for s in sources if s.state == 'testing')
    s_decaying = sum(1 for s in sources if s.state == 'decaying')
    s_recovering = sum(1 for s in sources if s.state == 'recovering')
    
    print(f"\n{'═'*70}")
    print(f"  閾值={threshold}  |  {len(good_n)} 好  |  {len(bad_n)} 差  |  {len(sources)} 源")
    print(f"{'═'*70}")
    
    print(f"\n  📊 節點級:")
    print(f"     好: 均分 {sum(gn_f)/len(gn_f):>5.1f} | 最低 {min(gn_f):>5.1f} | "
          f"測 {sum(gn_t)/len(gn_t):.0f}/{rounds} 輪 | 穩定 ~{sum(gn_stable)/len(gn_stable):.0f} 輪" if gn_stable else
          f"     好: 均分 {sum(gn_f)/len(gn_f):>5.1f} | 最低 {min(gn_f):>5.1f}")
    print(f"     差: 均分 {sum(bn_f)/len(bn_f):>5.1f} | 最低 {min(bn_f):>5.1f} | "
          f"測 {sum(bn_t)/len(bn_t):.0f}/{rounds} 輪")
    print(f"     狀態: 測試 {n_testing} | 退化 {n_decaying} | 恢復 {n_recovering}")
    
    print(f"\n  📊 源級:")
    print(f"     好: {len(good_s)} 個 | 均分 {sum(gs_f)/len(gs_f):.1f}" if gs_f else f"     好: {len(good_s)} 個")
    print(f"     差: {len(bad_s)} 個 | 均分 {sum(bs_f)/len(bs_f):.1f}" if bs_f else f"     差: {len(bad_s)} 個")
    print(f"     狀態: 測試 {s_testing} | 退化 {s_decaying} | 恢復 {s_recovering}")
    
    print(f"\n  📊 資源 ({rounds} 輪平均):")
    print(f"     每輪測試節點: {avg_t:.0f} / {total_n} ({avg_t*100/total_n:.0f}%)")
    print(f"     每輪選源: {avg_s:.1f} / 80")
    
    print(f"\n  📊 第 {rounds} 輪分佈:")
    for k, label in [('testing', f'測試中 [{threshold}-99]'), ('decaying', '退化中 [100→50]'),
                     ('recovering', f'恢復中 [0→50]')]:
        v = last_n.get(k, 0)
        pct = v * 100 // total_n if total_n else 0
        bar = '█' * (pct // 2)
        print(f"     節點 {label:>18}: {v:>5} ({pct:>2}%) {bar}")
    for k, label in [('testing', f'測試中 [{threshold}-99]'), ('decaying', '退化中 [100→50]'),
                     ('recovering', f'恢復中 [0→50]')]:
        v = last_s.get(k, 0)
        pct = v * 100 // len(sources) if sources else 0
        bar = '█' * (pct // 2)
        print(f"     源   {label:>18}: {v:>5} ({pct:>2}%) {bar}")
    
    if verbose:
        print(f"\n  📊 趨勢 (每 5 輪):")
        for i in range(0, rounds, 5):
            chunk = stats[i:i+5]
            avg_tt = sum(r['nodes_tested'] for r in chunk) / len(chunk)
            d = chunk[-1]['node_dist']
            print(f"     輪 {i+1:>2}-{i+5:>2}: 測 {avg_tt:>5.0f} | "
                  f"測試 {d.get('testing',0):>4} | 退化 {d.get('decaying',0):>4} | "
                  f"恢復 {d.get('recovering',0):>3}")
    
    return {
        'threshold': threshold,
        'good_avg': sum(gn_f)/len(gn_f) if gn_f else 0,
        'bad_avg': sum(bn_f)/len(bn_f) if bn_f else 0,
        'good_min': min(gn_f) if gn_f else 0,
        'bad_min': min(bn_f) if bn_f else 0,
        'good_stable': sum(gn_stable)/len(gn_stable) if gn_stable else 999,
        'avg_tested': avg_t,
        'avg_selected': avg_s,
        'n_testing': n_testing,
        'n_decaying': n_decaying,
        'n_recovering': n_recovering,
        's_testing': s_testing,
        's_decaying': s_decaying,
        's_recovering': s_recovering,
    }


def comparison(results, total_n, total_s):
    print(f"\n{'═'*95}")
    print(f"  📊 多閾值比較 (50 輪)")
    print(f"{'═'*95}")
    
    h = (f"  {'閾':>2} │ {'好均':>4} {'好低':>4} │ {'差均':>4} {'差低':>4} │ "
         f"{'測試':>4} {'退化':>4} {'恢復':>3} │ {'每輪測':>5} {'每輪源':>4} │ "
         f"{'源測試':>4} {'源退化':>4} {'源恢復':>3}")
    print(h)
    print(f"  {'─'*2}─┼─{'─'*4}─{'─'*4}─┼─{'─'*4}─{'─'*4}─┼─"
          f"{'─'*4}─{'─'*4}─{'─'*3}─┼─{'─'*5}─{'─'*4}─┼─"
          f"{'─'*4}─{'─'*4}─{'─'*3}")
    
    for r in results:
        print(f"  {r['threshold']:>2} │ {r['good_avg']:>4.1f} {r['good_min']:>4.0f} │ "
              f"{r['bad_avg']:>4.1f} {r['bad_min']:>4.0f} │ "
              f"{r['n_testing']:>4} {r['n_decaying']:>4} {r['n_recovering']:>3} │ "
              f"{r['avg_tested']:>5.0f} {r['avg_selected']:>4.1f} │ "
              f"{r['s_testing']:>4} {r['s_decaying']:>4} {r['s_recovering']:>3}")


def main():
    print("═" * 70)
    print("  dryrun-v3.py — 狀態機版 (到0才+1, 到100才-1)")
    print("═" * 70)
    
    print("\n📦 載入真實數據...")
    sources_data, nodes_data = load_data()
    print(f"   源: {len(sources_data)} 個 | 節點: {len(nodes_data)} 個")
    
    if not sources_data or not nodes_data:
        print("❌ 數據為空")
        return 1
    
    thresholds = [50]
    all_results = []
    all_nodes = {}
    
    for t in thresholds:
        print(f"\n🔄 模擬閾值={t}, 初始分=50, 100輪...")
        nodes, sources, stats = run_sim(sources_data, nodes_data, t, rounds=100)
        all_nodes[t] = nodes
        r = report(t, nodes, sources, stats, verbose=True)
        all_results.append(r)
    
    comparison(all_results, len(nodes_data), len(sources_data))
    
    # 深入分析
    print(f"\n{'═'*70}")
    print(f"  🔍 深入分析")
    print(f"{'═'*70}")
    
    n50 = all_nodes[50]
    good_50 = [n for n in n50 if n.is_good]
    bad_50 = [n for n in n50 if not n.is_good]
    
    print(f"\n  好節點分數分佈:")
    bands = [(99, 100.5, '≥99'), (90, 99, '90-98'), (80, 90, '80-89'),
             (70, 80, '70-79'), (60, 70, '60-69'), (50, 60, '50-59'), (0, 50, '<50')]
    for lo, hi, label in bands:
        c = len([n for n in good_50 if lo <= n.score < hi])
        pct = c * 100 // len(good_50) if good_50 else 0
        bar = '█' * (pct // 2)
        print(f"     {label:>8}: {c:>5} ({pct:>2}%) {bar}")
    
    print(f"\n  差節點分數分佈:")
    for lo, hi, label in bands:
        c = len([n for n in bad_50 if lo <= n.score < hi])
        pct = c * 100 // len(bad_50) if bad_50 else 0
        bar = '█' * (pct // 2)
        print(f"     {label:>8}: {c:>5} ({pct:>2}%) {bar}")
    
    # 狀態追蹤
    print(f"\n  好節點狀態分佈:")
    for st in ['testing', 'decaying', 'recovering']:
        c = len([n for n in good_50 if n.state == st])
        pct = c * 100 // len(good_50) if good_50 else 0
        print(f"     {st:>12}: {c:>5} ({pct:>2}%)")
    
    print(f"\n  差節點狀態分佈:")
    for st in ['testing', 'decaying', 'recovering']:
        c = len([n for n in bad_50 if n.state == st])
        pct = c * 100 // len(bad_50) if bad_50 else 0
        print(f"     {st:>12}: {c:>5} ({pct:>2}%)")
    
    # 穩定性
    stable_3 = len([n for n in good_50 if n.first_stable and n.first_stable <= 3])
    stable_5 = len([n for n in good_50 if n.first_stable and n.first_stable <= 5])
    never = len([n for n in good_50 if n.first_stable is None])
    print(f"\n  好節點穩定性:")
    print(f"     3 輪內: {stable_3} ({stable_3*100//len(good_50)}%)")
    print(f"     5 輪內: {stable_5} ({stable_5*100//len(good_50)}%)")
    print(f"     未穩定: {never} ({never*100//len(good_50)}%)")
    
    # 場景追蹤
    print(f"\n  場景追蹤 (隨機 1 個好節點 + 1 個差節點):")
    random.seed(99)
    sample_good = random.choice(good_50)
    sample_bad = random.choice(bad_50)
    print(f"    好節點 [{sample_good.sig[:20]}...]:")
    for i in range(0, min(20, len(sample_good.history)), 5):
        chunk = sample_good.history[i:i+5]
        states = sample_good.state_history[i:i+5]
        print(f"      輪{i+1:>2}-{i+5:>2}: {chunk} | {states}")
    print(f"    差節點 [{sample_bad.sig[:20]}...]:")
    for i in range(0, min(20, len(sample_bad.history)), 5):
        chunk = sample_bad.history[i:i+5]
        states = sample_bad.state_history[i:i+5]
        print(f"      輪{i+1:>2}-{i+5:>2}: {chunk} | {states}")
    
    r50 = all_results[0]
    print(f"\n{'═'*70}")
    print(f"  📋 結論")
    print(f"{'═'*70}")
    print(f"""
  狀態機版模擬結果 (閾值 50, 50 輪):
  
  節點級:
    好: 均分 {r50['good_avg']:.1f}, 最低 {r50['good_min']:.0f}
    差: 均分 {r50['bad_avg']:.1f}, 最低 {r50['bad_min']:.0f}
    分差: {r50['good_avg'] - r50['bad_avg']:.1f}
  
  狀態分佈:
    節點: 測試 {r50['n_testing']} | 退化 {r50['n_decaying']} | 恢復 {r50['n_recovering']}
    源:   測試 {r50['s_testing']} | 退化 {r50['s_decaying']} | 恢復 {r50['s_recovering']}
  
  資源:
    每輪測 {r50['avg_tested']:.0f} / {len(nodes_data)} 節點
    每輪選 {r50['avg_selected']:.1f} / 80 源
""")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
