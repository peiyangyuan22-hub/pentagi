# -*- coding: utf-8 -*-
"""
V11.3 — Skellam统计模型层
xG → Poisson参数λ → Skellam让盘概率

核心逻辑：
  1. 从历史进球/xG数据计算球队攻防强度（Gamma贝叶斯平滑）
  2. Skellam分布计算让球盘概率 P(Δ>h), P(Δ=h), P(Δ<h)
  3. 输出公平赔率，供EV计算使用
"""

from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict
import math
import json
import os
from scipy.stats import skellam, poisson, nbinom


# ==================== 类型定义 ====================

@dataclass
class TeamStrength:
    """球队攻防强度"""
    attack_lambda: float    # 进攻λ（每场预期进球）
    defense_lambda: float   # 防守λ（每场预期失球）
    attack_samples: int     # 样本数
    defense_samples: int
    attack_raw_avg: float   # 原始场均进球
    defense_raw_avg: float  # 原始场均失球


@dataclass
class MatchStrengths:
    """一场比赛的双方强度"""
    home_attack_lambda: float
    home_defense_lambda: float
    away_attack_lambda: float
    away_defense_lambda: float
    home_adv_factor: float = 0.15  # 主场优势（默认+0.15球）


@dataclass
class SkellamResult:
    """Skellam模型输出"""
    mu_home: float              # 主队预期进球
    mu_away: float              # 客队预期进球
    home_win_prob: float        # P(Δ>0) 主胜
    draw_prob: float            # P(Δ=0) 平局
    away_win_prob: float        # P(Δ<0) 客胜
    
    # 让球盘概率
    handicap: int
    p_cover: float              # P(Δ > h) 让胜
    p_push: float               # P(Δ = h) 让平
    p_lose: float               # P(Δ < h) 让负
    
    # 公平赔率
    fair_odds_cover: float
    fair_odds_push: float
    fair_odds_lose: float
    
    # 模型诊断
    home_team: str = ""
    away_team: str = ""
    league: str = ""


# ==================== Gamma贝叶斯平滑 ====================

class GammaBayesianSmoother:
    """
    Gamma先验 → 后验更新（共轭）
    
    先验 Gamma(α, β):
      α = 2 (默认)
      β = 2 / league_avg_goals (league_avg ≈ 2.5)
    
    后验 Gamma(α + Σg, β + N):
      λ_post = (α + Σg) / (β + N)
    """
    
    def __init__(self, alpha: float = 2.0, beta: float = 0.8):
        """
        beta = 2/2.5 = 0.8 (联赛场均2.5球)
        """
        self.alpha = alpha
        self.beta = beta
    
    def update(self, sum_goals: float, n_matches: int) -> float:
        """贝叶斯后验λ"""
        return (self.alpha + sum_goals) / (self.beta + n_matches)
    
    def estimate_lambda(self, recent_goals: List[float]) -> float:
        """从进球列表估算λ"""
        if not recent_goals:
            return self.alpha / self.beta  # 先验均值
        return self.update(sum(recent_goals), len(recent_goals))


# ==================== 球队强度计算 ====================

