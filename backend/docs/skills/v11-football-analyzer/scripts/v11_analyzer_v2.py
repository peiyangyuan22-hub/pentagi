# -*- coding: utf-8 -*-
"""
V11 足球分析框架 v2.0 — Pipeline架构

架构继承自OpenClaw ToolDescriptor设计模式：
  1. PipelineStep: 每个分析步骤独立可测，带 availability 检测
  2. DataProvider: 统一数据获取接口，可插拔
  3. Formatter: 结构化输出 + AvailabilityReport

兼容旧接口：V11Analyzer.analyze_match() 签名不变

改进 vs v1.1:
  ✅ 深盘让平逻辑修正（66%-80%阈值 + 客队让球处理）
  ✅ 单信号+Edge>0不再降灰标
  ✅ 三选二投票不再打架时被动让平
  ✅ Kelly Edge 整合进标签判定
  ✅ Monte Carlo seed固定可复现
  ✅ 每个Step可单独验证
  ✅ 输出带availability报告

使用：python v11_analyzer_v2.py
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Callable, Any
import json
import math
import os
import random
from datetime import datetime, timezone, timedelta


# ==================== 常量 ====================

MIN_ODD = 1.30
MAX_ODD = 5.00
RANK_GAP_HIGH = 5

FUND_ALLOCATION = {"A": 40, "B": 40, "C": 20}

KELLY_FRACTION = 0.25
KELLY_MAX_STAKE = 0.15
KELLY_MIN_EDGE = 0.05

MC_SEED = 42  # 固定种子，保证可复现
MC_SIMULATIONS = 5000

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
    league: str
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


@dataclass
class Context:
    """
    分析上下文 — PipelineStep之间传递的共享状态。
    类似OpenClaw ToolPlan的中间数据存储。
    """
    match: Match
    direction: Optional[str] = None
    min_odd: float = 0.0
    vote_strength: int = 0
    spread: float = 0.0
    rank_gap: Optional[int] = None
    rank_note: str = ""
    fundamental_agrees: Optional[bool] = None
    avg_agrees: Optional[bool] = None
    avg_convert_score: float = 0.5
    trend: str = "N/A"
    deep_dir: Optional[str] = None
    deep_penalty: int = 0
    deep_diag: str = ""
    kelly_edge: float = 0.0
    base_win_prob: float = 0.0
    label: str = ""
    confidence: int = 0


@dataclass
class StepResult:
    """PipelineStep的执行结果，带 availability 信息"""
    step_name: str
    success: bool
    data: Any = None
    availability: bool = True
    message: str = ""
    diagnostics: List[str] = field(default_factory=list)


# ==================== PipelineStep 基类 ====================

class PipelineStep:
    """
    分析管道中的一步。
    
    对应OpenClaw的ToolDescriptor：
    - name: 步骤名
    - description: 做什么
    - input_requirements: 需要context中的哪些字段
    - availability_check: 该步骤是否可用（数据是否齐全）
    - execute: 执行逻辑
    """
    
    name: str = ""
    description: str = ""
    
    def input_requirements(self) -> List[str]:
        """返回需要context中存在的字段名列表"""
        return []
    
    def availability_check(self, ctx: Context) -> StepResult:
        """
        检查该步骤是否可以执行。
        对应OpenClaw的ToolAvailabilitySignal。
        """
        missing = []
        for req in self.input_requirements():
            if not hasattr(ctx, req):
                missing.append(req)
            elif getattr(ctx, req) is None:
                missing.append(req)
        if missing:
            return StepResult(
                step_name=self.name,
                success=False,
                availability=False,
                message=f"缺少输入: {', '.join(missing)}",
                diagnostics=[f"缺失字段: {missing}"],
            )
        return StepResult(
            step_name=self.name,
            success=True,
            availability=True,
            message="可用",
        )
    
    def execute(self, ctx: Context) -> Context:
        """执行步骤，修改context中的数据"""
        raise NotImplementedError


# ==================== 步骤1: 市场方向 ====================

class MarketDirectionStep(PipelineStep):
    name = "market_direction"
    description = "从让球盘赔率中确定市场方向，三选二投票机制"
    
    def input_requirements(self) -> List[str]:
        return ["match"]
    
    def availability_check(self, ctx: Context) -> StepResult:
        m = ctx.match
        if not m.odds_win or not m.odds_draw or not m.odds_loss:
            return StepResult(
                step_name=self.name, success=False, availability=False,
                message="缺少让球盘赔率",
                diagnostics=["odds_win/odds_draw/odds_loss 至少一项为0或None"],
            )
        return StepResult(step_name=self.name, success=True, availability=True, message="赔率数据完整")
    
    def execute(self, ctx: Context) -> Context:
        m = ctx.match
        options = [
            (Direction.WIN, m.odds_win),
            (Direction.DRAW, m.odds_draw),
            (Direction.LOSS, m.odds_loss),
        ]
        market_dir, market_odd = min(options, key=lambda x: x[1])
        
        # 信号B: 百家平均方向
        avg_dir = None
        if m.avg_odds is not None:
            avg_dir = Direction.WIN if m.avg_odds.home < m.avg_odds.away else Direction.LOSS
        
        # 信号C: 基本面方向（只看排名差距>5）
        rank_gap = self._get_rank_gap(m)
        fund_dir = None
        if rank_gap is not None and abs(rank_gap) > RANK_GAP_HIGH:
            fund_dir = Direction.WIN if rank_gap < 0 else Direction.LOSS
        
        # 统计外部投票（只计让胜/让负，不计让平）
        ext_win = 0
        ext_loss = 0
        for d in (avg_dir, fund_dir):
            if d == Direction.WIN:
                ext_win += 1
            elif d == Direction.LOSS:
                ext_loss += 1
        
        total_ext = ext_win + ext_loss
        ctx.vote_strength = total_ext
        
        if total_ext >= 2:
            if ext_win == 2:
                winner = Direction.WIN
            elif ext_loss == 2:
                winner = Direction.LOSS
            else:
                winner = market_dir  # 两信号打架 → 退守市场
            ctx.direction = winner
            ctx.min_odd = m.odds_win if winner == Direction.WIN else m.odds_loss
        elif total_ext == 1:
            ctx.direction = market_dir
            ctx.min_odd = market_odd
        else:
            ctx.direction = market_dir
            ctx.min_odd = market_odd
        
        return ctx
    
    def _get_rank_gap(self, m: Match) -> Optional[int]:
        if m.home_rank is None or m.away_rank is None:
            return None
        return m.home_rank - m.away_rank


# ==================== 步骤2: Spread计算 ====================

class SpreadStep(PipelineStep):
    name = "spread"
    description = "计算赔率离散度，评估信号强度"
    
    def input_requirements(self) -> List[str]:
        return ["match"]
    
    def execute(self, ctx: Context) -> Context:
        m = ctx.match
        odds = [m.odds_win, m.odds_draw, m.odds_loss]
        ctx.spread = round(max(odds) - min(odds), 2)
        return ctx
    
    @staticmethod
    def classify_strength(spread: float) -> str:
        if spread >= 1.0:
            return "strong"
        elif spread >= 0.5:
            return "medium"
        return "weak"


# ==================== 步骤3: 基本面交叉验证 ====================

class FundamentalStep(PipelineStep):
    name = "fundamental"
    description = "用排名差距验证市场方向"
    
    def input_requirements(self) -> List[str]:
        return ["match", "direction"]
    
    def execute(self, ctx: Context) -> Context:
        m = ctx.match
        rank_gap = self._get_rank_gap(m)
        ctx.rank_gap = rank_gap
        ctx.rank_note = self._rank_note(m, rank_gap)
        
        if rank_gap is None:
            ctx.fundamental_agrees = None
            return ctx
        
        if abs(rank_gap) <= RANK_GAP_HIGH:
            ctx.fundamental_agrees = None
            return ctx
        
        fundamental_favors_home = (rank_gap < 0)
        market_favors_home = (ctx.direction == Direction.WIN)
        ctx.fundamental_agrees = (fundamental_favors_home == market_favors_home)
        return ctx
    
    def _get_rank_gap(self, m: Match) -> Optional[int]:
        if m.home_rank is None or m.away_rank is None:
            return None
        return m.home_rank - m.away_rank
    
    def _rank_note(self, m: Match, rank_gap: Optional[int]) -> str:
        if m.home_rank is None or m.away_rank is None:
            return "无排名数据"
        gap = rank_gap
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


# ==================== 步骤4: 百家平均交叉验证 ====================

class AverageOddsStep(PipelineStep):
    name = "avg_odds"
    description = "用百家平均赔率验证市场方向，含让球换算检查"
    
    def input_requirements(self) -> List[str]:
        return ["match", "direction"]
    
    def availability_check(self, ctx: Context) -> StepResult:
        m = ctx.match
        if m.avg_odds is None:
            return StepResult(
                step_name=self.name, success=False, availability=False,
                message="缺少百家平均赔率",
                diagnostics=["avg_odds is None"],
            )
        return StepResult(step_name=self.name, success=True, availability=True, message="百家数据完整")
    
    def execute(self, ctx: Context) -> Context:
        m = ctx.match
        avg_favors_home = (m.avg_odds.home < m.avg_odds.away)
        market_favors_home = (ctx.direction == Direction.WIN)
        ctx.avg_agrees = (avg_favors_home == market_favors_home)
        
        # 让球换算检查
        if ctx.direction == Direction.WIN and m.handicap < 0:
            gap = m.avg_odds.away - m.avg_odds.home
            required = abs(m.handicap) + 0.5
            ctx.avg_convert_score = min(gap / required, 1.0) if required > 0 else 0.5
        elif ctx.direction == Direction.LOSS and m.handicap > 0:
            gap = m.avg_odds.home - m.avg_odds.away
            required = abs(m.handicap) + 0.5
            ctx.avg_convert_score = min(gap / required, 1.0) if required > 0 else 0.5
        else:
            ctx.avg_convert_score = 0.5
        
        return ctx


# ==================== 步骤5: 赔率走势 ====================

class TrendStep(PipelineStep):
    name = "trend"
    description = "检查赔率走势（初赔vs即赔）— 优先使用OddsCache"
    
    def __init__(self, odds_cache=None):
        super().__init__()
        self._cache = odds_cache
    
    def input_requirements(self) -> List[str]:
        return ["match"]
    
    def availability_check(self, ctx: Context) -> StepResult:
        m = ctx.match
        
        # 内置prev_odds
        if m.prev_odds_win is not None:
            return StepResult(
                step_name=self.name, success=True, availability=True,
                message="有内置初赔数据",
            )
        
        # 外部OddsCache
        if self._cache is not None:
            trend_data = self._cache.get_trend(m.match_id)
            if trend_data is not None:
                return StepResult(
                    step_name=self.name, success=True, availability=True,
                    message=f"从OddsCache获取趋势: {trend_data['direction']}",
                )
        
        return StepResult(
            step_name=self.name, success=False, availability=False,
            message="缺少初赔数据且无OddsCache",
            diagnostics=["prev_odds_win is None, no cache"],
        )
    
    def execute(self, ctx: Context) -> Context:
        m = ctx.match
        
        # 优先内置prev_odds
        if m.prev_odds_win is not None:
            prev_min = min(m.prev_odds_win, m.prev_odds_draw, m.prev_odds_loss)
            curr_min = min(m.odds_win, m.odds_draw, m.odds_loss)
        elif self._cache is not None:
            td = self._cache.get_trend_for_pipeline(m.match_id)
            if td:
                # 从趋势数据反推方向
                ctx.trend = td["direction"]
                ctx._diagnostics["trend"] = td
                return ctx
            else:
                ctx.trend = "无数据"
                return ctx
        else:
            ctx.trend = "无数据"
            return ctx
        
        delta = round(curr_min - prev_min, 2)
        if delta < -0.02:
            ctx.trend = "收紧"
        elif delta > 0.02:
            ctx.trend = "放宽"
        else:
            ctx.trend = "持平"
        return ctx


# ==================== 步骤6: 让-2深盘检查 ====================

class DeepHandicapStep(PipelineStep):
    name = "deep_handicap"
    description = "对|handicap|≥2的深盘做让平分水岭检查"
    
    def input_requirements(self) -> List[str]:
        return ["match", "direction"]
    
    def availability_check(self, ctx: Context) -> StepResult:
        m = ctx.match
        if abs(m.handicap) < 2:
            return StepResult(
                step_name=self.name, success=False, availability=False,
                message=f"非深盘(handicap={m.handicap})，跳过",
                diagnostics=[f"|handicap|={abs(m.handicap)} < 2"],
            )
        if m.avg_odds is None:
            return StepResult(
                step_name=self.name, success=False, availability=False,
                message="深盘但无百家数据，无法做让平检查",
                diagnostics=["深盘需要百家平均赔率做让平分水岭"],
            )
        return StepResult(step_name=self.name, success=True, availability=True, message=f"深盘检查可用")
    
    def execute(self, ctx: Context) -> Context:
        m = ctx.match
        
        # 计算百家平均隐含概率（反佣金修正）
        raw_home_p = 1.0 / m.avg_odds.home
        raw_draw_p = 1.0 / m.avg_odds.draw
        raw_away_p = 1.0 / m.avg_odds.away
        total_raw = raw_home_p + raw_draw_p + raw_away_p
        home_prob = raw_home_p / total_raw
        away_prob = raw_away_p / total_raw
        
        if m.handicap < 0:  # 主队让球
            if 0.65 < home_prob <= 0.80:
                if ctx.direction != Direction.DRAW:
                    ctx.deep_dir = Direction.DRAW
                    ctx.deep_penalty = 20
                    ctx.deep_diag = f"深盘让平(主{home_prob:.0%})"
                else:
                    ctx.deep_penalty = 5
        else:  # 客队让球（handicap > 0，实质客队让深盘）
            if 0.65 < away_prob <= 0.80:
                if ctx.direction != Direction.DRAW:
                    ctx.deep_dir = Direction.DRAW
                    ctx.deep_penalty = 20
                    ctx.deep_diag = f"深盘让平(客{away_prob:.0%})"
                else:
                    ctx.deep_penalty = 5
        
        return ctx


# ==================== 步骤7: Kelly Edge ====================

class KellyEdgeStep(PipelineStep):
    name = "kelly_edge"
    description = "计算Kelly Edge（预期价值）"
    
    def input_requirements(self) -> List[str]:
        return ["match", "direction", "min_odd"]
    
    def execute(self, ctx: Context) -> Context:
        # 估算基础胜率
        base_win_prob = 1.0 / ctx.min_odd
        
        # 双信号 + spread中强，调高信任
        strength = SpreadStep.classify_strength(ctx.spread)
        if ctx.vote_strength >= 2 and strength in ("medium", "strong"):
            base_win_prob = min(base_win_prob * 1.15, 0.80)
        elif ctx.vote_strength == 1 and strength in ("medium", "strong"):
            base_win_prob = min(base_win_prob * 1.05, 0.70)
        
        ctx.base_win_prob = base_win_prob
        
        # Edge = 模型概率 - 隐含概率
        if ctx.min_odd <= 1.0:
            ctx.kelly_edge = -1.0
        else:
            implied_prob = 1.0 / ctx.min_odd
            ctx.kelly_edge = base_win_prob - implied_prob
        
        return ctx


# ==================== 步骤8: 标签 + 置信度 ====================

class LabelStep(PipelineStep):
    name = "label"
    description = "基于所有信号输出标签和置信度"
    
    def input_requirements(self) -> List[str]:
        return ["match", "direction", "min_odd", "spread", "vote_strength",
                "kelly_edge", "base_win_prob"]
    
    def execute(self, ctx: Context) -> Context:
        m = ctx.match
        
        # 赔率门槛
        if ctx.min_odd < MIN_ODD or ctx.min_odd > MAX_ODD:
            ctx.label = Label.EXCLUDE
            ctx.confidence = 0
            return ctx
        
        # 信号强度
        strength = SpreadStep.classify_strength(ctx.spread)
        
        # 弱信号 → 灰标
        if strength == "weak":
            ctx.label = Label.GRAY
            ctx.confidence = 20
            return ctx
        
        # 无外部信号 → 灰标
        if ctx.vote_strength == 0:
            ctx.label = Label.GRAY
            ctx.confidence = 25
            return ctx
        
        # ── 单信号 ──
        if ctx.vote_strength == 1:
            if ctx.kelly_edge > 0:
                base_conf = 50
                if ctx.fundamental_agrees is True:
                    base_conf += 10
                if ctx.avg_agrees is True:
                    base_conf += 8
                imp_conf = int(ctx.base_win_prob * 100)
                final_conf = min(max(base_conf, imp_conf, 55), 75)
                ctx.label = Label.YELLOW
                ctx.confidence = final_conf
            else:
                ctx.label = Label.GRAY
                ctx.confidence = 30
            return ctx
        
        # ── 双信号 ──
        # 基本面与市场打架
        if ctx.fundamental_agrees is False:
            if ctx.rank_gap is not None and abs(ctx.rank_gap) >= 10:
                ctx.label = Label.HOT
                ctx.confidence = 35
            elif ctx.rank_gap is not None and abs(ctx.rank_gap) >= 5:
                ctx.label = Label.HOT
                ctx.confidence = 30
            else:
                ctx.label = Label.EXCLUDE
                ctx.confidence = 0
            return ctx
        
        # 计算置信度
        base_conf = 55
        if ctx.fundamental_agrees is True:
            base_conf += 15
        if ctx.avg_agrees is True:
            base_conf += 10
        base_conf += int(ctx.avg_convert_score * 8)
        if ctx.trend == "收紧":
            base_conf += 8
        
        final_conf = min(base_conf, 80)
        
        if final_conf >= 65:
            ctx.label = Label.GREEN
        elif final_conf >= 40:
            ctx.label = Label.YELLOW
        else:
            ctx.label = Label.GRAY
        
        ctx.confidence = final_conf
        return ctx


# ==================== 步骤9: 深盘覆盖 ====================

class DeepOverrideStep(PipelineStep):
    name = "deep_override"
    description = "深盘干预后强制覆盖标签和置信度"
    
    def input_requirements(self) -> List[str]:
        return ["match", "deep_dir", "label", "confidence"]
    
    def availability_check(self, ctx: Context) -> StepResult:
        if ctx.deep_dir is None:
            return StepResult(
                step_name=self.name, success=False, availability=False,
                message="无需深盘覆盖",
            )
        return StepResult(step_name=self.name, success=True, availability=True, message=f"需深盘覆盖")
    
    def execute(self, ctx: Context) -> Context:
        ctx.direction = ctx.deep_dir
        
        # 更新min_odd为让平赔率
        dir_odd_map = {
            Direction.WIN: ctx.match.odds_win,
            Direction.DRAW: ctx.match.odds_draw,
            Direction.LOSS: ctx.match.odds_loss,
        }
        ctx.min_odd = dir_odd_map.get(ctx.direction, ctx.min_odd)
        
        ctx.label = Label.YELLOW
        ctx.confidence = max(ctx.confidence, 55)
        return ctx


# ==================== Pipeline 编排 ====================

class AnalysisPipeline:
    """
    分析管道 — 按顺序执行步骤。
    
    类似OpenClaw的BuildToolPlan：
    1. 收集所有Step
    2. 依次执行availability_check
    3. 可用步骤执行execute
    4. 不可用步骤跳过，在报告中标记
    """
    
    def __init__(self, odds_cache=None):
        self.odds_cache = odds_cache
        self.steps: List[PipelineStep] = [
            MarketDirectionStep(),
            SpreadStep(),
            FundamentalStep(),
            AverageOddsStep(),
            TrendStep(odds_cache=odds_cache),
            DeepHandicapStep(),
            KellyEdgeStep(),
            LabelStep(),
            DeepOverrideStep(),
        ]
    
    def run(self, ctx: Context) -> Tuple[Context, List[StepResult]]:
        """运行管道，返回最终ctx + 每一步的执行报告"""
        step_results = []
        
        for step in self.steps:
            # 1. availability check
            avail = step.availability_check(ctx)
            
            if not avail.availability:
                avail.message = f"[跳过] {avail.message}"
                step_results.append(avail)
                continue
            
            # 2. execute
            try:
                ctx = step.execute(ctx)
                step_results.append(StepResult(
                    step_name=step.name,
                    success=True,
                    availability=True,
                    message=f"✅ {step.description}",
                    diagnostics=[],
                ))
            except Exception as e:
                step_results.append(StepResult(
                    step_name=step.name,
                    success=False,
                    availability=True,
                    message=f"❌ 执行失败: {e}",
                    diagnostics=[str(e)],
                ))
        
        # 补充vote_info
        if ctx.direction:
            raw_options = [
                (Direction.WIN, ctx.match.odds_win),
                (Direction.DRAW, ctx.match.odds_draw),
                (Direction.LOSS, ctx.match.odds_loss),
            ]
            raw_market_dir, _ = min(raw_options, key=lambda x: x[1])
            is_contrarian = (ctx.direction != raw_market_dir)
            
            vote_parts = []
            if ctx.match.avg_odds is not None:
                vote_parts.append(f"百家{'同' if ctx.avg_agrees else '反'}")
            if ctx.rank_gap is not None and abs(ctx.rank_gap) > RANK_GAP_HIGH:
                vote_parts.append(f"基本面{'同' if ctx.fundamental_agrees else '反'}")
            votes_str = " ".join(vote_parts)
            if is_contrarian:
                ctx.vote_info = f"⚡{votes_str} 逆市场{raw_market_dir}"
            else:
                ctx.vote_info = f"✅{votes_str} 跟市场"
            
            if ctx.deep_dir is not None:
                ctx.vote_info += f" [深盘→让平]"
        
        return ctx, step_results


# ==================== V11Analyzer v2 ====================

class V11Analyzer:
    """Cherry V11 分析引擎 v2.0 — Pipeline架构"""
    
    def __init__(self, min_odd=MIN_ODD, max_odd=MAX_ODD, odds_cache=None):
        self.min_odd = min_odd
        self.max_odd = max_odd
        self.pipeline = AnalysisPipeline(odds_cache=odds_cache)
    
    def analyze_match(self, m: Match, tracker: Optional["ReviewTracker"] = None) -> Prediction:
        ctx = Context(match=m)
        ctx, step_results = self.pipeline.run(ctx)
        
        # 也可返回 step_results 用于调试，这里只构建Prediction
        pred = self._build_prediction(m, ctx)
        
        if tracker:
            tracker.record(m.match_id, pred.direction, pred.label, pred.min_odd, pred.confidence)
        
        return pred
    
    def analyze_match_with_report(self, m: Match) -> Tuple[Prediction, List[StepResult]]:
        """分析比赛 + 返回步骤执行报告（调试用）"""
        ctx = Context(match=m)
        ctx, step_results = self.pipeline.run(ctx)
        
        pred = self._build_prediction(m, ctx)
        
        return pred, step_results
    
    def analyze_matches(self, matches: List[Match], tracker: Optional["ReviewTracker"] = None) -> List[Prediction]:
        return [self.analyze_match(m, tracker) for m in matches]
    
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
    
    def _build_prediction(self, m: Match, ctx: Context) -> Prediction:
        return Prediction(
            match_id=m.match_id,
            league=m.league,
            direction=ctx.direction or Direction.DRAW,
            label=ctx.label or Label.EXCLUDE,
            min_odd=ctx.min_odd or 0,
            spread=ctx.spread,
            rank_gap=ctx.rank_gap,
            trend=ctx.trend or "N/A",
            confidence=ctx.confidence or 0,
            rank_note=ctx.rank_note or "",
            vote_info=ctx.vote_info or "",
        )
    
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


# ==================== 独立函数 ====================

def kelly_criterion(odds: float, prob: float, bankroll_pct: float = KELLY_FRACTION) -> float:
    b = odds - 1.0
    q = 1.0 - prob
    edge = b * prob - q
    if edge <= KELLY_MIN_EDGE:
        return 0.0
    fraction = bankroll_pct * edge / b
    return min(max(fraction, 0.0), KELLY_MAX_STAKE)


# ==================== 蒙特卡洛模拟（固定种子） ====================

def monte_carlo_simulation(
    pick: Prediction,
    num_simulations: int = MC_SIMULATIONS,
    seed: int = MC_SEED,
) -> dict:
    rng = random.Random(seed + hash(pick.match_id) % (2**31))
    
    raw_odds = [pick.min_odd, 1.0, 1.0]
    conf_factor = pick.confidence / 100.0
    
    if pick.direction == Direction.WIN:
        win_w = conf_factor * 0.7
        draw_w = (1 - conf_factor) * 0.5
        loss_w = (1 - conf_factor) * 0.5
    elif pick.direction == Direction.DRAW:
        draw_w = conf_factor * 0.55
        win_w = (1 - conf_factor) * 0.5
        loss_w = (1 - conf_factor) * 0.5
    else:
        loss_w = conf_factor * 0.7
        draw_w = (1 - conf_factor) * 0.5
        win_w = (1 - conf_factor) * 0.5
    
    total_w = win_w + draw_w + loss_w
    win_pct = win_w / total_w
    draw_pct = draw_w / total_w
    loss_pct = loss_w / total_w
    
    hits = 0
    for _ in range(num_simulations):
        r = rng.random()
        if r < win_pct:
            result = Direction.WIN
        elif r < win_pct + draw_pct:
            result = Direction.DRAW
        else:
            result = Direction.LOSS
        if result == pick.direction:
            hits += 1
    
    return {
        "direction": pick.direction,
        "hit_rate": round(hits / num_simulations, 4),
        "win_pct": round(win_pct, 4),
        "draw_pct": round(draw_pct, 4),
        "loss_pct": round(loss_pct, 4),
        "simulations": num_simulations,
        "seed": seed,
    }


def monte_carlo_parlay(picks: List[Prediction], num_simulations: int = MC_SIMULATIONS, seed: int = MC_SEED) -> dict:
    if len(picks) != 4:
        return {"error": "需要4串1"}
    
    sim_results = []
    for p in picks:
        sim_results.append(monte_carlo_simulation(p, num_simulations, seed))
    
    combo_odd = 1.0
    for p in picks:
        combo_odd *= p.min_odd
    
    rng = random.Random(seed + 9999)
    hit_counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    all_hits = 0
    
    for _ in range(num_simulations):
        hit_count = 0
        for sim in sim_results:
            r = rng.random()
            probs = [sim["win_pct"], sim["draw_pct"], sim["loss_pct"]]
            p_sum = 0
            result = Direction.WIN
            for idx, prob in enumerate(probs):
                p_sum += prob
                if r < p_sum:
                    result = [Direction.WIN, Direction.DRAW, Direction.LOSS][idx]
                    break
            if result == sim["direction"]:
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
        "seed": seed,
        "expected_return": round(all_hits / num_simulations * combo_odd, 4),
    }


# ==================== Availability报告 ====================

def print_availability_report(results: List[StepResult]):
    """打印pipeline步骤的availability诊断报告"""
    print("  📊 Pipeline Availability Report")
    print("  " + "-" * 50)
    for r in results:
        status = "✅" if r.availability else "⏭️"
        ok = "✓" if r.success else "✗"
        print(f"  {status} [{r.step_name}] {ok} {r.message}")
        for d in r.diagnostics:
            print(f"       ↳ {d}")


# ==================== 测试运行 ====================

if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    # ── 测试数据 ──
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
    
    print("=" * 60)
    print("  🍒 Cherry V11 v2.0 — Pipeline架构")
    print("=" * 60)
    
    results = []
    for m in sample_matches:
        pred, step_reports = analyzer.analyze_match_with_report(m)
        results.append(pred)
        
        kelly_pct = kelly_criterion(pred.min_odd, pred.confidence / 100)
        kelly_str = f"  Kelly={kelly_pct*100:.1f}%" if kelly_pct > 0 else ""
        
        print(f"\n  [{pred.match_id}] {pred.league}")
        print(f"  {pred.direction}  {pred.label}  赔率{pred.min_odd}  conf={pred.confidence}%{kelly_str}")
        print(f"  {pred.vote_info}  |  {pred.rank_note}")
        
        # 显示availability报告（前几个关键步骤即可）
        key_steps = [s for s in step_reports if s.step_name in 
                     ("market_direction", "avg_odds", "trend", "deep_handicap", "deep_override")]
        for s in key_steps:
            if not s.availability or not s.success:
                icon = "⏭️" if not s.availability else "⚠️"
                print(f"    {icon} {s.step_name}: {s.message}")
    
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
            
            # MC模拟
            mc = monte_carlo_parlay(picks)
            
            print(f"\n  [{name}]  资金={f}%  |  综合赔率 ≈ {combo_odd:.2f}x")
            if "all_hit_prob" in mc:
                print(f"    MC命中率={mc['all_hit_prob']:.2%}  期望回报={mc['expected_return']:.2f}x")
            for i, p in enumerate(picks):
                pmc = monte_carlo_simulation(p)
                print(f"    {i+1}. {p.match_id} {p.direction} {p.label} 赔率{p.min_odd} conf={p.confidence}% MC命中={pmc['hit_rate']:.1%}")
            print(f"    Kelly: {', '.join([f'{k}%' for k in kelly_pcts])}")
            if "hit_distribution" in mc:
                dist = mc["hit_distribution"]
                print(f"    命中分布: {', '.join([f'{k}={v:.1%}' for k, v in sorted(dist.items())])}")
        else:
            print(f"\n  [{name}]  (无合格4串1)")
    
    # 周四复盘对比
    print("\n" + "=" * 60)
    print("  周四复盘对比")
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