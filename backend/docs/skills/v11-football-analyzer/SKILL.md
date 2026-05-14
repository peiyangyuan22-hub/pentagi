---
name: v11-football-analyzer
description: V11 信号驱动的足球分析框架，用于将用户提供的赔率数据（让球盘胜/平/负赔率、排名、百家平均、走势）转化为串关策略方案。六步管道：市场信号采集→基本面交叉验证→百家平均验证→赔率走势监控→标签生成→赔率门槛过滤。三方案输出：A 稳健基石、B 均衡回报、C 高赔冲刺。Use when user provides match odds data and expects actionable parlay selections with confidence labels.
---

# V11 Football Analyzer

## 核心流程

```
用户输入 match 赔率数据
    ↓
V11Analyzer.analyze_match() — 六步管道
    ↓
Prediction(match_id, direction, label, odd)
    ↓
build_strategies() → StrategyOutput(A, B, C)
```

## 文件结构

- `scripts/v11_analyzer.py` — 核心分析器（V11Analyzer class），可直接运行测试

## 使用方式

直接读取 `scripts/v11_analyzer.py` 中的 `V11Analyzer` 类即可。不需要加载 SKILL.md 以外的文件，除非需要查看源码细节。

## 标签系统

| 标签 | 条件 | 操作 |
|------|------|------|
| 🟢 绿标 | spread≥1.0 + 基本面一致 + 走势收紧 | 核心建串 |
| 🟡 黄标 | spread中/强 + 基本面一致 | 可入串（B方案调味） |
| ⚠️ 灰标 | spread<0.5 信号弱 | **不入串** |
| 🔥 高赔候选 | 基本面与市场打架 + 排名差极端 | C方案红利 |
| 🚫 不入 | 赔率门槛外或不可靠 | 放弃 |

## 三方案原则

1. **灰标不入串** — 信号弱的不考虑
2. **绿标永远是锚** — 再高赔的方案也得有至少两个绿标兜底
3. **高赔来自判断，不是来自数字大** — 只有🔥高赔候选才能入C方案
4. **走势比绝对值更有信息量** — 收紧代表市场认可

## 赔率门槛

- `MIN_ODD = 1.50` — 低于此不进
- `MAX_ODD = 4.00` — 高于此不进

## 运行测试

```bash
python scripts/v11_analyzer.py
```

需要 Python 3.8+，无外部依赖。仅使用标准库（dataclasses, enum, typing）。
