# -*- coding: utf-8 -*-
"""
V11.3 — 资金管理与投注选择模块（Positioner）
功能：
  1. Kelly仓位计算（含分数Kelly、上限裁剪）
  2. 硬约束：单场≤MAX_STAKE、每轮≤MAX_BETS
  3. 四套方案：四单/四串1/五双选/五串1双选
  4. pack_into_five(): 压缩到最多5张

参考自用户提供的"一站式足球预测-投注系统"文档
"""

import pandas as pd
import numpy as np
import itertools
from math import prod
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field


# ==================== 参数 ====================

MAX_BETS = 5               # 每轮最多几张投注
MAX_STAKE = 10.0           # 单张最高投注额（元）
MAX_BANKROLL_FRAC = 0.05   # 整轮最大占 bankroll 比例


# ==================== Kelly基础 ====================

def kelly_fraction(prob: float, odds: float, fraction: float = 0.25,
                   max_stake: float = 0.10) -> float:
    """
    Kelly公式计算最优仓位。
    
    公式：f = (b*p - q) / b  （b=odds-1, q=1-p）
    负值截为0，上限max_stake。
    """
    if prob <= 0 or odds <= 1.0:
        return 0.0
    b = odds - 1.0
    q = 1.0 - prob
    f = (b * prob - q) / b
    f = max(0.0, f)
    return min(f * fraction, max_stake)


def scale_to_constraints(
    bet_df: pd.DataFrame,
    bankroll: float,
    max_bets: int = MAX_BETS,
    max_stake: float = MAX_STAKE,
    max_bankroll_frac: float = MAX_BANKROLL_FRAC,
) -> pd.DataFrame:
    """
    硬约束裁剪：
      1) 单张 ≤ max_stake
      2) 总额 ≤ min(bankroll*max_bankroll_frac, max_bets*max_stake)
    
    返回裁剪后的副本。
    """
    df = bet_df.copy()
    
    if 'bet_amount' not in df.columns:
        return df
    
    # 1. 单张上限
    df['bet_amount'] = df['bet_amount'].clip(upper=max_stake)
    
    # 2. 总额上限
    max_total = min(bankroll * max_bankroll_frac, max_bets * max_stake)
    total_now = df['bet_amount'].sum()
    if total_now > max_total:
        scale = max_total / total_now
        df['bet_amount'] = (df['bet_amount'] * scale).round(2)
    
    # 3. 再次确保单张上限
    df['bet_amount'] = df['bet_amount'].clip(upper=max_stake).round(2)
    
    return df


# ==================== 方案选择 ====================

def select_four_single(
    predictions: List[Dict],
    bankroll: float,
) -> pd.DataFrame:
    """
    方案：四单（4张单注）
    
    输入: predictions = [
        {
            'match_id': str,
            'direction': str ('让胜'/'让平'/'让负'),
            'model_prob': float,    # 模型概率
            'market_odds': float,   # 市场赔率
            'ev': float,            # expected value
        },
        ...
    ]
    
    返回: DataFrame（最多4行）
    """
    # 过滤正EV
    cand = [p for p in predictions if p.get('ev', 0) > 0]
    if not cand:
        return pd.DataFrame()
    
    # 按EV降序取前4
    cand.sort(key=lambda p: -p['ev'])
    top = cand[:4]
    
    rows = []
    for p in top:
        kelly = kelly_fraction(p['model_prob'], p['market_odds'])
        bet_amount = kelly * bankroll
        rows.append({
            'match_id': p['match_id'],
            'direction': p['direction'],
            'model_prob': p['model_prob'],
            'market_odds': p['market_odds'],
            'ev': p['ev'],
            'kelly_frac': kelly,
            'bet_amount': bet_amount,
            'bet_type': '单注',
        })
    
    df = pd.DataFrame(rows)
    return scale_to_constraints(df, bankroll)


