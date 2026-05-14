"""
V11_Analysis(match) — 信号驱动的足球分析框架

六步信号采集与决策：
1. 市场信号 (赔率最低方向)
2. 基本面交叉验证 (排名差)
3. 百家平均交叉验证
4. 赔率走势监控 (收紧/放宽)
5. 标签生成 (绿标🟢/黄标🟡/灰标⚠️/高赔🔥/不入🚫)
6. 赔率门槛过滤

Build_Strategies(matches) — 三方案串关构建
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


class FundamentalsState(Enum):
    HOME_ADVANTAGE = "主队优势明显"
    AWAY_ADVANTAGE = "客队优势明显"
    BALANCED = "均势"


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
    handicap: float
    odds: dict  # {"win": float, "draw": float, "loss": float}
    home_rank: int
    away_rank: int
    avg_odds: Optional[dict] = None  # {"home": float, "away": float}
    previous: Optional[dict] = None  # {"min_odd": float}
    current: Optional[dict] = None   # {"min_odd": float}


@dataclass
class AnalysisResult:
    match_id: str
    direction: str
    label: str
    confidence: float
    key_risk: str
    odds: float


@dataclass
class StrategyConfig:
    name: str
    funds_ratio: float
    description: str


# ==================== 核心参数 ====================

MIN_ODD_THRESHOLD = 1.50  # 低于此不入选
MAX_ODD_THRESHOLD = 4.00  # 高于此不入选
RANK_GAP_HIGH = 5         # 排名差高于此视为"明显优势"

# 策略配置
STRATEGIES = {
    "A": StrategyConfig("稳健基石", 0.40, "最低赔率+最强信号的3-4场"),
    "B": StrategyConfig("均衡回报", 0.40, "绿标中赔混合1个黄标"),
    "C": StrategyConfig("高赔冲刺", 0.20, "绿标锚底+高赔候选+合理补位"),
}

TOTAL_UNITS = 100


# ==================== 第一步：信号采集 ====================

def _market_signal(odds: dict) -> tuple[Signal, float, float]:
    """从赔率中找到最低方向——市场的「首选方向」"""
    direction_map = {"win": Signal.WIN, "draw": Signal.DRAW, "loss": Signal.LOSS}
    min_key = min(direction_map, key=lambda k: odds[k])
    min_val = odds[min_key]
    max_val = max(odds.values())
    spread = round(max_val - min_val, 2)
    return direction_map[min_key], min_val, spread


def classify_signal_strength(spread: float) -> SignalStrength:
    if spread >= 1.0:
        return SignalStrength.STRONG
    elif spread >= 0.5:
        return SignalStrength.MEDIUM
    else:
        return SignalStrength.WEAK


# ==================== 第二步：基本面交叉验证 ====================

def evaluate_fundamentals(rank_gap: int) -> FundamentalsState:
    if rank_gap > RANK_GAP_HIGH:
        return FundamentalsState.HOME_ADVANTAGE
    elif rank_gap < -RANK_GAP_HIGH:
        return FundamentalsState.AWAY_ADVANTAGE
    else:
        return FundamentalsState.BALANCED


def _signal_to_expectation(signal: Signal) -> FundamentalsState:
    """让球盘信号对应的基本面期望方向"""
    mapping = {
        Signal.WIN: FundamentalsState.HOME_ADVANTAGE,
        Signal.LOSS: FundamentalsState.AWAY_ADVANTAGE,
    }
    return mapping.get(signal, FundamentalsState.BALANCED)


def fundamentals_agree(signal: Signal, fundamentals: FundamentalsState) -> bool:
    """基本面方向与市场信号是否一致"""
    expected = _signal_to_expectation(signal)
    # 市场信号若为平/均势，不视为矛盾
    if expected == FundamentalsState.BALANCED:
        return True
    return expected == fundamentals


# ==================== 第三步：百家平均交叉验证 ====================

def avg_odds_agree(avg_diff: float, signal: Signal) -> bool:
    """百家平均方向与让球盘方向一致？"""
    if avg_diff is None:
        return True  # 无数据时不惩罚
    # avg_home - avg_away > 0 → 百家认为主队劣势（赔率高=不被看好）
    if avg_diff < 0 and signal == Signal.WIN:
        return True
    if avg_diff > 0 and signal == Signal.LOSS:
        return True
    if signal == Signal.DRAW:
        return True
    return False


# ==================== 第四步：赔率走势监控 ====================

def get_trend(prev_min: float, curr_min: float) -> Trend:
    if curr_min < prev_min:
        return Trend.TIGHTENING
    return Trend.WIDENING


# ==================== 第五步：标签生成 ====================

def generate_label(
    strength: SignalStrength,
    fundamentals_state: FundamentalsState,
    fundamentals_agreed: bool,
    trend: Trend,
    rank_gap: int,
    odds_val: float,
) -> Label:
    # 赔率门槛
    if odds_val < MIN_ODD_THRESHOLD or odds_val > MAX_ODD_THRESHOLD:
        return Label.NO_ENTRY

    if strength == SignalStrength.STRONG and fundamentals_agreed and trend == Trend.TIGHTENING:
        return Label.GREEN

    if strength in (SignalStrength.STRONG, SignalStrength.MEDIUM) and fundamentals_agreed:
        return Label.YELLOW

    if strength == SignalStrength.WEAK:
        return Label.GRAY

    if not fundamentals_agreed:
        if abs(rank_gap) > RANK_GAP_HIGH * 2:
            return Label.HIGH_ODDS
        return Label.NO_ENTRY

    # 兜底
    return Label.NO_ENTRY


# ==================== 第六步：置信度计算 ====================

def calculate_confidence(
    strength: SignalStrength,
    fundamental_agrees: bool,
    avg_agrees: bool,
    trend: Trend,
) -> float:
    score = 0.0

    # 信号强度 (0-0.3)
    strength_scores = {
        SignalStrength.STRONG: 0.3,
        SignalStrength.MEDIUM: 0.2,
        SignalStrength.WEAK: 0.1,
    }
    score += strength_scores.get(strength, 0.1)

    # 基本面验证 (0-0.3)
    if fundamental_agrees:
        score += 0.3

    # 百家平均验证 (0-0.2)
    if avg_agrees:
        score += 0.2

    # 走势 (0-0.2)
    if trend == Trend.TIGHTENING:
        score += 0.2

    return round(min(score, 1.0), 2)


# ==================== 风险识别 ====================

def identify_risk(
    strength: SignalStrength,
    rank_gap: int,
    avg_diff: Optional[float],
) -> str:
    risks = []
    if strength == SignalStrength.WEAK:
        risks.append("信号弱，市场分歧小或数据不足")
    if abs(rank_gap) <= RANK_GAP_HIGH:
        risks.append("排名接近，基本面信号不足")
    if avg_diff is not None and abs(avg_diff) < 0.3:
        risks.append("百家赔率接近，无显著倾向")
    if abs(rank_gap) > RANK_GAP_HIGH * 2:
        risks.append("排名差极端，注意冷门风险")
    return "; ".join(risks) if risks else "无明显风险"


# ==================== 主入口：Analyze ====================

def V11_Analysis(match: Match) -> AnalysisResult:
    # 第一步：信号采集
    direction, min_odds, spread = _market_signal(match.odds)
    strength = classify_signal_strength(spread)

    # 第二步：基本面
    rank_gap = match.home_rank - match.away_rank
    fundamentals = evaluate_fundamentals(rank_gap)
    fund_agreed = fundamentals_agree(direction, fundamentals)

    # 第三步：百家平均
    if match.avg_odds:
        avg_diff = match.avg_odds.get("home", 0) - match.avg_odds.get("away", 0)
    else:
        avg_diff = None
    avg_agreed = avg_odds_agree(avg_diff, direction)

    # 第四步：走势
    if match.previous and match.current:
        trend = get_trend(match.previous["min_odd"], match.current["min_odd"])
    else:
        trend = Trend.TIGHTENING  # 无数据时默认乐观

    # 第五步：标签
    label = generate_label(strength, fundamentals, fund_agreed, trend, rank_gap, min_odds)

    # 第六步：置信度与风险
    confidence = calculate_confidence(strength, fund_agreed, avg_agreed, trend)
    risk = identify_risk(strength, rank_gap, avg_diff)

    return AnalysisResult(
        match_id=match.id,
        direction=direction.value,
        label=label.value,
        confidence=confidence,
        key_risk=risk,
        odds=min_odds,
    )


# ==================== Build_Strategies ====================

def Build_Strategies(results: list[AnalysisResult]) -> dict:
    # 过滤：只要🟢和🟡
    green = [r for r in results if r.label == Label.GREEN.value]
    yellow = [r for r in results if r.label == Label.YELLOW.value]
    high_odds = [r for r in results if r.label == Label.HIGH_ODDS.value]
    candidates = green + yellow

    # 默认全部分配
    allocation = {
        "A": 0,
        "B": 0,
        "C": 0,
    }

    # ||| 方案 A: 稳健基石 |||
    a_pool = [r for r in green if r.odds < 2.00]
    a_pool.sort(key=lambda r: r.odds)
    strategy_a = a_pool[:4]
    allocation["A"] = len(strategy_a)

    # ||| 方案 B: 均衡回报 |||
    b_low = [r for r in green if 1.50 <= r.odds <= 1.80]
    b_mid = [r for r in green if 1.80 <= r.odds <= 2.10]
    b_extra = [r for r in yellow if r.odds >= 2.00]

    strategy_b = []
    strategy_b.extend(b_low[:2])
    strategy_b.extend(b_mid[:1])
    if b_extra:
        strategy_b.append(b_extra[0])
    else:
        # 用黄标中赔补位
        b_fill = [r for r in yellow if r.odds < 2.00]
        if b_fill:
            strategy_b.append(b_fill[0])
    allocation["B"] = len(strategy_b)

    # ||| 方案 C: 高赔冲刺 |||
    c_base = [r for r in green if 1.50 <= r.odds <= 1.80]
    c_high = [r for r in high_odds if r.odds >= 2.50]
    c_fill = [r for r in candidates if 1.90 <= r.odds <= 2.10]

    strategy_c = []
    strategy_c.extend(c_base[:2])
    if c_high:
        strategy_c.append(c_high[0])
    else:
        # 改用黄标中赔作为红利
        c_alt = [r for r in yellow if r.odds >= 2.00]
        if c_alt:
            strategy_c.append(c_alt[0])
    if c_fill:
        strategy_c.append(c_fill[0])
    allocation["C"] = len(strategy_c)

    # 资金分配
    A_funds = round(STRATEGIES["A"].funds_ratio * TOTAL_UNITS) if len(strategy_c) >= 2 else 0
    B_funds = round(STRATEGIES["B"].funds_ratio * TOTAL_UNITS) if len(strategy_c) >= 2 else 0
    C_funds = TOTAL_UNITS - A_funds - B_funds

    return {
        "A": {
            "matches": [r.match_id for r in strategy_a],
            "funds": A_funds,
            "desc": STRATEGIES["A"].description,
        },
        "B": {
            "matches": [r.match_id for r in strategy_b],
            "funds": B_funds,
            "desc": STRATEGIES["B"].description,
        },
        "C": {
            "matches": [r.match_id for r in strategy_c],
            "funds": C_funds,
            "desc": STRATEGIES["C"].description,
        },
    }


# ==================== Run ====================

if __name__ == "__main__":
    # 示例：3场假数据跑通流程
    sample_matches = [
        Match(
            id="001",
            handicap=-1,
            odds={"win": 1.80, "draw": 3.50, "loss": 4.00},
            home_rank=3,
            away_rank=12,
            avg_odds={"home": 1.60, "away": 4.50},
            previous={"min_odd": 1.90},
            current={"min_odd": 1.80},
        ),
        Match(
            id="002",
            handicap=0,
            odds={"win": 2.20, "draw": 3.30, "loss": 2.80},
            home_rank=8,
            away_rank=6,
            avg_odds={"home": 2.10, "away": 3.10},
            previous={"min_odd": 2.30},
            current={"min_odd": 2.20},
        ),
        Match(
            id="003",
            handicap=-2,
            odds={"win": 2.50, "draw": 3.20, "loss": 2.40},
            home_rank=18,
            away_rank=2,
            avg_odds=None,
            previous=None,
            current=None,
        ),
    ]

    results = [V11_Analysis(m) for m in sample_matches]
    for r in results:
        print(f"[{r.match_id}] {r.direction} | {r.label} | 赔率={r.odds} | 置信度={r.confidence}")
        print(f"  风险: {r.key_risk}")

    print("\n策略方案:")
    strategies = Build_Strategies(results)
    for s_name, s_data in strategies.items():
        print(f"  [{s_name}] 场次={s_data['matches']} 资金={s_data['funds']}")
        print(f"     {s_data['desc']}")
