"""
V11 足球分析框架 — 六步信号驱动分析 + 三方案串关构建

独立运行：python scripts/v11_analyzer.py
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ==================== 常量 ====================

MIN_ODD = 1.50
MAX_ODD = 4.00
RANK_GAP_HIGH = 5

# 方案资金分配
FUND_ALLOCATION = {"A": 40, "B": 40, "C": 20}


# ==================== 类型定义 ====================

class Direction:
    WIN = "让胜"
    DRAW = "让平"
    LOSS = "让负"


class Label:
    GREEN = "🟢 绿标"
    YELLOW = "🟡 黄标"
    GRAY = "⚠️ 灰标"
    HOT = "🔥 高赔候选"
    EXCLUDE = "🚫 不入"


@dataclass
class AvgOdds:
    """百家平均赔率"""
    home: float
    draw: float
    away: float


@dataclass
class Match:
    """单场比赛完整数据"""
    match_id: str
    league: str
    home_team: str
    away_team: str
    home_rank: Optional[int]
    away_rank: Optional[int]
    handicap: int           # 让球数（-2, -1, +1...）

    # 让球盘赔率
    odds_win: float
    odds_draw: float
    odds_loss: float

    # 百家平均（可选）
    avg_odds: Optional[AvgOdds] = None

    # 前次赔率（可选，用于走势分析）
    prev_odds_win: Optional[float] = None
    prev_odds_draw: Optional[float] = None
    prev_odds_loss: Optional[float] = None


@dataclass
class Prediction:
    """单场分析结果"""
    match_id: str
    direction: str           # 让胜/让平/让负
    label: str               # 五级标签
    min_odd: float           # 最低赔率
    spread: float            # 赔率差
    rank_gap: Optional[int]  # 排名差（正值=主队优）
    trend: str               # 收紧/放宽/持平/N/A
    confidence: int          # 置信度 0-100

    @property
    def is_green(self) -> bool:
        return self.label == Label.GREEN

    @property
    def is_yellow(self) -> bool:
        return self.label == Label.YELLOW

    @property
    def is_hot(self) -> bool:
        return self.label == Label.HOT


# ==================== V11Analyzer ====================

class V11Analyzer:
    """Cherry V11 分析引擎"""

    def __init__(self, min_odd=MIN_ODD, max_odd=MAX_ODD):
        self.min_odd = min_odd
        self.max_odd = max_odd

    # ── 第一步：市场方向 ──────────────────────────

    def _get_market_direction(self, m: Match) -> Tuple[str, float]:
        """返回 (方向, 最低赔率)"""
        options = [
            (Direction.WIN, m.odds_win),
            (Direction.DRAW, m.odds_draw),
            (Direction.LOSS, m.odds_loss),
        ]
        return min(options, key=lambda x: x[1])

    def _calc_spread(self, m: Match) -> float:
        """赔率差 = max - min"""
        odds = [m.odds_win, m.odds_draw, m.odds_loss]
        return round(max(odds) - min(odds), 2)

    def _classify_strength(self, spread: float) -> str:
        """信号强度分级"""
        if spread >= 1.0:
            return "strong"
        elif spread >= 0.5:
            return "medium"
        return "weak"

    # ── 第二步：基本面交叉验证 ────────────────────

    def _get_rank_gap(self, m: Match) -> Optional[int]:
        """排名差（正值=主队排名更好）"""
        if m.home_rank is None or m.away_rank is None:
            return None
        return m.home_rank - m.away_rank

    def _check_fundamental_alignment(
        self, rank_gap: Optional[int], direction: str
    ) -> Optional[bool]:
        """基本面是否与市场方向一致"""
        if rank_gap is None:
            return None          # 缺排名数据
        if abs(rank_gap) <= RANK_GAP_HIGH:
            return None          # 均势，无法判断

        fundamental_favors_home = (rank_gap > 0)
        market_favors_home = (direction == Direction.WIN)

        return fundamental_favors_home == market_favors_home

    # ── 第三步：百家平均交叉验证 ────────────────

    def _check_avg_alignment(self, m: Match, direction: str) -> Optional[bool]:
        """百家平均是否与让球盘方向一致"""
        if m.avg_odds is None:
            return None

        avg_favors_home = (m.avg_odds.home < m.avg_odds.away)
        market_favors_home = (direction == Direction.WIN)

        return avg_favors_home == market_favors_home

    # ── 第四步：赔率走势监控 ────────────────────

    def _check_trend(self, m: Match) -> str:
        """赔率走势：收紧/放宽/持平/N/A"""
        if m.prev_odds_win is None:
            return "N/A"

        prev_min = min(m.prev_odds_win, m.prev_odds_draw, m.prev_odds_loss)
        curr_min = min(m.odds_win, m.odds_draw, m.odds_loss)
        delta = round(curr_min - prev_min, 2)

        if delta < -0.02:
            return "收紧"
        elif delta > 0.02:
            return "放宽"
        else:
            return "持平"

    # ── 第五步：标签判定 + 置信度 ──────────────

    def _assign_label(
        self,
        m: Match,
        direction: str,
        min_odd: float,
        spread: float,
        rank_gap: Optional[int],
        fundamental_agrees: Optional[bool],
        avg_agrees: Optional[bool],
        trend: str,
    ) -> Tuple[str, int]:
        """返回 (标签, 置信度 0-100)"""

        # 赔率门槛
        if min_odd < self.min_odd or min_odd > self.max_odd:
            return Label.EXCLUDE, 0

        # 信号强度
        strength = self._classify_strength(spread)

        # 弱信号 → 灰标
        if strength == "weak":
            return Label.GRAY, 20

        # ── 基本面与市场打架的分支 ──
        if fundamental_agrees is False:
            if rank_gap is not None and abs(rank_gap) >= 10:
                return Label.HOT, 40          # 大排名差 → 市场可能错了
            elif rank_gap is not None and abs(rank_gap) >= 5:
                confidence = 30
                if avg_agrees is True:
                    confidence += 10           # 百家站队 → 加分
                return Label.YELLOW, confidence
            else:
                return Label.EXCLUDE, 0       # 两个都不可靠

        # ── 基本面一致或无法判断 ──
        confidence = 60
        if fundamental_agrees is True:
            confidence += 20                   # 排名支持 +20
        if avg_agrees is True:
            confidence += 10                   # 百家支持 +10
        if trend == "收紧":
            confidence += 10                   # 走势收紧 +10

        if confidence >= 80:
            return Label.GREEN, confidence
        else:
            return Label.YELLOW, confidence

    # ── 主入口 ─────────────────────────────────

    def analyze_match(self, m: Match) -> Prediction:
        """分析单场比赛"""
        direction, min_odd = self._get_market_direction(m)
        spread = self._calc_spread(m)
        rank_gap = self._get_rank_gap(m)

        fundamental_agrees = self._check_fundamental_alignment(rank_gap, direction)
        avg_agrees = self._check_avg_alignment(m, direction)
        trend = self._check_trend(m)

        label, confidence = self._assign_label(
            m, direction, min_odd, spread,
            rank_gap, fundamental_agrees, avg_agrees, trend,
        )

        return Prediction(
            match_id=m.match_id,
            direction=direction,
            label=label,
            min_odd=min_odd,
            spread=spread,
            rank_gap=rank_gap,
            trend=trend,
            confidence=confidence,
        )

    def analyze_matches(self, matches: List[Match]) -> List[Prediction]:
        """批量分析"""
        return [self.analyze_match(m) for m in matches]

    # ── 方案构建（建串）────────────────────────

    def build_strategies(self, predictions: List[Prediction]) -> dict:
        """构建三个串关方案"""
        greens = [p for p in predictions if p.is_green]
        yellows = [p for p in predictions if p.is_yellow]
        hots = [p for p in predictions if p.is_hot]

        # 方案 A：稳健基石 🛡️
        # 3-4场绿标 + 赔率 < 2.00，赔率从低到高
        strategy_a = sorted(
            [p for p in greens if p.min_odd < 2.00],
            key=lambda x: x.min_odd,
        )[:4]

        # 方案 B：均衡回报 ⚖️
        # 2绿标低赔(1.50-1.80) + 1绿标中赔(1.80-2.10) + 1黄标调味(>=2.00)
        b_low = [p for p in greens if p.min_odd < 1.80][:2]
        b_mid = [p for p in greens if 1.80 <= p.min_odd < 2.10][:1]
        b_high = (yellows + hots)[:1]   # 黄标或高赔候选当调味
        strategy_b = b_low + b_mid + b_high

        # 方案 C：高赔冲刺 🚀
        # 2绿标锚底(1.50-1.80) + 1高赔候选(>=2.50) + 1合理补位(1.80-2.10)
        c_anchor = sorted(greens, key=lambda x: x.min_odd)[:2]
        c_hot = sorted(hots, key=lambda x: x.min_odd, reverse=True)[:1]
        c_fill = [
            p for p in greens
            if 1.80 <= p.min_odd < 2.10 and p not in c_anchor
        ][:1]
        strategy_c = c_anchor + c_hot + c_fill

        return {
            "strategy_a": strategy_a,
            "strategy_b": strategy_b,
            "strategy_c": strategy_c,
        }


# ==================== 测试运行 ====================

if __name__ == "__main__":
    # 实战示例：周四/周五场次
    sample_matches = [
        Match(
            match_id="周四001", league="西甲",
            home_team="巴伦西亚", away_team="巴列卡诺",
            home_rank=13, away_rank=10, handicap=-1,
            odds_win=4.95, odds_draw=3.85, odds_loss=1.50,
            avg_odds=AvgOdds(home=2.24, draw=3.08, away=3.50),
        ),
        Match(
            match_id="周五005", league="英超",
            home_team="维拉", away_team="利物浦",
            home_rank=5, away_rank=4, handicap=1,
            odds_win=1.59, odds_draw=3.90, odds_loss=4.80,
            avg_odds=AvgOdds(home=1.57, draw=4.20, away=5.50),
            prev_odds_win=1.62, prev_odds_draw=3.90, prev_odds_loss=4.70,
        ),
        Match(
            match_id="周五003", league="沙特联",
            home_team="布赖代合作", away_team="利雅得",
            home_rank=5, away_rank=16, handicap=-1,
            odds_win=2.54, odds_draw=3.30, odds_loss=2.46,
            avg_odds=AvgOdds(home=1.65, draw=3.80, away=4.75),
        ),
    ]

    analyzer = V11Analyzer()
    results = analyzer.analyze_matches(sample_matches)

    print("=" * 60)
    print("  🍒 Cherry V11 — 单场分析结果")
    print("=" * 60)
    for p in results:
        print(f"\n  [{p.match_id}] {p.direction}")
        print(f"  └ 标签={p.label}  赔率={p.min_odd}  spread={p.spread}")
        print(f"      排名差={p.rank_gap}  走势={p.trend}  置信度={p.confidence}%")

    print("\n" + "=" * 60)
    print("  串关方案")
    print("=" * 60)
    strategies = analyzer.build_strategies(results)
    for name, picks in strategies.items():
        label = {"strategy_a": "A 稳健基石 🛡️",
                 "strategy_b": "B 均衡回报 ⚖️",
                 "strategy_c": "C 高赔冲刺 🚀"}[name]
        fund = {"strategy_a": 40, "strategy_b": 40, "strategy_c": 20}[name]
        if picks:
            combo_odd = 1.0
            for p in picks:
                combo_odd *= p.min_odd
            odds_list = " × ".join([f"{p.min_odd:.2f}" for p in picks])
            print(f"\n  [{label}]  资金={fund}")
            print(f"  └ {', '.join([p.match_id for p in picks])}")
            print(f"    综合赔率 ≈ {combo_odd:.2f}x  ({odds_list})")
        else:
            print(f"\n  [{label}]  资金={fund}")
            print(f"  └ (无合格场次)")