def select_four_parlay(
    predictions: List[Dict],
    bankroll: float,
    n_choose: int = 4,
) -> pd.DataFrame:
    """
    方案：4串1（1张复式）
    
    从正EV场次中枚举组合，选期望乘子最高的4串1。
    """
    cand = [p for p in predictions if p.get('ev', 0) > 0]
    if len(cand) < n_choose:
        return pd.DataFrame()
    
    # 取top10枚举组合（10C4=210，足够快）
    top_n = sorted(cand, key=lambda p: -p['ev'])[:10]
    
    best_combo = None
    best_exp = -float('inf')
    
    for combo in itertools.combinations(top_n, n_choose):
        # 每场的期望乘子 = p * odds
        parlay_exp = prod(p['model_prob'] * p['market_odds'] for p in combo)
        if parlay_exp > best_exp:
            best_exp = parlay_exp
            best_combo = combo
    
    if best_combo is None:
        return pd.DataFrame()
    
    # 4串1的概率 = ∏ p_i，赔率 = ∏ odds_i
    parlay_prob = prod(p['model_prob'] for p in best_combo)
    parlay_odds = prod(p['market_odds'] for p in best_combo)
    parlay_ev = best_exp - 1.0
    
    kelly = kelly_fraction(parlay_prob, parlay_odds)
    bet_amount = kelly * bankroll
    
    rows = []
    for i, p in enumerate(best_combo):
        rows.append({
            'match_id': p['match_id'],
            'direction': p['direction'],
            'model_prob': p['model_prob'],
            'market_odds': p['market_odds'],
            'ev': p['ev'],
            'kelly_frac': kelly,
            'bet_amount': bet_amount if i == 0 else 0,
            'bet_type': '4串1',
            'parlay_prob': parlay_prob if i == 0 else 0,
            'parlay_odds': parlay_odds if i == 0 else 0,
            'parlay_ev': parlay_ev if i == 0 else 0,
        })
    
    df = pd.DataFrame(rows)
    return scale_to_constraints(df, bankroll)


def select_five_double(
    double_entries: List[Dict],
    bankroll: float,
) -> pd.DataFrame:
    """
    方案：五双选（5张双选单注）
    
    输入: double_entries = [
        {
            'match_id': str,
            'directions': [str, str],   # 两个方向
            'double_exp': float,        # p_a*odds_a + p_b*odds_b
            'double_prob': float,       # p_a + p_b
            'double_odds': float,       # double_exp / double_prob（等效赔率）
        },
        ...
    ]
    """
    cand = [d for d in double_entries if d.get('double_exp', 0) > 1.0]
    if not cand:
        return pd.DataFrame()
    
    cand.sort(key=lambda d: -d['double_exp'])
    top = cand[:5]
    
    rows = []
    for d in top:
        kelly = kelly_fraction(d['double_prob'], d['double_odds'])
        bet_amount = kelly * bankroll
        rows.append({
            'match_id': d['match_id'],
            'directions': d['directions'],
            'double_prob': d['double_prob'],
            'double_odds': d['double_odds'],
            'double_exp': d['double_exp'],
            'ev': d['double_exp'] - 1.0,
            'kelly_frac': kelly,
            'bet_amount': bet_amount,
            'bet_type': '双选',
        })
    
    df = pd.DataFrame(rows)
    return scale_to_constraints(df, bankroll)


def select_five_parlay_double(
    double_entries: List[Dict],
    bankroll: float,
) -> pd.DataFrame:
    """
    方案：5串1双选（1张复式）
    """
    cand = [d for d in double_entries if d.get('double_exp', 0) > 1.0]
    if len(cand) < 5:
        return pd.DataFrame()
    
    top_n = sorted(cand, key=lambda d: -d['double_exp'])[:10]
    
    best_combo = None
    best_exp = -float('inf')
    
    for combo in itertools.combinations(top_n, 5):
        parlay_exp = prod(d['double_exp'] for d in combo)
        if parlay_exp > best_exp:
            best_exp = parlay_exp
            best_combo = combo
    
    if best_combo is None:
        return pd.DataFrame()
    
    parlay_prob = prod(d['double_prob'] for d in best_combo)
    parlay_odds = prod(d['double_odds'] for d in best_combo)
    parlay_ev = best_exp - 1.0
    
    kelly = kelly_fraction(parlay_prob, parlay_odds)
    bet_amount = kelly * bankroll
    
    rows = []
    for i, d in enumerate(best_combo):
        rows.append({
            'match_id': d['match_id'],
            'directions': d['directions'],
            'double_prob': d['double_prob'],
            'double_odds': d['double_odds'],
            'double_exp': d['double_exp'],
            'ev': d['double_exp'] - 1.0,
            'kelly_frac': kelly,
            'bet_amount': bet_amount if i == 0 else 0,
            'bet_type': '5串1双选',
            'parlay_prob': parlay_prob if i == 0 else 0,
            'parlay_odds': parlay_odds if i == 0 else 0,
            'parlay_ev': parlay_ev if i == 0 else 0,
        })
    
    df = pd.DataFrame(rows)
    return scale_to_constraints(df, bankroll)


