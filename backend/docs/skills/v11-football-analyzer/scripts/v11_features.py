# -*- coding: utf-8 -*-
"""
V11.3 — 特征工程模块（FeatureFactory）
功能：
  1. 从原始数据生成30-50维特征
  2. 近N场滚动统计（λ攻防、形态、赛程）
  3. 交叉特征（攻防差值、乘积）
  4. 对缺失值进行贝叶斯平滑

参考自用户提供的"一站式足球预测-投注系统"文档
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
import math
import numpy as np
from collections import defaultdict


# ==================== 类型定义 ====================

@dataclass
class TeamProfile:
    """球队特征画像"""
    team_id: str
    league: str = ""
    
    # 进攻特征
    attack_lambda: float = 1.5        # Gamma后验进攻λ
    attack_raw_avg: float = 1.5       # 原始场均进球
    attack_samples: int = 0           # 样本数
    
    # 防守特征
    defense_lambda: float = 1.5       # Gamma后验防守λ
    defense_raw_avg: float = 1.5      # 原始场均失球
    defense_samples: int = 0
    
    # 近期形态
    points_last5: float = 0.0         # 近5场积分
    goal_diff_last5: float = 0.0      # 近5场净胜球
    form_code: str = "DDDDD"          # W/D/L 编码
    
    # 赛程
    days_since_last_match: int = 7
    consecutive_away: int = 0         # 连续客场场数
    
    # 伤停（0=无，1=有主力伤停，2=多名主力伤停）
    injury_impact: int = 0
    
    # xG（可选）
    xg_attack_lambda: Optional[float] = None
    xg_defense_lambda: Optional[float] = None


@dataclass
class MatchFeatures:
    """一场比赛的全部特征"""
    match_id: str
    league: str
    home_team: str
    away_team: str
    
    # === 攻防λ特征 ===
    lam_home_att: float = 1.5
    lam_home_def: float = 1.5
    lam_away_att: float = 1.5
    lam_away_def: float = 1.5
    
    # === Skellam输入 ===
    mu_home: float = 2.25
    mu_away: float = 2.25
    
    # === 近期形态 ===
    home_pts_last5: float = 0.0
    away_pts_last5: float = 0.0
    home_gd_last5: float = 0.0
    away_gd_last5: float = 0.0
    home_form: str = "DDDDD"
    away_form: str = "DDDDD"
    
    # === 主客场 ===
    home_adv_factor: float = 0.15
    
    # === 赛程 ===
    home_days_since: int = 7
    away_days_since: int = 7
    away_consecutive: int = 0
    
    # === 阵容 ===
    home_injury: int = 0
    away_injury: int = 0
    
    # === 排名 ===
    home_rank: Optional[int] = None
    away_rank: Optional[int] = None
    rank_gap: Optional[int] = None
    
    # === 交叉特征 ===
    att_power_ratio: float = 1.0       # home_att / away_att
    def_power_ratio: float = 1.0       # home_def / away_def
    total_strength: float = 4.5        # mu_home + mu_away
    att_balance: float = 0.0           # (lam_home_att - lam_away_att) / total
    
    # === 市场特征 ===
    home_odds: float = 0.0
    draw_odds: float = 0.0
    away_odds: float = 0.0
    handicap: int = 0
    implied_home_prob: float = 0.33
    implied_draw_prob: float = 0.33
    implied_away_prob: float = 0.33
    
    # === 天气（可选） ===
    temp_celsius: float = 20.0
    rain_prob: float = 0.0


# ==================== Gamma贝叶斯平滑 ====================

class GammaSmoother:
    """
    Gamma(α,β) 先验 → 后验更新。
    
    先验默认: α=2, β=2/2.5=0.8（联赛场均2.5球）
    """
    
    def __init__(self, alpha: float = 2.0, beta: float = 0.8):
        self.alpha = alpha
        self.beta = beta
    
    def posterior_lambda(self, values: List[float]) -> Tuple[float, int]:
        """从数值列表计算后验λ"""
        if not values:
            return self.alpha / self.beta, 0
        
        n = len(values)
        total = sum(values)
        post_lam = (self.alpha + total) / (self.beta + n)
        return round(post_lam, 4), n
    
    def posterior_from_stats(self, total: float, n: int) -> float:
        """从总量和样本数计算后验λ"""
        return (self.alpha + total) / (self.beta + n)


# ==================== 滚动统计计算器 ====================

class RollingStatsCalculator:
    """
    滚动统计计算器。
    计算球队最近N场的攻防λ、积分、净胜球等。
    """
    
    def __init__(self, n_games: int = 5, smoother: Optional[GammaSmoother] = None):
        self.n_games = n_games
        self.smoother = smoother or GammaSmoother()
        # 缓存: {team_id: TeamProfile}
        self._cache: Dict[str, TeamProfile] = {}
    
    def compute_profile(
        self,
        team_id: str,
        recent_goals_for: List[float],
        recent_goals_against: List[float],
        recent_results: List[str],        # ['W','D','L',...]
        days_since_match: int = 7,
        consecutive_away: int = 0,
        injury_impact: int = 0,
        league: str = "",
    ) -> TeamProfile:
        """计算球队特征画像"""
        
        # 攻防λ
        att_lam, att_n = self.smoother.posterior_lambda(recent_goals_for)
        def_lam, def_n = self.smoother.posterior_lambda(recent_goals_against)
        
        # 原始均值
        att_raw = sum(recent_goals_for) / max(len(recent_goals_for), 1)
        def_raw = sum(recent_goals_against) / max(len(recent_goals_against), 1)
        
        # 积分（3/1/0）
        pts = 0
        for r in recent_results[:self.n_games]:
            if r == 'W':
                pts += 3
            elif r == 'D':
                pts += 1
        pts_avg = pts / max(len(recent_results[:self.n_games]), 1)
        
        # 净胜球
        gd = sum(recent_goals_for[:self.n_games]) - sum(recent_goals_against[:self.n_games])
        
        # 形态编码
        form = ''.join(recent_results[:self.n_games]).ljust(self.n_games, 'D')[:self.n_games]
        
        profile = TeamProfile(
            team_id=team_id,
            league=league,
            attack_lambda=round(att_lam, 4),
            attack_raw_avg=round(att_raw, 4),
            attack_samples=att_n,
            defense_lambda=round(def_lam, 4),
            defense_raw_avg=round(def_raw, 4),
            defense_samples=def_n,
            points_last5=round(pts_avg, 4),
            goal_diff_last5=round(gd / max(len(recent_results[:self.n_games]), 1), 4),
            form_code=form,
            days_since_last_match=days_since_match,
            consecutive_away=consecutive_away,
            injury_impact=injury_impact,
        )
        
        self._cache[team_id] = profile
        return profile
    
    def get_cached(self, team_id: str) -> Optional[TeamProfile]:
        return self._cache.get(team_id)


# ==================== 特征构建器 ====================

class FeatureBuilder:
    """
    把两队特征整合成一场比赛的特征向量。
    """
    
    def __init__(self, home_adv: float = 0.15):
        self.home_adv = home_adv
    
    def build_features(
        self,
        match_id: str,
        league: str,
        home: TeamProfile,
        away: TeamProfile,
        handicap: int,
        home_odds: float = 0.0,
        draw_odds: float = 0.0,
        away_odds: float = 0.0,
        home_rank: Optional[int] = None,
        away_rank: Optional[int] = None,
    ) -> MatchFeatures:
        """构建一场比赛的全部特征"""
        
        # Skellam输入
        mu_home = home.attack_lambda * away.defense_lambda * (1.0 + self.home_adv)
        mu_away = away.attack_lambda * home.defense_lambda
        
        # 排名差距
        rank_gap = None
        if home_rank is not None and away_rank is not None:
            rank_gap = home_rank - away_rank
        
        # 交叉特征
        att_power = home.attack_lambda / max(away.attack_lambda, 0.01)
        def_power = home.defense_lambda / max(away.defense_lambda, 0.01)
        total_str = mu_home + mu_away
        att_bal = (home.attack_lambda - away.attack_lambda) / max(total_str, 0.01)
        
        # 市场隐含概率
        if home_odds > 0 and draw_odds > 0 and away_odds > 0:
            implied = np.array([1.0/home_odds, 1.0/draw_odds, 1.0/away_odds])
            total_imp = implied.sum()
            imp_home = implied[0] / total_imp if total_imp > 0 else 0.33
            imp_draw = implied[1] / total_imp if total_imp > 0 else 0.33
            imp_away = implied[2] / total_imp if total_imp > 0 else 0.34
        else:
            imp_home = imp_draw = imp_away = 0.33
        
        return MatchFeatures(
            match_id=match_id,
            league=league,
            home_team=home.team_id,
            away_team=away.team_id,
            lam_home_att=home.attack_lambda,
            lam_home_def=home.defense_lambda,
            lam_away_att=away.attack_lambda,
            lam_away_def=away.defense_lambda,
            mu_home=round(mu_home, 4),
            mu_away=round(mu_away, 4),
            home_pts_last5=home.points_last5,
            away_pts_last5=away.points_last5,
            home_gd_last5=home.goal_diff_last5,
            away_gd_last5=away.goal_diff_last5,
            home_form=home.form_code,
            away_form=away.form_code,
            home_adv_factor=self.home_adv,
            home_days_since=home.days_since_last_match,
            away_days_since=away.days_since_last_match,
            away_consecutive=away.consecutive_away,
            home_injury=home.injury_impact,
            away_injury=away.injury_impact,
            home_rank=home_rank,
            away_rank=away_rank,
            rank_gap=rank_gap,
            att_power_ratio=round(att_power, 4),
            def_power_ratio=round(def_power, 4),
            total_strength=round(total_str, 4),
            att_balance=round(att_bal, 4),
            home_odds=home_odds,
            draw_odds=draw_odds,
            away_odds=away_odds,
            handicap=handicap,
            implied_home_prob=round(imp_home, 4),
            implied_draw_prob=round(imp_draw, 4),
            implied_away_prob=round(imp_away, 4),
        )


# ==================== 特征工厂（统一入口） ====================

class FeatureFactory:
    """
    特征工厂 — 统一入口。
    从原始数据到MatchFeatures的一条龙。
    """
    
    def __init__(self, n_games: int = 5, home_adv: float = 0.15):
        self.roll_calc = RollingStatsCalculator(n_games=n_games)
        self.builder = FeatureBuilder(home_adv=home_adv)
    
    def get_feature_vector(self, features: MatchFeatures) -> List[float]:
        """把MatchFeatures转为数值向量（用于ML模型）"""
        vec = [
            features.lam_home_att, features.lam_home_def,
            features.lam_away_att, features.lam_away_def,
            features.mu_home, features.mu_away,
            features.home_pts_last5, features.away_pts_last5,
            features.home_gd_last5, features.away_gd_last5,
            features.home_days_since, features.away_days_since,
            features.away_consecutive,
            float(features.home_injury), float(features.away_injury),
            features.att_power_ratio, features.def_power_ratio,
            features.total_strength, features.att_balance,
            features.implied_home_prob, features.implied_draw_prob, features.implied_away_prob,
        ]
        # 处理None
        vec = [v if v is not None else 0.0 for v in vec]
        return vec
    
    def feature_names(self) -> List[str]:
        """特征名称列表（与get_feature_vector对应）"""
        return [
            'lam_home_att', 'lam_home_def', 'lam_away_att', 'lam_away_def',
            'mu_home', 'mu_away',
            'home_pts_last5', 'away_pts_last5',
            'home_gd_last5', 'away_gd_last5',
            'home_days_since', 'away_days_since',
            'away_consecutive',
            'home_injury', 'away_injury',
            'att_power_ratio', 'def_power_ratio',
            'total_strength', 'att_balance',
            'implied_home_prob', 'implied_draw_prob', 'implied_away_prob',
        ]


# ==================== 演示 ====================

if __name__ == "__main__":
    factory = FeatureFactory(n_games=5, home_adv=0.15)
    
    # 构造示例数据
    home_profile = factory.roll_calc.compute_profile(
        team_id="拜仁",
        recent_goals_for=[3, 2, 1, 4, 2],
        recent_goals_against=[0, 1, 0, 1, 1],
        recent_results=['W', 'W', 'D', 'W', 'W'],
        days_since_match=7,
    )
    
    away_profile = factory.roll_calc.compute_profile(
        team_id="科隆",
        recent_goals_for=[0, 1, 0, 2, 0],
        recent_goals_against=[3, 2, 4, 1, 2],
        recent_results=['L', 'D', 'L', 'W', 'L'],
        days_since_match=7,
        consecutive_away=1,
    )
    
    mf = factory.builder.build_features(
        match_id="周六012",
        league="德甲",
        home=home_profile,
        away=away_profile,
        handicap=-2,
        home_odds=1.17,
        draw_odds=8.61,
        away_odds=11.93,
        home_rank=1,
        away_rank=14,
    )
    
    vec = factory.get_feature_vector(mf)
    names = factory.feature_names()
    
    print("=" * 70)
    print("  特征工程模块 — 演示")
    print("=" * 70)
    print(f"\n  比赛: {mf.home_team} vs {mf.away_team} ({mf.league})")
    print(f"  μ_home={mf.mu_home:.2f} μ_away={mf.mu_away:.2f}")
    print(f"  排名差距: {mf.rank_gap:+d}")
    print(f"  攻防比: att_ratio={mf.att_power_ratio:.2f} def_ratio={mf.def_power_ratio:.2f}")
    print(f"\n  特征向量 ({len(vec)}维):")
    for n, v in zip(names, vec):
        print(f"    {n}: {v:.4f}")
