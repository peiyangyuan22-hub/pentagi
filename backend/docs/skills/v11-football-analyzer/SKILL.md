---
name: v11-football-analyzer
description: 🍒 Cherry V11 信号驱动的足球让球盘赔率分析框架。六步管道：市场信号采集→基本面交叉验证→百家平均验证→赔率走势监控→标签判定（含置信度）→赔率门槛过滤。三方案构建：A稳健基石🛡️ B均衡回报⚖️ C高赔冲刺🚀。Use when user provides match odds data (让球盘胜/平/负赔率、排名、百家平均) and expects actionable parlay selections with confidence labels.
---

# 🍒 Cherry V11 — Football Analyzer

## 核心流程

```
Match(match_id, league, home/away_team, home/away_rank, handicap,
      odds_win/draw/loss, avg_odds?, prev_odds_win/draw/loss?)
    ↓
V11Analyzer.analyze_match(m) → Prediction
    ↓
V11Analyzer.build_strategies(predictions) → {strategy_a, strategy_b, strategy_c}
```

## 数据结构

参见 `scripts/v11_analyzer.py` 中 `Match` / `Prediction` / `AvgOdds` dataclass。

**关键输入字段：**
- `handicap`: 让球数 (-2, -1, 0, +1...)
- `odds_win/draw/loss`: 对应让球盘赔率
- `avg_odds`: `AvgOdds(home, draw, away)` 百家平均赔率（可选）
- `prev_odds_win/draw/loss`: 前次赔率（可选，用于走势分析）

**输出 Prediction 含:** match_id, direction, label, min_odd, spread, rank_gap, trend, confidence(0-100)

## 标签系统

| 标签 | 条件 | 置信度 | 操作 |
|------|------|--------|------|
| 🟢 绿标 | spread中/强 + 基本面一致 + 走势收紧 | ≥80 | 核心建串 |
| 🟡 黄标 | 基本面一致但缺走势/数据，或打架但排名差≥5 | 30-70 | B方案调味 |
| ⚠️ 灰标 | spread < 0.5 信号弱 | 20 | **不入串** |
| 🔥 高赔候选 | 基本面打架 + 排名差≥10 | 40 | C方案红利 |
| 🚫 不入 | 赔率门槛外，或打架且排名差<5 | 0 | 放弃 |

## 三方案

- **A 稳健基石**: ≤4场绿标, odds<2.00, 综合≈5-8x, 资金40%
- **B 均衡回报**: 2低+1中+1黄标, 综合≈10-13x, 资金40%
- **C 高赔冲刺**: 2锚底+1高赔+1补位, 综合≈12-18x, 资金20%

## 哲学原则

1. 不要跟市场对着干，除非有理由
2. 灰标不入串
3. 高赔来自判断不是来自数字大
4. 绿标永远是锚
5. 百家平均不是独立信号，是交叉验证
6. 赔率走势比绝对数值更有信息量

## 运行

```bash
python scripts/v11_analyzer.py
```

Python 3.8+, 仅标准库。
