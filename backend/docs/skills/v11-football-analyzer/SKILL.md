---
name: v11-football-analyzer
description: 🍒 Cherry V11 v1.1 信号驱动的足球让球盘赔率分析框架。六步管道+三大bug修复（三选二投票修复、让-2深盘模式识别、置信度校准）。三方案构建：A稳健基石🛡️ B均衡回报⚖️ C高赔冲刺🚀。Use when user provides match odds data (让球盘胜/平/负赔率、排名、百家平均) and expects actionable parlay selections with confidence labels.
---

# 🍒 Cherry V11 v1.1 — Football Analyzer (Bug Fix Edition)

## 修复内容

### Bug #1: 三选二投票平局修复
- 外部信号分级：2票=双信号确认，1票=强制灰标不入串，0票=灰标
- 单信号场次不再参与任何方案构建

### Bug #2: 让-2深盘模式识别
- 新增 `_deep_handicap_check()` 检测 |handicap|≥2
- 百家主胜概率>65%时，强制转向让平（净胜2球走水剧本）
- 周四验证：皇马vs奥维耶多(2-0)、胡巴尔vs拉斯(2-0) 均正确

### Bug #3: 置信度校准
- 上限80%（不再虚高到100%）
- 基础值从60降到50
- 单信号自动扣10点
- 深盘让平强制给55%

## 实战效果（周四复盘）
| v1.0 | 2/5 ❌ | v1.1 | 4/5 ✅✅✅✅ |

## 核心流程

```
Match(...) → V11Analyzer.analyze_match(m) → Prediction
    ↓
V11Analyzer.build_strategies(predictions) → {strategy_a, strategy_b, strategy_c}
```

## 数据结构

参见 `scripts/v11_analyzer_v2.py` 中 `Match` / `Prediction` / `AvgOdds` dataclass。

**关键输入字段：**
- `handicap`: 让球数 (-2, -1, 0, +1...)
- `odds_win/draw/loss`: 对应让球盘赔率
- `avg_odds`: `AvgOdds(home, draw, away)` 百家平均赔率（可选）
- `prev_odds_win/draw/loss`: 前次赔率（可选，用于走势分析）

**输出 Prediction 含:** match_id, direction, label, min_odd, spread, rank_gap, trend, confidence(0-80)

## 标签系统 v1.1

| 标签 | 条件 | 置信度 | 操作 |
|------|------|--------|------|
| 🟢 绿标 | vote_strength≥2 + 基本面一致/无法判断 + spread中/强 | ≤80 | 核心建串 |
| 🟡 黄标 | 深盘让平干扰 或 基本面一致但缺信号 | 55 | B/C方案调味 |
| ⚠️ 灰标 | vote_strength≤1 (单信号或无信号) 或 spread弱 | 25-30 | **不入串** |
| 🔥 高赔候选 | 基本面打架 + 排名差≥10 | 35 | C方案红利 |
| 🚫 不入 | 赔率门槛外，或打架且排名差<5 | 0 | 放弃 |

## 三方案 v1.1

- **A 稳健基石**: 绿标场次, odds尽量<2.50, 资金动态分配
- **B 均衡回报**: 绿标+黄标混合, 综合赔率灵活, 资金动态分配
- **C 高赔冲刺**: 绿标+黄标深盘让平, 综合赔率较高, 资金动态分配

资金分配基于平均置信度自适应调整。

## 哲学原则

1. 两票再动，一票不动（三选二核心规则）
2. 灰标不入串
3. 深盘让平是强制干预而非预测
4. 宁缺毋滥：没4串1就不出
5. 置信度上限80%，诚实比漂亮重要
6. 赔率走势比绝对数值更有信息量

## 运行

```bash
python scripts/predict.py     # 最新版（v1.1别名）
python scripts/v11_analyzer_v2.py  # 原始v1.1文件
```

Python 3.8+, 仅标准库。

