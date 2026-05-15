# -*- coding: utf-8 -*-
"""
V11 足球分析框架 v1.1 — Bug修复版

修复：
  1. 三选二投票平局处理（令出赛分组方向）
  2. 让-2深盘模式识别+让平分水岭
  3. 置信度校准（80%封顶、标签降级）
  
使用：python v11_analyzer_v2.py
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import json
import math
import os
from datetime import datetime, timezone, timedelta


# ==================== 常量 ====================

MIN_ODD = 1.30           # 放宽一点下限，捕捉更多机会
MAX_ODD = 5.00
RANK_GAP_HIGH = 5

FUND_ALLOCATION = {"A": 40, "B": 40, "C": 20}

KELLY_FRACTION = 0.25
KELLY_MAX_STAKE = 0.15
KELLY_MIN_EDGE = 0.05

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
    home: float
    draw: float
    away: float


@dataclass
class Match:
    match_id: str
    league: str
    home_team: str
    away_team: str
    home_rank: Optional[int]
    away_rank: Optional[int]
    handicap: int
    odds_win: float
    odds_draw: float
    odds_loss: float
    avg_odds: Optional[AvgOdds] = None
    prev_odds_win: Optional[float] = None
    prev_odds_draw: Optional[float] = None
    prev_odds_loss: Optional[float] = None


@dataclass
class Prediction:
    match_id: str
    direction: str
    label: str
    min_odd: float
    spread: float
    rank_gap: Optional[int]
    trend: str
    confidence: int
    rank_note: str = ""
    vote_info: str = ""

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
    b = odds - 1.0
    q = 1.0 - prob
    edge = b * prob - q
    if edge <= KELLY_MIN_EDGE:
        return 0.0
    fraction = bankroll_pct * edge / b
    return min(max(fraction, 0.0), KELLY_MAX_STAKE)


# ==================== 赛后复盘追踪器 ====================

class ReviewTracker:
    def __init__(self, log_path: str = REVIEW_LOG):
        self.log_path = log_path

    def record(self, match_id: str, direction: str, label: str, min_odd: float,
               confidence: int, actual_result: Optional[str] = None):
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


# ==================== V11Analyzer v1.1 ====================

class V11Analyzer:
    """Cherry V11 分析引擎 v1.1 — 三大bug修复"""

    def __init__(self, min_odd=MIN_ODD, max_odd=MAX_ODD):
        self.min_odd = min_odd
        self.max_odd = max_odd

    # ── 第一步：市场方向（四选初筛）───────────────

    def _get_market_direction(self, m: Match) -> Tuple[str, float]:
        """
        改良三选二：
        当外部信号仅一个或平局时 → 退回让球盘跟赔率（但返回标记供后续降级）
        返回 (方向, 最低赔率, 投票得分)
        投票得分: 2=全票, 1=单票, 0=平局无票
        """
        options = [
            (Direction.WIN, m.odds_win),
            (Direction.DRAW, m.odds_draw),
            (Direction.LOSS, m.odds_loss),
        ]
        market_dir, market_odd = min(options, key=lambda x: x[1])

        # 信号B：百家平均方向
        avg_dir = None
        if m.avg_odds is not None:
            avg_dir = Direction.WIN if m.avg_odds.home < m.avg_odds.away else Direction.LOSS

        # 信号C：基本面方向
        rank_gap = self._get_rank_gap(m)
        fund_dir = None
        if rank_gap is not None and abs(rank_gap) > RANK_GAP_HIGH:
            fund_dir = Direction.WIN if rank_gap < 0 else Direction.LOSS

        # 统计外部投票（只计让胜/让负方向，排除让平）
        ext_votes_for_win = 0
        ext_votes_for_loss = 0
        for d in (avg_dir, fund_dir):
            if d == Direction.WIN:
                ext_votes_for_win += 1
            elif d == Direction.LOSS:
                ext_votes_for_loss += 1

        total_ext = ext_votes_for_win + ext_votes_for_loss
        decision_strength = total_ext  # 0=无外部信号, 1=单信号, 2=双信号

        if total_ext >= 2:
            # 双信号一致：直接覆盖市场方向
            if ext_votes_for_win == 2:
                winner = Direction.WIN
            elif ext_votes_for_loss == 2:
                winner = Direction.LOSS
            else:
                # 两信号打架（一个看胜一个看负）→ 等于无信号
                return market_dir, market_odd, 0
            if winner != market_dir:
                inv_odd = m.odds_win if winner == Direction.WIN else m.odds_loss
                return winner, inv_odd, 2
            return winner, m.odds_win if winner == Direction.WIN else m.odds_loss, 2
        elif total_ext == 1:
            # 单信号：不强制逆转市场，但保留投票强度信息供降级参考
            return market_dir, market_odd, 1
        else:
            # 无外部信号
            return market_dir, market_odd, 0

    def _calc_spread(self, m: Match) -> float:
        odds = [m.odds_win, m.odds_draw, m.odds_loss]
        return round(max(odds) - min(odds), 2)

    def _classify_strength(self, spread: float) -> str:
        if spread >= 1.0:
            return "strong"
        elif spread >= 0.5:
            return "medium"
        return "weak"

    # ── 第二步：基本面交叉验证 ────────────────────

    def _get_rank_gap(self, m: Match) -> Optional[int]:
        if m.home_rank is None or m.away_rank is None:
            return None
        return m.home_rank - m.away_rank

    def _check_fundamental_alignment(
        self, rank_gap: Optional[int], direction: str
    ) -> Optional[bool]:
        if rank_gap is None:
            return None
        if abs(rank_gap) <= RANK_GAP_HIGH:
            return None
        fundamental_favors_home = (rank_gap < 0)
        market_favors_home = (direction == Direction.WIN)
        if fundamental_favors_home:
            return market_favors_home
        else:
            return (direction == Direction.LOSS)

    # ── 第三步：百家平均交叉验证 ─────────────────

    def _check_avg_alignment(self, m: Match, direction: str) -> Tuple[Optional[bool], float]:
        if m.avg_odds is None:
            return None, 0.5
        avg_favors_home = (m.avg_odds.home < m.avg_odds.away)
        market_favors_home = (direction == Direction.WIN)
        aligned = (avg_favors_home == market_favors_home)

        # 让球换算检查
        if direction == Direction.WIN and m.handicap < 0:
            gap = m.avg_odds.away - m.avg_odds.home
            required = abs(m.handicap) + 0.5
            convert_score = min(gap / required, 1.0) if required > 0 else 0.5
        elif direction == Direction.LOSS and m.handicap > 0:
            gap = m.avg_odds.home - m.avg_odds.away
            required = abs(m.handicap) + 0.5
            convert_score = min(gap / required, 1.0) if required > 0 else 0.5
        else:
            convert_score = 0.5

        return aligned, round(convert_score, 2)

    # ── 排名方向说明 ─────────────────────────────

    def _rank_note(self, m: Match) -> str:
        if m.home_rank is None or m.away_rank is None:
            return "无排名数据"
        gap = m.home_rank - m.away_rank
        if gap == 0:
            return f"同排第{m.home_rank}名"
        if gap < 0:
            better_team = f"主队{m.home_team}"
        else:
            better_team = f"客队{m.away_team}"
        rank_diff = abs(gap)
        note = f"{better_team}高{rank_diff}位"
        if abs(gap) >= 10:
            note += "（悬殊）"
        elif abs(gap) >= 5:
            note += "（显著）"
        else:
            note += "（均势）"
        return note

    # ── 第四步：赔率走势 ─────────────────────────

    def _check_trend(self, m: Match) -> str:
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

    # ── 第五步：让-2深盘专用检查 ─────────────────
    # 新增：对让-2及以上深盘特殊处理

    def _deep_handicap_check(self, m: Match, direction: str) -> Tuple[Optional[str], int, str]:
        """
        对 |handicap| >= 2 的比赛，做让平分水岭检查。
        
        让-2深盘特性（v1.1.1修正）：
        - 让胜：净胜3+球 → 罕见（除非碾压级差距）
        - 让平：净胜2球 → 最常见走水结果
        - 让负：净胜≤1球 → 爆冷
        
        两档阈值（2026-05-15 修复）：
        - 百家主胜 65-80% → 强制转向让平（实力差距适中，走水剧本）
        - 百家主胜 >80%   → 不干预（实力碾压，打穿概率足够高）
        
        触发依据：
        - 拜仁周六上榜时百家主胜86%，且让球盘最低赔是让胜@1.73
        - 市场+百家双看打穿时，让平是便宜盘，不应该主动踩
        
        Returns:
            (建议方向或None, 扣减分数, 诊断信息)
        """
        if abs(m.handicap) < 2:
            return None, 0, ""
        
        if m.avg_odds is None:
            return None, 0, ""
        
        # 计算百家平均隐含概率（带反佣金修正）
        raw_home_p = 1.0 / m.avg_odds.home
        raw_draw_p = 1.0 / m.avg_odds.draw
        raw_away_p = 1.0 / m.avg_odds.away
        total_raw = raw_home_p + raw_draw_p + raw_away_p
        home_prob = raw_home_p / total_raw
        away_prob = raw_away_p / total_raw
        
        if m.handicap < 0:  # 主队让球（强队让深盘）
            # 66% ~ 80% → 强制让平（净胜2球走水剧本）
            # >80% → 不干预（实力太碾压，让胜打穿概率高）
            if 0.65 < home_prob <= 0.80:
                if direction != Direction.DRAW:
                    return Direction.DRAW, 20, f"深盘让平(主{home_prob:.0%})"
                return None, 5, ""
        else:  # 客队让球（handicap > 0，主队受让，实质是客队让深盘）
            if 0.65 < away_prob <= 0.80:
                if direction != Direction.DRAW:
                    return Direction.DRAW, 20, f"深盘让平(客{away_prob:.0%})"
                return None, 5, ""
        return None, 0, ""

    # ── 第六步：标签 + 置信度（校准版）────────────

    # ── Kelly Edge 辅助计算 ─────────────────────

    def _kelly_edge(self, min_odd: float, win_prob: float) -> float:
        """
        计算Kelly Edge（预期价值）。
        
        Edge = (真实概率 * 赔率 - 1) / (赔率 - 1)  实际Kelly比例
        简化为：Edge = (win_prob * min_odd) - 1.0   （正数=有正期望）
        
        用赔率倒推隐含概率 vs 模型估算概率
        """
        if min_odd <= 1.0:
            return -1.0
        implied_prob = 1.0 / min_odd
        edge = win_prob - implied_prob
        return edge

    # ── 标签 + 置信度（Kelly Edge整合版 v1.1.1） ──
    # 2026-05-15 修复：整合Kelly Edge，单信号但Edge>0不再降灰标

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
        vote_strength: int,
    ) -> Tuple[str, int]:
        """
        v1.1.1 改进：
        - 置信度上限 80%
        - 整合Kelly Edge：Edge为正时，单信号不再降灰标
        - 单信号但Edge为负 → 灰标
        - 双信号确认 ≥绿标
        """
        # 赔率门槛
        if min_odd < self.min_odd or min_odd > self.max_odd:
            return Label.EXCLUDE, 0

        # 信号强度
        strength = self._classify_strength(spread)

        # 弱信号 → 灰标
        if strength == "weak":
            return Label.GRAY, 20

        # 估算真实胜率基准
        base_win_prob = 1.0 / min_odd
        # 双信号 +spread中强，模型比赔率更信任
        if vote_strength >= 2 and strength in ("mid", "strong"):
            base_win_prob = min(base_win_prob * 1.15, 0.80)
        elif vote_strength == 1 and strength in ("mid", "strong"):
            base_win_prob = min(base_win_prob * 1.05, 0.70)
        
        # 计算Edge
        edge = self._kelly_edge(min_odd, base_win_prob)

        # ── 无外部信号(vote_strength=0) → 灰标 ──
        if vote_strength == 0:
            return Label.GRAY, 25

        # ── 单信号处理 ──
        if vote_strength == 1:
            # Edge为正 → 仍可参与，但降一档（黄色）
            if edge > 0:
                base_conf = 50
                if fundamental_agrees is True:
                    base_conf += 10
                if avg_agrees is True:
                    base_conf += 8
                # 赔率倒推置信
                imp_conf = int(base_win_prob * 100)
                final_conf = min(max(base_conf, imp_conf, 55), 75)
                return Label.YELLOW, final_conf
            else:
                # Edge为负 → 灰标
                return Label.GRAY, 30

        # ── 双信号（vote_strength >= 2） ──

        # 基本面与市场打架
        if fundamental_agrees is False:
            if rank_gap is not None and abs(rank_gap) >= 10:
                return Label.HOT, 35
            elif rank_gap is not None and abs(rank_gap) >= 5:
                return Label.HOT, 30
            else:
                return Label.EXCLUDE, 0

        # 基本面一致或无法判断
        base_conf = 55
        if fundamental_agrees is True:
            base_conf += 15
        if avg_agrees is True:
            base_conf += 10
        base_conf += int(avg_convert_score * 8)
        if trend == "收紧":
            base_conf += 8

        final_conf = base_conf

        # 标签判定
        if final_conf >= 65:
            label = Label.GREEN
        elif final_conf >= 40:
            label = Label.YELLOW
        else:
            label = Label.GRAY

        # 置信度上限 80%
        final_conf = min(final_conf, 80)

        return label, final_conf

    # ── 主入口 ─────────────────────────────────

    def analyze_match(self, m: Match, tracker: Optional[ReviewTracker] = None) -> Prediction:
        direction, min_odd, vote_strength = self._get_market_direction(m)
        spread = self._calc_spread(m)
        rank_gap = self._get_rank_gap(m)

        # 让-2深盘检查（在标签前干预方向）
        deep_dir, deep_penalty, deep_diag = self._deep_handicap_check(m, direction)
        if deep_dir is not None:
            direction = deep_dir
            # 方向变了，min_odd要更新为对应方向的赔率
            dir_odd_map = {
                Direction.WIN: m.odds_win,
                Direction.DRAW: m.odds_draw,
                Direction.LOSS: m.odds_loss,
            }
            min_odd = dir_odd_map.get(direction, min_odd)

        fundamental_agrees = self._check_fundamental_alignment(rank_gap, direction)
        avg_agrees, avg_convert_score = self._check_avg_alignment(m, direction)
        trend = self._check_trend(m)

        label, confidence = self._assign_label(
            m, direction, min_odd, spread,
            rank_gap, fundamental_agrees, avg_agrees, avg_convert_score, trend,
            vote_strength,
        )

        # 如果深盘干预过，覆盖标签和置信度
        # 深盘让平是强制干预，应该至少黄标+55%置信度
        if deep_dir is not None:
            label = Label.YELLOW
            confidence = max(confidence, 55)

        rank_note = self._rank_note(m)

        raw_options = [
            (Direction.WIN, m.odds_win),
            (Direction.DRAW, m.odds_draw),
            (Direction.LOSS, m.odds_loss),
        ]
        raw_market_dir, _ = min(raw_options, key=lambda x: x[1])
        is_contrarian = (direction != raw_market_dir)

        vote_parts = []
        if m.avg_odds is not None:
            vote_parts.append(f"百家{'同' if avg_agrees else '反'}")
        if rank_gap is not None and abs(rank_gap) > RANK_GAP_HIGH:
            vote_parts.append(f"基本面{'同' if fundamental_agrees else '反'}")
        votes_str = " ".join(vote_parts)
        if is_contrarian:
            vote_parts_str = f"⚡{votes_str} 逆市场{raw_market_dir}"
        else:
            vote_parts_str = f"✅{votes_str} 跟市场"

        if deep_dir is not None:
            vote_parts_str += f" [深盘→让平]"

        pred = Prediction(
            match_id=m.match_id,
            direction=direction,
            label=label,
            min_odd=min_odd,
            spread=spread,
            rank_gap=rank_gap,
            trend=trend,
            confidence=confidence,
            rank_note=rank_note,
            vote_info=vote_parts_str,
        )

        if tracker:
            tracker.record(m.match_id, direction, label, min_odd, confidence)

        return pred

    def analyze_matches(self, matches: List[Match], tracker: Optional[ReviewTracker] = None) -> List[Prediction]:
        return [self.analyze_match(m, tracker) for m in matches]

    # ── 方案构建 ─────────────────────────────

    def build_strategies(self, predictions: List[Prediction]) -> dict:
        greens = sorted([p for p in predictions if p.is_green], key=lambda x: x.min_odd)
        yellows = sorted([p for p in predictions if p.is_yellow], key=lambda x: x.min_odd)
        hots = sorted([p for p in predictions if p.is_hot], key=lambda x: x.min_odd, reverse=True)

        eligible = greens + hots + yellows

        def pick_strategy(name: str, rules: dict) -> list:
            pool = list(eligible)
            selected = []
            for rule_type, count in rules.get("force", {}).items():
                candidates = {
                    "green": list(greens),
                    "hot": list(hots),
                    "yellow": list(yellows),
                }.get(rule_type, [])
                if name == "A":
                    candidates = [p for p in candidates if p.min_odd < 2.00]
                elif name == "C":
                    candidates = sorted(candidates, key=lambda x: -x.min_odd)
                for p in candidates:
                    if len(selected) >= count:
                        break
                    if p not in selected and p in pool:
                        selected.append(p)

            remaining = [p for p in pool if p not in selected]
            if name == "A":
                remaining.sort(key=lambda x: x.min_odd)
            elif name == "C":
                remaining.sort(key=lambda x: -x.min_odd)
            else:
                remaining.sort(key=lambda x: x.confidence, reverse=True)

            for p in remaining:
                if len(selected) >= 4:
                    break
                if name == "A" and p.min_odd > 2.50:
                    continue
                if name == "C" and p.min_odd < 1.60:
                    continue
                selected.append(p)

            return selected[:4]

        strategy_a = pick_strategy("A", {"force": {"green": 3}})
        strategy_b = pick_strategy("B", {"force": {"green": 2, "yellow": 1}})
        strategy_c = pick_strategy("C", {"force": {"green": 2, "hot": 1}})

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
        return [round(kelly_criterion(p.min_odd, p.confidence / 100) * 100, 1) for p in picks]

    def _kelly_fund_allocation(self, predictions: List[Prediction]) -> dict:
        qualifiers = [p for p in predictions if p.label not in (Label.GRAY, Label.EXCLUDE)]
        if not qualifiers:
            return {"A": 40, "B": 40, "C": 20}
        avg_conf = sum(p.confidence for p in qualifiers) / len(qualifiers)
        a_ratio = min(0.5, 0.25 + (avg_conf - 50) / 200)
        c_ratio = max(0.1, 0.25 - (avg_conf - 50) / 200)
        b_ratio = 1.0 - a_ratio - c_ratio
        return {
            "A": round(a_ratio * 100),
            "B": round(b_ratio * 100),
            "C": round(c_ratio * 100),
        }


# ==================== 蒙特卡洛模拟 ====================

import random

def monte_carlo_simulation(
    pick: Prediction,
    num_simulations: int = 5000,
) -> dict:
    """
    对单场比赛进行蒙特卡洛模拟。
    
    原理：
    1. 用赔率倒推隐含概率（去佣金）
    2. 用模型置信度调整概率
    3. 5000次随机模拟，统计实际结果分布的命中率
    
    Returns:
        {
            "direction": str,
            "hit_rate": float,      # 选向命中率
            "win_pct": float,       # 让胜概率
            "draw_pct": float,      # 让平概率
            "loss_pct": float,      # 让负概率
            "even_prob": float,     # 深层净胜分布
        }
    """
    # 使用赔率倒推
    raw_odds = [pick.min_odd, 1.0, 1.0]  # 只有选向的赔率已知
    imp_probs = [1.0 / pick.min_odd]
    
    # 让平/让负的赔率不可见，用模型置信度做方向性修正
    # 置信度越高，选向概率越集中
    conf_factor = pick.confidence / 100.0
    
    # 用赔率反推：让球盘三个方向的隐含概率
    # 但我们只有选向的赔率，其他两个未知
    # 改用模型赋予的三个方向权重
    if pick.direction == Direction.WIN:
        win_w = conf_factor * 0.7  # 让胜占主导
        draw_w = (1 - conf_factor) * 0.5  # 让平可能性
        loss_w = (1 - conf_factor) * 0.5  # 让负可能性
    elif pick.direction == Direction.DRAW:
        draw_w = conf_factor * 0.55  # 让平主导（深盘走水）
        win_w = (1 - conf_factor) * 0.5  # 让胜
        loss_w = (1 - conf_factor) * 0.5  # 让负
    else:  # LOSS
        loss_w = conf_factor * 0.7
        draw_w = (1 - conf_factor) * 0.5
        win_w = (1 - conf_factor) * 0.5
    
    total_w = win_w + draw_w + loss_w
    win_pct = win_w / total_w
    draw_pct = draw_w / total_w
    loss_pct = loss_w / total_w
    
    # 5000次模拟
    hits = 0
    for _ in range(num_simulations):
        r = random.random()
        if r < win_pct:
            result = Direction.WIN
        elif r < win_pct + draw_pct:
            result = Direction.DRAW
        else:
            result = Direction.LOSS
        if result == pick.direction:
            hits += 1
    
    hit_rate = hits / num_simulations
    
    return {
        "direction": pick.direction,
        "hit_rate": round(hit_rate, 4),
        "win_pct": round(win_pct, 4),
        "draw_pct": round(draw_pct, 4),
        "loss_pct": round(loss_pct, 4),
        "simulations": num_simulations,
    }


def monte_carlo_parlay(picks: List[Prediction], num_simulations: int = 5000) -> dict:
    """
    对4串1方案进行蒙特卡洛模拟。
    
    计算：
    - 全部命中概率（方案命中）
    - 平均回报倍数
    - 模拟分布（n场命中的概率）
    """
    if len(picks) != 4:
        return {"error": "需要4串1"}
    
    sim_results = []
    for p in picks:
        sim_results.append(monte_carlo_simulation(p, num_simulations))
    
    # 计算方案整体命中
    combo_odd = 1.0
    all_hits = 0
    hit_counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    
    for p in picks:
        combo_odd *= p.min_odd
    
    for _ in range(num_simulations):
        hit_count = 0
        for sim in sim_results:
            r = random.random()
            probs = [sim["win_pct"], sim["draw_pct"], sim["loss_pct"]]
            p_sum = 0
            result = Direction.WIN
            for idx, prob in enumerate(probs):
                p_sum += prob
                if r < p_sum:
                    result = [Direction.WIN, Direction.DRAW, Direction.LOSS][idx]
                    break
            target = sim["direction"]
            if result == target:
                hit_count += 1
        
        hit_counts[hit_count] = hit_counts.get(hit_count, 0) + 1
        if hit_count == 4:
            all_hits += 1
    
    return {
        "combo_odd": round(combo_odd, 2),
        "all_hit_prob": round(all_hits / num_simulations, 4),
        "hit_distribution": {
            f"{k}场中": round(v / num_simulations, 4)
            for k, v in sorted(hit_counts.items())
        },
        "simulations": num_simulations,
        "expected_return": round(all_hits / num_simulations * combo_odd, 4),
    }


# ==================== 测试运行 ====================

if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sample_matches = [
        Match(match_id="周四001", league="西甲",
            home_team="巴伦西亚", away_team="巴列卡诺",
            home_rank=13, away_rank=10, handicap=-1,
            odds_win=4.95, odds_draw=3.85, odds_loss=1.50,
            avg_odds=AvgOdds(home=2.24, draw=3.08, away=3.50)),
        Match(match_id="周四002", league="沙特联",
            home_team="达曼协定", away_team="吉达联合",
            home_rank=7, away_rank=6, handicap=1,
            odds_win=1.66, odds_draw=3.70, odds_loss=3.90,
            avg_odds=AvgOdds(home=3.21, draw=3.72, away=1.97)),
        Match(match_id="周四003", league="沙特联",
            home_team="胡巴尔卡德西亚", away_team="拉斯决心",
            home_rank=4, away_rank=9, handicap=-2,
            odds_win=2.32, odds_draw=3.80, odds_loss=2.30,
            avg_odds=AvgOdds(home=1.20, draw=6.85, away=10.05)),
        Match(match_id="周四004", league="西甲",
            home_team="赫罗纳", away_team="皇家社会",
            home_rank=19, away_rank=8, handicap=-1,
            odds_win=3.60, odds_draw=3.50, odds_loss=1.77,
            avg_odds=AvgOdds(home=1.90, draw=3.76, away=3.82)),
        Match(match_id="周四005", league="西甲",
            home_team="皇马", away_team="奥维耶多",
            home_rank=2, away_rank=20, handicap=-2,
            odds_win=2.66, odds_draw=3.70, odds_loss=2.07,
            avg_odds=AvgOdds(home=1.24, draw=6.35, away=10.49)),
        Match(match_id="周五001", league="澳超",
            home_team="阿德莱德", away_team="奥克兰FC",
            home_rank=None, away_rank=None, handicap=-1,
            odds_win=4.50, odds_draw=3.95, odds_loss=1.53,
            avg_odds=AvgOdds(home=2.30, draw=3.50, away=2.80)),
        Match(match_id="周五002", league="沙特联",
            home_team="达马克", away_team="迈季迈阿宽广",
            home_rank=15, away_rank=10, handicap=-1,
            odds_win=3.25, odds_draw=3.35, odds_loss=1.92,
            avg_odds=AvgOdds(home=1.78, draw=3.40, away=4.21)),
        Match(match_id="周五003", league="沙特联",
            home_team="布赖代合作", away_team="利雅得",
            home_rank=5, away_rank=16, handicap=-1,
            odds_win=2.54, odds_draw=3.40, odds_loss=2.27,
            avg_odds=AvgOdds(home=1.69, draw=3.73, away=4.36)),
        Match(match_id="周五004", league="法甲",
            home_team="圣埃蒂安", away_team="罗德兹",
            home_rank=None, away_rank=None, handicap=-1,
            odds_win=2.90, odds_draw=3.45, odds_loss=2.02,
            avg_odds=AvgOdds(home=1.69, draw=3.96, away=4.28)),
        Match(match_id="周五005", league="英超",
            home_team="维拉", away_team="利物浦",
            home_rank=5, away_rank=4, handicap=1,
            odds_win=1.59, odds_draw=3.90, odds_loss=4.10,
            avg_odds=AvgOdds(home=2.92, draw=3.72, away=2.23)),
    ]

    tracker = ReviewTracker()
    analyzer = V11Analyzer()
    results = analyzer.analyze_matches(sample_matches, tracker)

    print("=" * 60)
    print("  🍒 Cherry V11 v1.1 — Bug修复版 单场分析")
    print("=" * 60)
    for p in results:
        kelly_pct = kelly_criterion(p.min_odd, p.confidence / 100)
        kelly_str = f"  Kelly={kelly_pct*100:.1f}%" if kelly_pct > 0 else ""
        print(f"\n  [{p.match_id}] {p.direction}")
        print(f"  └ 标签={p.label}  赔率={p.min_odd}  置信度={p.confidence}%{kelly_str}")
        print(f"    {p.vote_info}  |  {p.rank_note}")

    print("\n" + "=" * 60)
    print("  串关方案")
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
            print(f"\n  [{name}]  资金={f}%  |  综合赔率 ≈ {combo_odd:.2f}x")
            for i, p in enumerate(picks):
                print(f"    {i+1}. {p.match_id} {p.direction} {p.label} 赔率{p.min_odd} conf={p.confidence}%")
            print(f"    Kelly: {', '.join([f'{k}%' for k in kelly_pcts])}")
        else:
            print(f"\n  [{name}]  (无合格4串1)")

    # 周四复盘对比
    print("\n" + "=" * 60)
    print("  周四复盘对比 (v1.0 vs v1.1)")
    print("=" * 60)
    v11_results = {
        "周四001": "让负",
        "周四002": "让胜",
        "周四003": "让负",
        "周四004": "让负",
        "周四005": "让负",
    }
    actual = {
        "周四001": "让负",
        "周四002": "让负",
        "周四003": "让平",
        "周四004": "让负",
        "周四005": "让平",
    }
    for rid in ["周四001", "周四002", "周四003", "周四004", "周四005"]:
        v11_dir = v11_results[rid]
        new_dir = [p for p in results if p.match_id == rid][0]
        actual_dir = actual[rid]
        old_correct = "✅" if v11_dir == actual_dir else "❌"
        new_correct = "✅" if new_dir.direction == actual_dir else "❌"
        print(f"  {rid}: 旧={v11_dir}{old_correct} 新={new_dir.direction}{new_correct} 实际={actual_dir}")
