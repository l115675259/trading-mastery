---
name: trading-mastery
description: |
  综合7本经典交易著作的完整知识体系。
  涵盖：蜡烛图技术、期货市场技术分析、艾略特波浪理论、趋势交易系统、海龟交易法则、
  交易心理分析、股票大作手回忆录。
  
  When to use:
  - 用户询问任何技术分析、趋势判断、K线形态、市场结构问题
  - 用户需要制定交易策略、设计交易系统、进行资金管理
  - 用户需要分析具体品种的图表、判断趋势方向、找买卖点
  - 用户讨论交易心理、概率思维、纪律执行问题
  - 用户要求评估交易系统、做回测设计、风险管理
---

# 交易大师体系 v3.0 — 统一架构

## 架构总览

```
                    run.py（统一入口 + 环境自愈）
                          │
           ┌──────────────┼──────────────┐
           ▼              ▼              ▼
       live模式      backtest模式     scan模式
           │              │              │
           └──────────────┼──────────────┘
                          ▼
                 data_pipeline.py（数据层）
                 ┌───────────────────┐
                 │ 1. 环境自检+自修    │
                 │ 2. 代理自动配置     │
                 │ 3. K线拉取(Binance) │
                 │ 4. 35+指标全量计算  │
                 │ 5. 标准化JSON输出   │
                 └────────┬──────────┘
                          ▼
                 LLM 分析层（Agent执行）
                 ┌───────────────────┐
                 │ Phase 1: 市场诊断  │
                 │ Phase 2: 工具选择  │
                 │ Phase 3: 信号评估  │
                 │   + 8种陷阱检测    │
                 │ Phase 4: 决策输出  │
                 │ 三遍校验自动执行    │
                 └────────┬──────────┘
                          ▼
                 backtest_engine.py
                 ┌───────────────────┐
                 │ 交易模拟 + 统计    │
                 │ 不做任何分析判断   │
                 └───────────────────┘
```

**核心原则**：Python 只做数据计算。LLM 做全部分析判断。一个入口。零手动配置。

## 快速开始

```bash
# 环境自愈（自动检测 Python/包/代理）
python scripts/run.py

# 实时分析
python scripts/run.py live AVAXUSDT

# 批量回测
python scripts/run.py backtest --coins AVAXUSDT,ADAUSDT,BTCUSDT

# 多币扫描
python scripts/run.py scan
```

## 文件结构

```
trading-mastery/
├── SKILL.md                     # 本文件 — skill 入口
├── requirements.txt
├── references/
│   ├── LLM_ANALYSIS_PROMPT.md   # LLM 分析协议规范（Phase 1-4 + 陷阱 + 校验）
│   ├── WORKFLOW.md              # 完整工作流说明
│   └── *.md                     # 各书知识库
├── scripts/
│   ├── run.py                   # 统一入口
│   ├── data_pipeline.py         # 数据管道
│   ├── backtest_engine.py       # 回测引擎
│   └── plot_analysis.py         # 图表工具
└── agents/
    └── openai.yaml
```

## 三种运行模式

### live — 实时分析
LLM 读取 `data_pipeline.py` 输出的数据 → 执行完整协议 → 给出交易决策。
日线判趋势 + 4H 找入场信号、4H 退出的策略在此模式下由 LLM 按协议灵活决定。

### backtest — 批量回测
Python 拉取历史数据 + 计算指标。LLM 逐个信号执行完整协议分析。
LLM 输出标准化信号 JSON → `backtest_engine.py` 模拟执行 → 统计胜率/盈亏比/回报。

### scan — 快速扫描
多币种的当前状态一览。LLM 逐一判断有无入场信号。

## 知识体系（五层金字塔）

| 层级 | 名称 | 支撑书系 | 参考文件 |
|------|------|---------|---------|
| L1 | 市场认知 | 道氏理论(Livermore)、五大事实(Douglas) | reminiscences.md, trading-psychology.md |
| L2 | 技术分析 | K线(Nison)、形态/指标/波浪(Murphy) | candles.md, technical-analysis.md, elliott-wave.md |
| L3 | 交易系统 | 趋势跟踪(Clenow)、海龟法则(Faith) | trend-following.md, turtle-trading.md |
| L4 | 风险管理 | 资金管理(Murphy)、ATR仓位(Faith+Clenow) | technical-analysis.md, turtle-trading.md |
| L5 | 心理修炼 | 概率思维(Douglas)、自我修炼(Livermore) | trading-psychology.md, reminiscences.md |

## LLM 分析协议

分析时 LLM 必须遵守 [references/LLM_ANALYSIS_PROMPT.md](references/LLM_ANALYSIS_PROMPT.md)：

- **Phase 1**: 市场诊断 — ADX 判趋势市/震荡市，多工具投票定方向
- **Phase 2**: 工具选择 — 趋势市启用趋势工具，忽略RSI逆势信号
- **Phase 3**: 信号评估 — 多头/空头信号扫描 + 8种陷阱逐项检测 + 风险评级
- **Phase 4**: 决策输出 — 入场/止损/止盈/盈亏比/仓位 / 或不交易
- **三遍校验**: Pass1 数字溯源 → Pass2 逻辑一致 → Pass3 完整性

## 关键公式

| 公式 | 来源 | 用途 |
|------|------|------|
| TR = max(H-L, |H-C_prev|, |L-C_prev|) | Nison/Faith/Murphy | 真实波幅 |
| ATR = EMA(TR, 20) | Faith/Clenow | 平均波幅 |
| 仓位 = 账户×风险因子/(ATR×点价) | Clenow | 持仓限额 |
| 单位 = 账户×1%/(N×每点价值) | Faith | 海龟头寸 |
| 盈亏比 = 预期盈利/预期亏损 ≥ 2:1 | Murphy/Douglas | 交易筛选 |

---

*本体系整合 7 本经典交易著作 + 统一分析引擎 + 环境自愈系统。*