class TeamStrengthCalculator:
    """
    计算球队攻防强度。
    
    需要外部提供 xG 数据（从v11_features或外部数据源来）。
    没有xG数据时，回退到用进球数估算。
    """
    
    def __init__(self, smoother: Optional[GammaBayesianSmoother] = None):
        self.smoother = smoother or GammaBayesianSmoother()
        # 缓存球队强度（避免重复计算）
        self._cache: Dict[str, TeamStrength] = {}
    
    def from_goals(
        self,
        team_id: str,
        recent_goals_for: List[float],    # 最近N场进球数
        recent_goals_against: List[float], # 最近N场失球数
    ) -> TeamStrength:
        """从实际进球数计算攻防强度"""
        attack_lambda = self.smoother.estimate_lambda(recent_goals_for)
        defense_lambda = self.smoother.estimate_lambda(recent_goals_against)
        
        raw_att_avg = sum(recent_goals_for) / max(len(recent_goals_for), 1)
        raw_def_avg = sum(recent_goals_against) / max(len(recent_goals_against), 1)
        
        ts = TeamStrength(
            attack_lambda=attack_lambda,
            defense_lambda=defense_lambda,
            attack_samples=len(recent_goals_for),
            defense_samples=len(recent_goals_against),
            attack_raw_avg=raw_att_avg,
            defense_raw_avg=raw_def_avg,
        )
        self._cache[team_id] = ts
        return ts
    
    def from_xg(
        self,
        team_id: str,
        recent_xg_for: List[float],      # 最近N场xG
        recent_xg_against: List[float],   # 最近N场xGA
    ) -> TeamStrength:
        """从xG数据计算攻防强度（优先使用，因为xG更稳定）"""
        return self.from_goals(team_id, recent_xg_for, recent_xg_against)
    
    def get_cached(self, team_id: str) -> Optional[TeamStrength]:
        return self._cache.get(team_id)


# ==================== Skellam 概率计算 ====================

class SkellamProbabilityEngine:
    """
    Skellam分布计算让盘概率。
    
    核心公式：
      μ_home = λ_home_attack × λ_away_defense × home_adv
      μ_away = λ_away_attack × λ_home_defense
      Δ = G_home - G_away ~ Skellam(μ_home, μ_away)
    
    P(让胜) = P(Δ > h)   (h为让球数，负=主让，正=客让)
    P(让平) = P(Δ = h)
    P(让负) = P(Δ < h)
    """
    
    def __init__(self, home_adv_factor: float = 0.15):
        self.home_adv_factor = home_adv_factor
    
    def compute_lambdas(
        self,
        home_att: float,    # 主队进攻λ
        home_def: float,    # 主队防守λ
        away_att: float,    # 客队进攻λ
        away_def: float,    # 客队防守λ
    ) -> Tuple[float, float]:
        """计算双方预期进球"""
        mu_home = home_att * away_def * (1.0 + self.home_adv_factor)
        mu_away = away_att * home_def
        return mu_home, mu_away
    
    def compute_1x2_probs(self, mu_home: float, mu_away: float) -> Tuple[float, float, float]:
        """
        计算全场胜平负概率（1X2）
        使用 Skellam 分布
        """
        # P(主胜) = P(Δ > 0) = 1 - CDF(0)
        # P(平)   = P(Δ = 0) = PDF(0)
        # P(客胜) = P(Δ < 0) = CDF(-1)
        
        home_win = 1.0 - skellam.cdf(0, mu_home, mu_away)
        draw = skellam.pmf(0, mu_home, mu_away)
        away_win = skellam.cdf(-1, mu_home, mu_away)
        
        # 归一化（确保和为1.0）
        total = home_win + draw + away_win
        if total > 0:
            home_win /= total
            draw /= total
            away_win /= total
        
        return home_win, draw, away_win
    
    def compute_handicap_probs(
        self, mu_home: float, mu_away: float, handicap: int
    ) -> Tuple[float, float, float]:
        """
        计算让球盘概率。
        
        handicap < 0: 主队让球（如-1表示主让1球）
        handicap > 0: 主队受让（如+1表示主受让1球）
        
        返回 (p_cover, p_push, p_lose)
          p_cover: 让球方赢盘
          p_push:  走水
          p_lose:  让球方输盘
        """
        if handicap < 0:  # 主队让球
            k = -handicap  # 如 -1 → k=1
            # 让胜: Δ > k（主队净胜>k球）
            p_cover = 1.0 - skellam.cdf(k, mu_home, mu_away)
            # 让平: Δ = k（主队净胜=k球）
            p_push = skellam.pmf(k, mu_home, mu_away)
            # 让负: Δ < k（主队净胜<k球）
            p_lose = skellam.cdf(k - 1, mu_home, mu_away)
        else:  # 客队让球 / 主队受让（handicap > 0）
            # 如 handicap=+1表示主受让1球 → 客让1球
            h = -handicap  # 转为客队视角让球数
            # 让负（客队赢盘）: Δ < h（主队净胜<客让球）
            p_lose = skellam.cdf(h - 1, mu_home, mu_away)
            # 让平: Δ = h
            p_push = skellam.pmf(h, mu_home, mu_away)
            # 让胜（主队赢盘）: Δ > h
            p_cover = 1.0 - skellam.cdf(h, mu_home, mu_away)
            # 注：这里p_cover=让胜（主队赢盘），p_lose=让负（客队赢盘）
        
        # 归一化
        total = p_cover + p_push + p_lose
        if total > 0:
            p_cover /= total
            p_push /= total
            p_lose /= total
        
        return p_cover, p_push, p_lose
    
    def compute_match_result(
        self,
        strengths: MatchStrengths,
        handicap: int,
        home_team: str = "",
        away_team: str = "",
        league: str = "",
    ) -> SkellamResult:
        """完整计算一场比赛的Skellam结果"""
        
        mu_home, mu_away = self.compute_lambdas(
            strengths.home_attack_lambda, strengths.home_defense_lambda,
            strengths.away_attack_lambda, strengths.away_defense_lambda,
        )
        
        home_win, draw, away_win = self.compute_1x2_probs(mu_home, mu_away)
        p_cover, p_push, p_lose = self.compute_handicap_probs(mu_home, mu_away, handicap)
        
        # 公平赔率（无佣金）
        fair_cover = 1.0 / max(p_cover, 0.001)
        fair_push = 1.0 / max(p_push, 0.001)
        fair_lose = 1.0 / max(p_lose, 0.001)
        
        return SkellamResult(
            mu_home=mu_home,
            mu_away=mu_away,
            home_win_prob=home_win,
            draw_prob=draw,
            away_win_prob=away_win,
            handicap=handicap,
            p_cover=p_cover,
            p_push=p_push,
            p_lose=p_lose,
            fair_odds_cover=fair_cover,
            fair_odds_push=fair_push,
            fair_odds_lose=fair_lose,
            home_team=home_team,
            away_team=away_team,
            league=league,
        )


