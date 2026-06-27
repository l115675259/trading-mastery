# 统一交易引擎 — 完整工作流 v3.0

## 核心理念

> Python 只做数据计算。LLM 做全部分析判断。
> 一个入口 `run.py`。环境自愈。零手动配置。

## 命令速查

```bash
# 实时分析（单币）
python scripts/run.py live AVAXUSDT

# 批量回测（多币）
python scripts/run.py backtest --coins AVAXUSDT,ADAUSDT,BTCUSDT,ETHUSDT

# 信号扫描（多币）
python scripts/run.py scan
```

## 端到端流程

```
Step 0: run.py 环境自愈
  ├─ 查找 Python 3.12+（brew/conda/system）
  ├─ 检查/安装缺失包（binpan/pandas/numpy/requests）
  ├─ 探测配置代理（7890 > 1087 > 直连）
  └─ 验证 Binance 连通

Step 1: 数据拉取 (data_pipeline.py)
  ├─ binpan 拉取 K 线（支持 1d/4h/1h/15m）
  ├─ 列名标准化（大写→小写，内部统一）
  └─ 35+ 指标计算：EMA/SMA/MACD/RSI/Stoch/ATR/BB/ADX/Supertrend/HA/Ichimoku/DI/Vol

Step 2: 指标计算 (data_pipeline.py — 同一函数)
  ├─ 趋势：EMA12/26/50/100, SMA20/50/100/200
  ├─ 动量：MACD/RSI/Stochastic
  ├─ 波动：ATR(20)/Bollinger Bands(20,2)
  ├─ 方向：ADX(14)/+DI/-DI, Supertrend(10,3)
  ├─ 日式：Heikin-Ashi, Ichimoku(9,26,52), Difference Index
  └─ 量价：Volume SMA20, Volume Ratio

Step 3: LLM 分析（Agent 执行，基于 LLM_ANALYSIS_PROMPT.md）
  ├─ Phase 1: 市场诊断
  │   ├─ ADX → 状态（strong_trend/weak_trend/ranging/extreme）
  │   ├─ 4工具投票 → 方向（UP/DOWN/NEUTRAL）
  │   └─ 异常检测（RSI极端/BB收窄/量异常）
  ├─ Phase 2: 工具选择
  │   ├─ ADX>40 → 启用趋势跟踪+波浪+突破，忽略RSI逆势信号
  │   ├─ ADX25-35 → 启用EMA交叉+K线关键位
  │   └─ ADX<20 → 启用RSI摆指+BB区间+支撑阻力
  ├─ Phase 3: 信号评估
  │   ├─ 多头/空头信号检测（K线形态+指标交叉+突破）
  │   ├─ 8种陷阱逐项检查
  │   │   T1假突破 T2多头陷阱 T3空头陷阱 T4RSI背离
  │   │   T5死猫反弹 T6反复穿刺 T7BB假突破 T8ST翻转
  │   └─ 信号质量评定
  └─ Phase 4: 决策输出
      ├─ 入场价/止损价/止盈价
      ├─ 盈亏比计算（≥2:1）
      └─ 仓位建议

Step 4: 三遍校验（LLM 自动执行）
  ├─ Pass 1: 数字溯源 — 所有数值在原始数据中可查
  ├─ Pass 2: 逻辑一致 — 诊断/工具/方向之间无矛盾
  └─ Pass 3: 完整性 — Phase 1-4 全完成，无遗漏

Step 5: 交易执行/回测
  ├─ 实时模式 → 输出决策供交易
  └─ 回测模式 → backtest_engine.py 模拟 + 统计
```

## 实时分析输出示例

```
  AVAXUSDT @ 2026-06-26 | 6.6330
  状态: strong_trend | 方向: DOWN | ADX=54 RSI=44
  启用: trend_following, adx, breakout, ma_cross
  禁用: rsi_oversold, stoch, bb_mean_reversion
  陷阱: medium (bull_trap_risk)
  信号: 不入场 — 日线空头 + 4H反弹多头陷阱风险
  决策: 等待
```

## 回测输出示例

```
  Coin         Trades     WR    PF   Total    Avg
  AVAXUSDT         60  61.7%  2.63  91.2%  +1.5%
  ADAUSDT          52  65.4%  2.57  94.4%  +1.8%
  BTCUSDT          62  58.1%  1.94  66.7%  +1.1%
  ──────────────────────────────────────────────
  Total: 554 trades, WR=58.7%, PF=2.08, +48.9%
```

## 校验失败处理

| 场景 | 处理 |
|------|------|
| Pass1 失败 | 删除无来源的判断，重新分析 |
| Pass2 失败 | 标记矛盾，调整工具选择，重新评估 |
| Pass3 失败 | 补全遗漏阶段 |
| 校验 0 错误 | 输出决策/执行交易 |

---

*所有分析判断由 LLM 完成。Python 只负责数据拉取、指标计算和交易模拟。*
