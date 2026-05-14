"""
V11 足球分析框架 — 六步信号驱动分析 + 三方案串关构建

独立运行：python scripts/v11_analyzer.py

改进 v2026-05-14:
  - Kelly 资金分配（动态计算）
  - 让球盘⇔百家平均换算交叉验证
  - 赛后复盘日志（jsonl）
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import json
import math
import os
from datetime import datetime, timezone, timedelta


# ==================== 常量 ====================

MIN_ODD = 1.50
MAX_ODD = 4.00
RANK_GAP_HIGH = 5

# 方案资金分配（硬编码兜底，Kelly覆盖时忽略）
FUND_ALLOCATION = {"A": 40, "B": 40, "C": 20}

# Kelly 参数
KELLY_FRACTION = 0.25        # 分数 Kelly，降低波动
KELLY_MAX_STAKE = 0.15       # 单注最大 15%
KELLY_MIN_EDGE = 0.05        # 最小正期望门槛

# 复盘日志路径
REVIEW_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review.log.jsonl")


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


# ==================== 辅助函数 ====================

def kelly_criterion(odds: float, prob: float, bankroll_pct: float = KELLY_FRACTION) -> float:
    """
    分数 Kelly 公式计算建议下注比例

    Args:
        odds: 十进制赔率
        prob: 获胜概率 (0-1)
        bankroll_pct: 分数 Kelly 系数，默认 0.25

    Returns:
        建议下注比例（占资金的百分比）
    """
    b = odds - 1.0
    q = 1.0 - prob
    edge = b * prob - q
    if edge <= KELLY_MIN_EDGE:
        return 0.0
    fraction = bankroll_pct * edge / b
    return min(max(fraction, 0.0), KELLY_MAX_STAKE)


def odds_to_prob(odds: float) -> float:
    """赔率倒推隐含概率（无反佣金修正）"""
    return 1.0 / odds


def handicap_convert(handicap: int, avg_home: float, avg_away: float, direction: str) -> bool:
    """
    让球盘方向 → 百家平均验证：让球方需要净胜 handicap+1 球

    示例：
        handicap=-1, 方向=让胜 → 需要净胜≥2球
        百家平均主胜赔率低 → 市场看好主队能赢 → 可能支持
    """
    if direction == Direction.WIN:
        # 让球胜：需要净胜 ≥ abs(handicap) + 1
        return avg_home < avg_away  # 百家看好主队
    elif direction == Direction.LOSS:
        return avg_away < avg_home  # 百家看好客队
    else:
        return True  # 让平无法用百家平均验证


class ReviewTracker:
    """赛后复盘日志追踪器"""

    def __init__(self, log_path: str = REVIEW_LOG):
        self.log_path = log_path

    def record(self, match_id: str, direction: str, label: str, min_odd: float,
               confidence: int, actual_result: Optional[str] = None):
        """记录一条预测"""
        entry = {
            "ts": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            "match_id": match_id,
            "direction": direction,
            "label": label,
            "min_odd": min_odd,
            "confidence": confidence,
            "actual": actual_result,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def update_result(self, match_id: str, actual_result: str):
        """赛后回填实际结果"""
        if not os.path.exists(self.log_path):
            return
        lines = []
        updated = False
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry["match_id"] == match_id and entry["actual"] is None:
                    entry["actual"] = actual_result
                    updated = True
                lines.append(json.dumps(entry, ensure_ascii=False))
        if updated:
            with open(self.log_path, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")

    def stats(self) -> dict:
        """统计各标签准确率"""
        if not os.path.exists(self.log_path):
            return {}
        records = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))

        completed = [r for r in records if r["actual"] is not None]
        stats = {"total": len(records), "pending": len(records) - len(completed)}
        # 按标签统计
        for label in set(r["label"] for r in completed):
            group = [r for r in completed if r["label"] == label]
            correct = sum(1 for r in group if r["direction"] == r["actual"])
            stats[label] = {
                "total": len(group),
                "correct": correct,
                "accuracy": round(correct / len(group), 3) if group else 0,
            }
        return stats


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
        market_favors_away = (direction == Direction.LOSS)

        # 主队优 → 市场方向也得是主队；客队优 → 市场方向也得是客队
        if fundamental_favors_home:
            return market_favors_home
        else:
            return market_favors_away

    # ── 第三步：百家平均交叉验证（含让球换算）────

    def _check_avg_alignment(self, m: Match, direction: str) -> Tuple[Optional[bool], float]:
        """
        百家平均是否与让球盘方向一致（含换算验证）

        Returns:
            (aligned: bool, convert_score: float)
            aligned: True=一致, False=打架, None=无数据
            convert_score: 0-1 换算匹配度（1=完全匹配）
        """
        if m.avg_odds is None:
            return None, 0.5

        # 基础方向一致检查
        avg_favors_home = (m.avg_odds.home < m.avg_odds.away)
        market_favors_home = (direction == Direction.WIN)
        aligned = (avg_favors_home == market_favors_home)

        # 让球换算检查
        if direction == Direction.WIN and m.handicap < 0:
            # 让-1要净胜2球：要求百家主胜明显低于客胜(≥20%差距)
            gap = m.avg_odds.away - m.avg_odds.home
            required = abs(m.handicap) + 0.5  # 让-1需要至少1.5球以上优势
            convert_score = min(gap / required, 1.0) if required > 0 else 0.5
        elif direction == Direction.LOSS and m.handicap > 0:
            # 受让方要直接赢：百家客胜明显低于主胜
            gap = m.avg_odds.home - m.avg_odds.away
            required = abs(m.handicap) + 0.5
            convert_score = min(gap / required, 1.0) if required > 0 else 0.5
        else:
            convert_score = 0.5  # 让平或其他情况无法量化换算

        return aligned, round(convert_score, 2)

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
        avg_convert_score: float,
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
        # 让球盘换算匹配度加权（最高+5）
        confidence += int(avg_convert_score * 10)
        if trend == "收紧":
            confidence += 10                   # 走势收紧 +10

        if confidence >= 80:
            return Label.GREEN, confidence
        else:
            return Label.YELLOW, confidence

    # ── 主入口 ─────────────────────────────────

    def analyze_match(self, m: Match, tracker: Optional[ReviewTracker] = None) -> Prediction:
        """分析单场比赛"""
        direction, min_odd = self._get_market_direction(m)
        spread = self._calc_spread(m)
        rank_gap = self._get_rank_gap(m)

        fundamental_agrees = self._check_fundamental_alignment(rank_gap, direction)
        avg_agrees, avg_convert_score = self._check_avg_alignment(m, direction)
        trend = self._check_trend(m)

        label, confidence = self._assign_label(
            m, direction, min_odd, spread,
            rank_gap, fundamental_agrees, avg_agrees, avg_convert_score, trend,
        )

        pred = Prediction(
            match_id=m.match_id,
            direction=direction,
            label=label,
            min_odd=min_odd,
            spread=spread,
            rank_gap=rank_gap,
            trend=trend,
            confidence=confidence,
        )

        if tracker:
            tracker.record(m.match_id, direction, label, min_odd, confidence)

        return pred

    def analyze_matches(self, matches: List[Match], tracker: Optional[ReviewTracker] = None) -> List[Prediction]:
        """批量分析"""
        return [self.analyze_match(m, tracker) for m in matches]

    # ── 方案构建（建串）────────────────────────

    def build_strategies(self, predictions: List[Prediction]) -> dict:
        """
        构建三个 4 串 1 方案

        要求：每个方案必须 4 场。若可选池不够，按优先级降级补位：
          优先: 🟢绿标 > 🔥高赔候选 > 🟡黄标
          禁止: ⚠️灰标 / 🚫不入
        """
        greens = sorted([p for p in predictions if p.is_green], key=lambda x: x.min_odd)
        yellows = sorted([p for p in predictions if p.is_yellow], key=lambda x: x.min_odd)
        hots = sorted([p for p in predictions if p.is_hot], key=lambda x: x.min_odd, reverse=True)

        # 所有可选池（按优先级排序）
        eligible = greens + hots + yellows

        def pick_strategy(name: str, rules: dict) -> list:
            """根据规则从 eligible 中选取 4 场"""
            pool = list(eligible)  # 拷贝
            selected = []

            # 规则指定的强制选场
            for rule_type, count in rules.get("force", {}).items():
                candidates = {
                    "green": list(greens),
                    "hot": list(hots),
                    "yellow": list(yellows),
                }.get(rule_type, [])
                # 差异化筛选
                if name == "A":
                    # A 要低赔：排掉高赔的
                    candidates = [p for p in candidates if p.min_odd < 2.00]
                elif name == "C":
                    # C 要高赔：优先高赔区间
                    candidates = sorted(candidates, key=lambda x: -x.min_odd)
                for p in candidates:
                    if len(selected) >= count:
                        break
                    if p not in selected and p in pool:
                        selected.append(p)

            # 补足到 4 场
            remaining = [p for p in pool if p not in selected]
            if name == "A":
                # A 补低赔
                remaining.sort(key=lambda x: x.min_odd)
            elif name == "C":
                # C 补高赔+合理赔率
                remaining.sort(key=lambda x: -x.min_odd)
            else:
                # B 均衡混合
                remaining.sort(key=lambda x: x.confidence, reverse=True)

            for p in remaining:
                if len(selected) >= 4:
                    break
                if name == "A" and p.min_odd > 2.50:
                    continue  # A 不超过 2.50
                if name == "C" and p.min_odd < 1.60:
                    continue  # C 不低于 1.60
                selected.append(p)

            return selected[:4]

        strategy_a = pick_strategy("A", {"force": {"green": 3}, "odd_range": [1.50, 2.00]})
        strategy_b = pick_strategy("B", {"force": {"green": 2, "yellow": 1}})
        strategy_c = pick_strategy("C", {"force": {"green": 2, "hot": 1}})

        # Kelly 资金建议
        kelly_a = self._kelly_weights(strategy_a)
        kelly_b = self._kelly_weights(strategy_b)
        kelly_c = self._kelly_weights(strategy_c)

        return {
            "strategy_a": strategy_a,
            "strategy_b": strategy_b,
            "strategy_c": strategy_c,
            "kelly_a": kelly_a,
            "kelly_b": kelly_b,
            "kelly_c": kelly_c,
            "recommended_fund": self._kelly_fund_allocation(predictions),
        }

    def _kelly_weights(self, picks: List[Prediction]) -> List[float]:
        """为每个选项计算 Kelly 建议比例"""
        return [
            round(kelly_criterion(p.min_odd, p.confidence / 100) * 100, 1)
            for p in picks
        ]

    def _kelly_fund_allocation(self, predictions: List[Prediction]) -> dict:
        """根据总预测质量动态分配三方案资金"""
        # 只考虑有入选资格的场次
        qualifiers = [p for p in predictions if p.label not in (Label.GRAY, Label.EXCLUDE)]
        if not qualifiers:
            return {"A": 40, "B": 40, "C": 20}
        avg_conf = sum(p.confidence for p in qualifiers) / len(qualifiers)
        # 置信度越高，A 方案占比越大
        a_ratio = min(0.5, 0.25 + (avg_conf - 50) / 200)
        c_ratio = max(0.1, 0.25 - (avg_conf - 50) / 200)
        b_ratio = 1.0 - a_ratio - c_ratio
        return {
            "A": round(a_ratio * 100),
            "B": round(b_ratio * 100),
            "C": round(c_ratio * 100),
        }


# ==================== 测试运行 ====================

if __name__ == "__main__":
    # 实战示例：2026-05-14/15 全部 10 场
    sample_matches = [
        # ── 周四场次 ──
        Match(
            match_id="周四001", league="西甲",
            home_team="巴伦西亚", away_team="巴列卡诺",
            home_rank=13, away_rank=10, handicap=-1,
            odds_win=4.95, odds_draw=3.85, odds_loss=1.50,
            avg_odds=AvgOdds(home=2.24, draw=3.08, away=3.50),
        ),
        Match(
            match_id="周四002", league="沙特联",
            home_team="达曼协定", away_team="吉达联合",
            home_rank=7, away_rank=6, handicap=1,
            odds_win=1.66, odds_draw=3.70, odds_loss=3.90,
            avg_odds=AvgOdds(home=3.21, draw=3.72, away=1.97),
        ),
        Match(
            match_id="周四003", league="沙特联",
            home_team="胡巴尔卡德西亚", away_team="拉斯决心",
            home_rank=4, away_rank=9, handicap=-2,
            odds_win=2.32, odds_draw=3.80, odds_loss=2.30,
            avg_odds=AvgOdds(home=1.20, draw=6.85, away=10.05),
        ),
        Match(
            match_id="周四004", league="西甲",
            home_team="赫罗纳", away_team="皇家社会",
            home_rank=19, away_rank=8, handicap=-1,
            odds_win=3.60, odds_draw=3.50, odds_loss=1.77,
            avg_odds=AvgOdds(home=1.90, draw=3.76, away=3.82),
        ),
        Match(
            match_id="周四005", league="西甲",
            home_team="皇马", away_team="奥维耶多",
            home_rank=2, away_rank=20, handicap=-2,
            odds_win=2.66, odds_draw=3.70, odds_loss=2.07,
            avg_odds=AvgOdds(home=1.24, draw=6.35, away=10.49),
        ),
        # ── 周五场次 ──
        Match(
            match_id="周五001", league="澳超",
            home_team="阿德莱德", away_team="奥克兰FC",
            home_rank=None, away_rank=None, handicap=-1,
            odds_win=4.50, odds_draw=3.95, odds_loss=1.53,
            avg_odds=AvgOdds(home=2.30, draw=3.50, away=2.80),
        ),
        Match(
            match_id="周五002", league="沙特联",
            home_team="达马克", away_team="迈季迈阿宽广",
            home_rank=15, away_rank=10, handicap=-1,
            odds_win=3.25, odds_draw=3.35, odds_loss=1.92,
            avg_odds=AvgOdds(home=1.78, draw=3.40, away=4.21),
        ),
        Match(
            match_id="周五003", league="沙特联",
            home_team="布赖代合作", away_team="利雅得",
            home_rank=5, away_rank=16, handicap=-1,
            odds_win=2.54, odds_draw=3.40, odds_loss=2.27,
            avg_odds=AvgOdds(home=1.69, draw=3.73, away=4.36),
        ),
        Match(
            match_id="周五004", league="法甲",
            home_team="圣埃蒂安", away_team="罗德兹",
            home_rank=None, away_rank=None, handicap=-1,
            odds_win=2.90, odds_draw=3.45, odds_loss=2.02,
            avg_odds=AvgOdds(home=1.69, draw=3.96, away=4.28),
        ),
        Match(
            match_id="周五005", league="英超",
            home_team="维拉", away_team="利物浦",
            home_rank=5, away_rank=4, handicap=1,
            odds_win=1.59, odds_draw=3.90, odds_loss=4.10,
            avg_odds=AvgOdds(home=2.92, draw=3.72, away=2.23),
        ),
    ]

    # 带复盘追踪的分析
    tracker = ReviewTracker()
    analyzer = V11Analyzer()
    results = analyzer.analyze_matches(sample_matches, tracker)

    print("=" * 60)
    print("  🍒 Cherry V11 — 单场分析结果")
    print("=" * 60)
    for p in results:
        print(f"\n  [{p.match_id}] {p.direction}")
        print(f"  └ 标签={p.label}  赔率={p.min_odd}  spread={p.spread}")
        print(f"      排名差={p.rank_gap}  走势={p.trend}  置信度={p.confidence}%")

        # 展示 Kelly 建议
        kelly_pct = kelly_criterion(p.min_odd, p.confidence / 100)
        if kelly_pct > 0:
            print(f"      Kelly建议={kelly_pct*100:.1f}%")

    print("\n" + "=" * 60)
    print("  串关方案 + Kelly 资金分配")
    print("=" * 60)
    strategies = analyzer.build_strategies(results)
    fund = strategies["recommended_fund"]

    for name, picks_key, fund_key, scheme_key in [
        ("A 稳健基石 🛡️", "strategy_a", "kelly_a", "A"),
        ("B 均衡回报 ⚖️", "strategy_b", "kelly_b", "B"),
        ("C 高赔冲刺 🚀", "strategy_c", "kelly_c", "C"),
    ]:
        picks = strategies[picks_key]
        kelly_pcts = strategies[fund_key]
        f = fund[scheme_key]
        if picks:
            combo_odd = 1.0
            for p in picks:
                combo_odd *= p.min_odd
            odds_list = " × ".join([f"{p.min_odd:.2f}" for p in picks])
            kelly_str = ", ".join([f"Kelly {k}%" for k in kelly_pcts])
            picks_detail = "\n".join([
                f"      {p.match_id}  {p.direction}  {p.label}  赔率{p.min_odd}  conf={p.confidence}%"
                for p in picks
            ])
            print(f"\n  [{name}]  资金={f}%  |  综合赔率 ≈ {combo_odd:.2f}x")
            print(f"  ── 4串1 ──")
            print(picks_detail)
            print(f"  ─────────")
            print(f"  Kelly: {kelly_str}")
        else:
            print(f"\n  [{name}] 资金={f}%")
            print(f"  └ (无合格 4 串 1)")

    # 复盘日志展示
    print(f"\n{'=' * 60}")
    print(f"  复盘日志")
    print(f"{'=' * 60}")
    for r in results:
        min_odd = r.min_odd
        kelly = kelly_criterion(min_odd, r.confidence / 100)
        print(f"  [{r.match_id}] {r.direction} | {r.label} | "
              f"赔率={min_odd} | 置信度={r.confidence}% | "
              f"Kelly={kelly*100:.1f}%")

    # 显示复盘追踪统计（读现有日志）
    print(f"\n  历史统计:")
    stats = tracker.stats()
    if stats:
        pending = stats.pop("pending", 0)
        total = stats.pop("total", 0)
        print(f"  总记录={total} 待回填={pending}")
        for label, s in sorted(stats.items()):
            print(f"  {label}: {s['correct']}/{s['total']} ({s['accuracy']*100:.0f}%)")
    else:
        print(f"  (首次运行，尚无历史数据)")