# ==================== 测试/演示 ====================

if __name__ == "__main__":
    # 示例：给定两队强度，算让球盘
    engine = SkellamProbabilityEngine(home_adv_factor=0.15)
    
    strengths = MatchStrengths(
        home_attack_lambda=2.1,    # 强队主场攻击λ
        home_defense_lambda=0.9,
        away_attack_lambda=1.1,    # 弱队客场攻击λ
        away_defense_lambda=1.5,
    )
    
    print("=" * 60)
    print("  Skellam 让盘概率引擎 — 演示")
    print("=" * 60)
    print(f"  主队: λ攻={strengths.home_attack_lambda:.2f} λ防={strengths.home_defense_lambda:.2f}")
    print(f"  客队: λ攻={strengths.away_attack_lambda:.2f} λ防={strengths.away_defense_lambda:.2f}")
    
    for h in [-2, -1, 0, 1, 2]:
        result = engine.compute_match_result(strengths, h)
        print(f"\n  让球 {h:+d}:")
        print(f"    μ_home={result.mu_home:.2f} μ_away={result.mu_away:.2f}")
        print(f"    1X2: 主={result.home_win_prob:.1%} 平={result.draw_prob:.1%} 客={result.away_win_prob:.1%}")
        label_cover = "让胜" if h < 0 else "让胜"
        label_push = "让平"
        label_lose = "让负" if h < 0 else "让负"
        print(f"    {h:+d}盘: {label_cover}={result.p_cover:.1%} {label_push}={result.p_push:.1%} {label_lose}={result.p_lose:.1%}")
    
    print()
    print("  EV计算示例（与市场赔率对比）:")
    print("  market_odds_cover=2.10 公平赔率=2.00 → EV=+5% → 正EV ✅")
