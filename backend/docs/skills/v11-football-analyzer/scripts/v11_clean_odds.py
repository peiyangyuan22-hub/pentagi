# -*- coding: utf-8 -*-
"""
V11.3 — 赔率清洗模块
功能：
  1. clean_odds(): 去除博彩公司佣金（vig），得到真实概率和公平赔率
  2. 支持1X2、让球盘、大小球等多种赔率格式
  3. 计算单场和双选的期望乘子（p·odds）

参考自用户提供的"一站式足球预测-投注系统"文档
"""

import pandas as pd
import numpy as np
from typing import List, Tuple, Optional, Dict


def clean_odds_1x2(home_odds: float, draw_odds: float, away_odds: float) -> Dict[str, float]:
    """
    去除1X2赔率的佣金（vig），返回真实概率和公平赔率。
    
    公式：
      implied_p = 1/odds
      vig = sum(implied_p) - 1
      true_p = implied_p / (1+vig)
      fair_odds = 1/true_p
    
    返回:
      {
        'prob_home': float, 'prob_draw': float, 'prob_away': float,
        'fair_home': float, 'fair_draw': float, 'fair_away': float,
        'vig': float
      }
    """
    implied = np.array([1.0/home_odds, 1.0/draw_odds, 1.0/away_odds])
    vig = implied.sum() - 1.0
    true_p = implied / (1.0 + vig)
    fair = 1.0 / true_p
    
    return {
        'prob_home': round(true_p[0], 6),
        'prob_draw': round(true_p[1], 6),
        'prob_away': round(true_p[2], 6),
        'fair_home': round(fair[0], 4),
        'fair_draw': round(fair[1], 4),
        'fair_away': round(fair[2], 4),
        'vig': round(vig, 4),
    }


def clean_odds_handicap(win_odds: float, draw_odds: float, lose_odds: float) -> Dict[str, float]:
    """
    去除让球盘赔率的佣金（vig），结构同1X2。
    
    返回:
      {
        'prob_win': float, 'prob_push': float, 'prob_lose': float,
        'fair_win': float, 'fair_push': float, 'fair_lose': float,
        'vig': float
      }
    """
    implied = np.array([1.0/win_odds, 1.0/draw_odds, 1.0/lose_odds])
    vig = implied.sum() - 1.0
    true_p = implied / (1.0 + vig)
    fair = 1.0 / true_p
    
    return {
        'prob_win': round(true_p[0], 6),
        'prob_push': round(true_p[1], 6),
        'prob_lose': round(true_p[2], 6),
        'fair_win': round(fair[0], 4),
        'fair_push': round(fair[1], 4),
        'fair_lose': round(fair[2], 4),
        'vig': round(vig, 4),
    }


def compute_single_exp(prob: float, fair_odds: float) -> float:
    """
    计算单选的期望乘子。
    exp = p * odds
    正EV条件: exp > 1.0
    """
    return prob * fair_odds


def compute_double_exp(prob_a: float, odds_a: float, prob_b: float, odds_b: float) -> float:
    """
    计算双选的期望乘子（两种结果互斥，期望可加）。
    exp = p_a * odds_a + p_b * odds_b
    """
    return prob_a * odds_a + prob_b * odds_b


def compute_parlay_exp(expecteds: List[float]) -> float:
    """
    计算串关的期望乘子（各场独立假设）。
    parlay_exp = ∏ exp_i
    正EV条件: parlay_exp > 1.0
    """
    result = 1.0
    for e in expecteds:
        result *= e
    return result


def compute_kelly_edge(fair_prob: float, market_odds: float) -> float:
    """
    计算Kelly Edge（直接比较模型概率与市场隐含概率）。
    edge = fair_prob * market_odds - 1
    """
    return fair_prob * market_odds - 1.0


def kelly_fraction(prob: float, odds: float, fraction: float = 0.25,
                   max_stake: float = 0.1) -> float:
    """
    Kelly公式计算最优仓位。
    
    参数:
      prob: 模型概率（0~1）
      odds: 市场赔率（≥1）
      fraction: Kelly分数（0.25 = 保守，0.5 = 激进）
      max_stake: 最大仓位上限
    
    返回:
      仓位比例（0~max_stake）
    """
    b = odds - 1.0
    f = (b * prob - (1.0 - prob)) / b
    f = max(0.0, f)  # 负值截为0（不下注）
    return min(f * fraction, max_stake)


def vig_from_odds(odds: List[float]) -> float:
    """计算赔率列表的佣金率"""
    implied = sum(1.0 / o for o in odds)
    return implied - 1.0


# ==================== 演示 ====================

if __name__ == "__main__":
    # 示例1: 1X2去vig
    print("=" * 60)
    print("  赔率清洗模块 — 演示")
    print("=" * 60)
    
    odds_1x2 = (2.50, 3.40, 2.80)
    result = clean_odds_1x2(*odds_1x2)
    print(f"\n  1X2赔率: {odds_1x2[0]:.2f}/{odds_1x2[1]:.2f}/{odds_1x2[2]:.2f}")
    print(f"  Vig: {result['vig']:.2%}")
    print(f"  真实概率: {result['prob_home']:.1%}/{result['prob_draw']:.1%}/{result['prob_away']:.1%}")
    print(f"  公平赔率: {result['fair_home']:.2f}/{result['fair_draw']:.2f}/{result['fair_away']:.2f}")
    
    # 示例2: 让球盘去vig
    odds_hcp = (1.80, 3.60, 4.20)
    result = clean_odds_handicap(*odds_hcp)
    print(f"\n  让球盘赔率: {odds_hcp[0]:.2f}/{odds_hcp[1]:.2f}/{odds_hcp[2]:.2f}")
    print(f"  Vig: {result['vig']:.2%}")
    print(f"  真实概率: {result['prob_win']:.1%}/{result['prob_push']:.1%}/{result['prob_lose']:.1%}")
    
    # 示例3: Kelly计算
    prob, odds = 0.55, 2.10
    kelly = kelly_fraction(prob, odds)
    edge = compute_kelly_edge(prob, odds)
    print(f"\n  概率={prob:.0%} 赔率={odds:.2f}")
    print(f"  Kelly Edge: {edge:+.2%}")
    print(f"  Kelly仓位: {kelly:.2%}")
