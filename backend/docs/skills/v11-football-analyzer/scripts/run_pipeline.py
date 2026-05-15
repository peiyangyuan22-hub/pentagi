# -*- coding: utf-8 -*-
"""V11完整流水线：500网 → 排名 → OddsCache → Pipeline → 输出"""
import sys, json, os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from v11_odds_cache import OddsCache
from v11_rankings import RankProvider
from v11_analyzer_v2 import V11Analyzer, AvgOdds, Match, kelly_criterion

print("🦞 V11 完整自动流水线")
print("=" * 55)

# 1. 500网自动抓取
print("\n📡 Step 1: 500彩票网数据抓取")
cache = OddsCache()
ok, msg, matches_500 = cache.fetch_today()
print(f"  {msg}")
if not matches_500:
    print("  ❌ 无数据，退出")
    sys.exit(1)

# 打印比赛概览
sat = [m for m in matches_500 if "周六" in m.match_id]
sun = [m for m in matches_500 if "周日" in m.match_id]
fri = [m for m in matches_500 if "周五" in m.match_id]
print(f"  周六{sat} 周五{fri} 周日{sun}")
print(f"  共{len(matches_500)}场 (周六{len(sat)}+周五{len(fri)}+周日{len(sun)})")

# 2. 排名匹配
print("\n📊 Step 2: 排名匹配")
rp = RankProvider()
v11_matches = []
ranks_found = 0
for m in matches_500:
    hr = rp.get(m.league, m.home_team)
    ar = rp.get(m.league, m.away_team)
    if hr: ranks_found += 1
    if ar: ranks_found += 1
    
    v11 = Match(
        match_id=m.match_id,
        league=m.league,
        home_team=m.home_team,
        away_team=m.away_team,
        home_rank=hr,
        away_rank=ar,
        handicap=m.handicap,
        odds_win=m.odds_win,
        odds_draw=m.odds_draw,
        odds_loss=m.odds_loss,
        avg_odds=AvgOdds(m.nspf_win, m.nspf_draw, m.nspf_loss) if m.nspf_win else None,
    )
    v11_matches.append(v11)

print(f"  匹配到 {ranks_found} 个排名（共{len(v11_matches)*2}个队）")
ranked = sum(1 for m in v11_matches if m.home_rank or m.away_rank)
print(f"  有排名数据的比赛: {ranked}/{len(v11_matches)}")

# 3. 检查是否有昨日缓存（TrendStep）
print("\n📈 Step 3: 趋势检查")
yesterday = cache.load_cache()
if yesterday:
    match_ids_today = set(m.match_id for m in matches_500)
    overlap = match_ids_today & set(yesterday.keys())
    print(f"  昨日缓存: {len(yesterday)}条, 今日重复: {len(overlap)}场")
else:
    print(f"  昨日缓存: 空（趋势对比跳过）")

# 4. Pipeline分析
print("\n🔬 Step 4: Pipeline分析")
analyzer = V11Analyzer(odds_cache=cache)
results = analyzer.analyze_matches(v11_matches)

# 5. 输出
print(f"\n📋 Pipeline输出 ({len(results)}场)")
print("-" * 55)
for i, p in enumerate(results):
    k = kelly_criterion(p.min_odd, p.confidence / 100)
    ks = f"  Kelly={k*100:.1f}%" if k > 0 else ""
    rank_info = ""
    if p.rank_note != "无排名数据":
        rank_info = f"  {p.rank_note}"
    
    print(f"\n  [{p.match_id}] {p.league} | {p.direction} {p.label} odd={p.min_odd} conf={p.confidence}%{ks}")
    print(f"  {p.vote_info}{rank_info}")

# 6. 分类统计
print(f"\n📊 分类统计")
greens = [r for r in results if "让" in r.direction and r.confidence >= 70]
yellows = [r for r in results if r.confidence >= 50 and r.confidence < 70]
blacks = [r for r in results if r.confidence == 0]

print(f"  🟢绿标: {len(greens)}")
for p in greens:
    print(f"    [{p.match_id}] {p.direction} odd={p.min_odd} conf={p.confidence}%")
print(f"  🟡黄标: {len(yellows)}")
for p in yellows:
    print(f"    [{p.match_id}] {p.direction} odd={p.min_odd} conf={p.confidence}%")
print(f"  ⚠️灰标: {len(grays)}")
print(f"  🚫不入: {len(blacks)}")

# 7. 串关
strategies = analyzer.build_strategies(results)
fund = strategies["recommended_fund"]
print(f"\n💎 串关方案")
for name, pk, kk, sk in [
    ("A 稳健基石", "strategy_a", "kelly_a", "A"),
    ("B 均衡回报", "strategy_b", "kelly_b", "B"),
    ("C 高赔冲刺", "strategy_c", "kelly_c", "C"),
]:
    picks = strategies[pk]
    f = fund[sk]
    if picks:
        combo = 1.0
        for p in picks:
            combo *= p.min_odd
        print(f"\n  [{name}]  资金={f}%  |  {combo:.2f}x")
        for i, p in enumerate(picks):
            k = kelly_criterion(p.min_odd, p.confidence / 100)
            print(f"    {i+1}. {p.match_id} {p.direction} odd={p.min_odd} conf={p.confidence}% Kelly={k*100:.1f}%")
    else:
        print(f"\n  [{name}]  (无合格4串1)")

print(f"\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("✅ 流水线完成")