# ==================== 综合打包 ====================

def pack_into_five(
    single_df: pd.DataFrame,
    parlay_df: pd.DataFrame,
    double_df: pd.DataFrame,
    parlay_double_df: pd.DataFrame,
    bankroll: float,
) -> pd.DataFrame:
    """
    把四个方案合并，按EV排序选前5张。
    """
    frames = []
    
    for df, source in [
        (single_df, '四单'),
        (parlay_df, '4串1'),
        (double_df, '五双选'),
        (parlay_double_df, '5串1双选'),
    ]:
        if df.empty:
            continue
        df = df.copy()
        df['source'] = source
        frames.append(df)
    
    if not frames:
        return pd.DataFrame()
    
    all_bets = pd.concat(frames, ignore_index=True)
    
    # 只保留正EV且有投注额的
    if 'ev' in all_bets.columns:
        all_bets = all_bets[all_bets['ev'] > 0]
    if 'bet_amount' in all_bets.columns:
        all_bets = all_bets[all_bets['bet_amount'] > 0]
    
    if all_bets.empty:
        return pd.DataFrame()
    
    # 按EV排序取前5
    all_bets = all_bets.sort_values('ev', ascending=False).head(5).reset_index(drop=True)
    
    return scale_to_constraints(all_bets, bankroll)


# ==================== 演示 ====================

if __name__ == "__main__":
    np.random.seed(42)
    bankroll = 1000.0
    
    # 构造10场演示数据
    predictions = []
    for i in range(10):
        model_prob = np.random.uniform(0.3, 0.75)
        market_odds = np.random.uniform(1.5, 4.5)
        ev = model_prob * market_odds - 1
        predictions.append({
            'match_id': f'M{i+1:03d}',
            'direction': np.random.choice(['让胜', '让平', '让负']),
            'model_prob': model_prob,
            'market_odds': market_odds,
            'ev': ev,
        })
    
    # 双选数据
    double_entries = []
    for p in predictions:
        double_prob = min(p['model_prob'] + 0.2, 0.85)
        double_odds = p['market_odds'] * 0.85
        double_exp = double_prob * double_odds
        double_entries.append({
            'match_id': p['match_id'],
            'directions': [p['direction'], np.random.choice(['让胜', '让平', '让负'])],
            'double_prob': double_prob,
            'double_odds': double_odds,
            'double_exp': double_exp,
        })
    
    print("=" * 70)
    print("  资金管理模块 — 演示")
    print(f"  Bankroll: {bankroll:.0f}元")
    print("=" * 70)
    
    s1 = select_four_single(predictions, bankroll)
    s2 = select_four_parlay(predictions, bankroll)
    s3 = select_five_double(double_entries, bankroll)
    s4 = select_five_parlay_double(double_entries, bankroll)
    final = pack_into_five(s1, s2, s3, s4, bankroll)
    
    print(f"\n  四单: {len(s1)}张 {'(无可选)' if s1.empty else ''}")
    print(f"  4串1: {'1张' if not s2.empty else '0张（无可选）'}")
    print(f"  五双选: {len(s3)}张 {'(无可选)' if s3.empty else ''}")
    print(f"  5串1双选: {'1张' if not s4.empty else '0张（无可选）'}")
    
    if not final.empty:
        print(f"\n  最终{len(final)}张投注:")
        for _, row in final.iterrows():
            print(f"    {row['match_id']} {row.get('bet_type','')} ev={row.get('ev',0):+.2%} 金额={row['bet_amount']:.2f}元 来源={row.get('source','')}")
        print(f"  总投注: {final['bet_amount'].sum():.2f}元 (上限{min(bankroll*MAX_BANKROLL_FRAC, MAX_BETS*MAX_STAKE):.0f}元)")
    else:
        print("\n  无正EV投注")
