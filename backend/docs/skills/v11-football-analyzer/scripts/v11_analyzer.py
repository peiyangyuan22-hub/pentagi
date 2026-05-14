"""
V11 足球分析框架 — 六步信号驱动分析 + 三方案串关构建

独立运行：python scripts/v11_analyzer.py
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ==================== 类型定义 ====================

class Signal(Enum):
    WIN = "让胜"
    DRAW = "让平"
    LOSS = "让负"


class SignalStrength(Enum):
    STRONG = "强"    # spread >= 1.0
    MEDIUM = "中"    # 0.5 <= spread < 1.0
    WEAK = "弱"      # spread < 0.5


class Trend(Enum):
    TIGHTENING = "收紧"  # 赔率在降，市场在确认
    WIDENING = "放宽"    # 赔率在升，市场在动摇


class Label(Enum):
    GREEN = "🟢 绿标"
    YELLOW = "🟡 黄标"
    GRAY = "⚠️ 灰标"
    HIGH_ODDS = "🔥 高赔候选"
    NO_ENTRY = "🚫 不入"


@dataclass
class Match:
    id: str
    handicap: float          # 让球数 (-1, -2, +1...)
    odds: dict               # {"win": 让胜赔率, "draw": 让平赔率, "loss": 让负赔率}
    home_rank: int
    away_rank: int
    avg_odds: Optional[dict] = None   # {"home": 百家主胜, "away": 百家客胜}
    previous: Optional[dict] = None   # {"min_odd": 之前最低赔率}
    current: Optional[dict] = None    # {"min_odd": 当前最低赔率}


@dataclass
class Prediction:
    match_id: str
    direction: str   # 让胜/让平/让负
    label: str       # 🟢 绿标 / 🟡 黄标 / ⚠️ 灰标 / 🔥 高赔候选 / 🚫 不入
    odd: float       # 最低赔率


@dataclass
class StrategyOutput:
    a: list     # 稳健基石
    b: list     # 均衡回报
    c: list     # 高赔冲刺


# ==================== 核心参数 ====================

MIN_ODD = 1.50
MAX_ODD = 4.00
RANK_GAP_HIGH = 5
TOTAL_UNITS = 100


# ==================== V11Analyzer ====================

class V11Analyzer:
    def __init__(self):
        self.min_odd = MIN_ODD
        self.max_odd = MAX_ODD

    # ── 第一步：信号采集 ──

    def _get_market_signal(self, match: Match) -> Signal:
        """找最低赔率方向——市场的「首选方向」"""
        direction_map = {"win": Signal.WIN, "draw": Signal.DRAW, "loss": Signal.LOSS}
        min_key = min(direction_map, key=lambda k: match.odds[k])
        return direction_map[min_key]

    def _calc_spread(self, match: Match) -> float:
        """信号分裂程度 = max赔率 - min赔率"""
        return round(max(match.odds.values()) - min(match.odds.values()), 2)

    def _classify_strength(self, spread: float) -> SignalStrength:
        if spread >= 1.0:
            return SignalStrength.STRONG
        elif spread >= 0.5:
            return SignalStrength.MEDIUM
        return SignalStrength.WEAK

    # ── 第二步：基本面交叉验证 ──

    def _check_fundamental_alignment(self, rank_gap: int, direction: Signal) -> bool:
        """基本面方向与市场信号是否一致"""
        if abs(rank_gap) <= RANK_GAP_HIGH:
            return True  # 均势不视为矛盾
        if rank_gap > RANK_GAP_HIGH and direction == Signal.WIN:
            return True
        if rank_gap < -RANK_GAP_HIGH and direction == Signal.LOSS:
            return True
        return direction == Signal.DRAW

    # ── 第三步：百家平均交叉验证 ──

    def _check_avg_alignment(self, match: Match) -> bool:
        """百家平均方向与让球盘方向一致？"""
        if not match.avg_odds:
            return True  # 无数据时不惩罚
        direction = self._get_market_signal(match)
        avg_diff = match.avg_odds.get("home", 0) - match.avg_odds.get("away", 0)
        # avg_diff < 0 → 百家主胜赔率低 → 看好主队 → 与让胜方向一致
        if avg_diff < 0 and direction == Signal.WIN:
            return True
        if avg_diff > 0 and direction == Signal.LOSS:
            return True
        if direction == Signal.DRAW:
            return True
        return False

    # ── 第四步：赔率走势监控 ──

    def _check_trend(self, match: Match) -> Trend:
        """赔率是收紧还是放宽"""
        if not match.previous or not match.current:
            return Trend.TIGHTENING  # 无数据默认乐观
        if match.current["min_odd"] < match.previous["min_odd"]:
            return Trend.TIGHTENING  # 赔率降 → 收紧 → 市场认可
        return Trend.WIDENING         # 赔率升 → 放宽 → 市场动摇

    # ── 第五步：标签生成 ──

    def _assign_label(self, spread: float, fundamental_agrees: bool,
                      avg_agrees: bool, trend: Trend, match: Match) -> Label:
        min_odds_val = min(match.odds.values())
        rank_gap = match.home_rank - match.away_rank
        strength = self._classify_strength(spread)

        # 赔率门槛
        if min_odds_val < self.min_odd or min_odds_val > self.max_odd:
            return Label.NO_ENTRY

        # 🟢 绿标：强信号 + 基本面一致 + 走势收紧
        if strength == SignalStrength.STRONG and fundamental_agrees and trend == Trend.TIGHTENING:
            return Label.GREEN

        # 🟡 黄标：中/强信号 + 基本面一致
        if strength in (SignalStrength.STRONG, SignalStrength.MEDIUM) and fundamental_agrees:
            return Label.YELLOW

        # ⚠️ 灰标：信号弱
        if strength == SignalStrength.WEAK:
            return Label.GRAY

        # 🔥 高赔候选：基本面与市场打架 + 排名差极端
        if not fundamental_agrees:
            if abs(rank_gap) > RANK_GAP_HIGH * 2:
                return Label.HIGH_ODDS
            return Label.NO_ENTRY

        return Label.NO_ENTRY

    # ── 主入口 ──

    def analyze_match(self, match: Match) -> Prediction:
        spread = self._calc_spread(match)
        direction = self._get_market_signal(match)
        rank_gap = match.home_rank - match.away_rank

        fundamental_agrees = self._check_fundamental_alignment(rank_gap, direction)
        avg_agrees = self._check_avg_alignment(match)
        trend = self._check_trend(match)
        label = self._assign_label(spread, fundamental_agrees, avg_agrees, trend, match)

        return Prediction(
            match_id=match.id,
            direction=direction.value,
            label=label.value,
            odd=min(match.odds.values()),
        )

    # ── 策略构建 ──

    def build_strategies(self, predictions: list[Prediction]) -> StrategyOutput:
        greens = [p for p in predictions if p.label == "🟢 绿标"]
        yellows = [p for p in predictions if p.label == "🟡 黄标"]
        hots = [p for p in predictions if p.label == "🔥 高赔候选"]

        return StrategyOutput(
            a=self._build_a(greens),
            b=self._build_b(greens, yellows, hots),
            c=self._build_c(greens, hots),
        )

    def _build_a(self, greens: list[Prediction]) -> list:
        """方案 A: 稳健基石 — 最低赔率+最强信号的3-4场"""
        pool = [p for p in greens if p.odd < 2.00]
        pool.sort(key=lambda p: p.odd)
        return pool[:4]

    def _build_b(self, greens: list[Prediction], yellows: list[Prediction],
                 hots: list[Prediction]) -> list:
        """方案 B: 均衡回报 — 2绿标低赔 + 1绿标中赔 + 1黄标调味"""
        result = []
        b_low = [p for p in greens if 1.50 <= p.odd <= 1.80]
        b_mid = [p for p in greens if 1.80 <= p.odd <= 2.10]
        b_extra = [p for p in yellows + hots if p.odd >= 2.00]

        result.extend(b_low[:2])
        result.extend(b_mid[:1])
        if b_extra:
            result.append(b_extra[0])
        else:
            b_fill = [p for p in yellows if p.odd < 2.00]
            if b_fill:
                result.append(b_fill[0])
        return result

    def _build_c(self, greens: list[Prediction], hots: list[Prediction]) -> list:
        """方案 C: 高赔冲刺 — 2绿标锚底 + 1高赔候选 + 1合理补位"""
        result = []
        c_base = [p for p in greens if 1.50 <= p.odd <= 1.80]
        candidates = [p for p in (greens + hots) if 1.90 <= p.odd <= 2.10]
        c_high = [p for p in hots if p.odd >= 2.50]

        result.extend(c_base[:2])
        if c_high:
            result.append(c_high[0])
        else:
            c_alt = [p for p in candidates if p.odd >= 2.00]
            if c_alt:
                result.append(c_alt[0])
        if candidates:
            result.append(candidates[0])
        return result

    def fund_allocation(self) -> dict:
        return {"A": 40, "B": 40, "C": 20}


# ==================== 测试运行 ====================

if __name__ == "__main__":
    analyzer = V11Analyzer()

    test_matches = [
        Match(
            id="001", handicap=-1,
            odds={"win": 1.80, "draw": 3.50, "loss": 4.00},
            home_rank=3, away_rank=12,
            avg_odds={"home": 1.60, "away": 4.50},
            previous={"min_odd": 1.90}, current={"min_odd": 1.80},
        ),
        Match(
            id="002", handicap=0,
            odds={"win": 2.20, "draw": 3.30, "loss": 2.80},
            home_rank=8, away_rank=6,
            avg_odds={"home": 2.10, "away": 3.10},
            previous={"min_odd": 2.30}, current={"min_odd": 2.20},
        ),
        Match(
            id="003", handicap=-2,
            odds={"win": 2.50, "draw": 3.20, "loss": 2.40},
            home_rank=18, away_rank=2,
            avg_odds=None, previous=None, current=None,
        ),
    ]

    predictions = [analyzer.analyze_match(m) for m in test_matches]
    for p in predictions:
        print(f"[{p.match_id}] {p.direction} | {p.label} | 赔率={p.odd}")

    outputs = analyzer.build_strategies(predictions)
    funds = analyzer.fund_allocation()
    print(f"\n  方案 A [稳健基石]  {len(outputs.a)}场 资金={funds['A']}")
    print(f"  方案 B [均衡回报]  {len(outputs.b)}场 资金={funds['B']}")
    print(f"  方案 C [高赔冲刺]  {len(outputs.c)}场 资金={funds['C']}")
