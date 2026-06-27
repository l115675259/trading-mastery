# BinPan 集成文档

binpan 是 trading-mastery skill 的数据层和执行层，提供实时行情、指标计算、形态检测和回测能力。

## 能力全景

| binpan 能力 | 对接 skill 层级 | 具体用途 | 来源书系 |
|---|---|---|---|
| OHLCV 数据 | L1 市场认知 + L2 技术分析 | 为趋势判断、形态识别提供原始数据 | 全部7本 |
| EMA / SMA | L2 均线分析 | 自动计算均线方向、金叉死叉 | Murphy Ch9 |
| MACD | L2 均线系统 | DIF/DEA 交叉、柱状图背离检测 | Murphy Ch9 |
| 布林带 | L2 均线系统 | 波动率通道、带宽收缩预警 | Murphy Ch9 |
| RSI | L2 摆动指数 | 超买超卖 + 背离检测 | Murphy Ch10 |
| 随机指标 | L2 摆动指数 | 快慢线交叉和超买超卖 | Murphy Ch10 |
| ATR | L4 风险管理 | 仓位计算、动态止损 | Faith Ch8, Clenow Ch3 |
| ADX | L2 趋势分析 | 判断市场有无趋势（>25=有趋势） | Murphy Ch4 |
| Supertrend | L3 趋势跟踪 | 天然的顺势止损线 | Clenow, Faith |
| 一目均衡表 | L2 日式技术 | 日本综合指标：云层、基准线、转换线 | Nison Ch5 |
| 分形 | L2 波浪理论 | 自动检测局部高低点，辅助数浪 | Elliott |
| Heikin-Ashi | L2 K线分析 | 平滑噪音的趋势蜡烛 | Nison |
| 差异指数 | L2 日式技术 | 日式超买超卖指标 | Nison Ch5 |
| 逐笔成交 | L2 交易量分析 | 细粒度成交分析 | Murphy Ch7 |
| 订单簿 | L2 支撑阻力 | 挂单墙位置，验证 S/R 强度 | Murphy Ch4 |
| 回测引擎 | L3 交易系统 + L4 | 策略历史表现检验 | Faith Ch10-12 |
| K-Means S/R | L2 支撑阻力 | 聚类算法自动发现关键价位 | Murphy Ch4, Faith Ch6 |
| CSV 导入导出 | 全层 | 数据持久化 | — |
| PostgreSQL/TimescaleDB | 全层 | 历史数据仓库 | — |

## 脚本流水线

```
fetch_klines.py          → 拉取原始 OHLCV 数据
compute_indicators.py    → 批量计算全部指标
detect_setup.py          → 扫描 K 线形态 + 趋势 + 指标信号
backtest_system.py       → 回测 Clenow / Turtle 策略
analyze_portfolio.py     → 多品种仓位计算 + 相关性检测
plot_analysis.py         → 生成分析图表
```

### 典型用法

```bash
# 1. 拉取数据
python scripts/fetch_klines.py BTCUSDT 1d 200 -o btc.csv

# 2. 计算指标
python scripts/compute_indicators.py btc.csv -o btc_indicators.csv

# 3. 扫描信号
python scripts/detect_setup.py btc_indicators.csv

# 4. 回测策略
python scripts/backtest_system.py btc_indicators.csv --strategy both

# 5. 多品种组合分析
python scripts/analyze_portfolio.py --symbols BTCUSDT ETHUSDT SOLUSDT DOGEUSDT

# 6. 生成图表
python scripts/plot_analysis.py btc_indicators.csv -o btc_chart.html
```

## SKILL.md 数据驱动分析工作流

结合脚本和 skill 分析框架的完整流水线：

### 第一步：数据准备（L1）
```bash
python scripts/fetch_klines.py SYMBOL INTERVAL LIMIT -o data.csv
python scripts/compute_indicators.py data.csv -o indicators.csv
```

### 第二步：信号扫描（L2）
```bash
python scripts/detect_setup.py indicators.csv
```
读取输出的信号列表，逐个审视：
- 是否有趋势工具（均线/ADX/Supertrend）确认趋势方向？
- K线形态是否出现在关键位置（支撑/阻力/菲波纳奇回撤位）？
- 摆动指数（RSI/随机）是否配合（顺势使用黄金法则）？
- 交易量是否验证？
- **至少两个工具给出同向信号才视为有效信号**

### 第三步：制定交易计划（L3 + L4）
对于每个有效信号：
1. 入场点：信号确认的下一根K线开盘
2. 止损：形态关键位外侧 / ATR 倍数 / 固定百分比
3. 目标：前高前低 / 菲波纳奇扩展 / 形态测算目标
4. 仓位：ATR 仓位公式 `合约数 = 账户 × 风险因子 / (ATR × 点价)`
5. 盈亏比 ≥ 2:1 才执行

### 第四步：回测验证（L3 + L4）
```bash
python scripts/backtest_system.py indicators.csv --strategy both
```
检查：
- Win rate (预期 30-42%, Clenow)
- Profit factor (>1.5 为佳)
- Max DD (是否在心理承受范围内，Douglas)
- MAR ratio (Faith)
- Return skew (>0 = 厚尾右偏 = 趋势跟踪特征, Clenow)

### 第五步：组合分析（L4）
```bash
python scripts/analyze_portfolio.py --symbols ... --account 100000
```
检查：
- 各品种仓位是否按波动率均衡
- 高相关性品种是否已限制总仓位（Faith: ≤6 单位）
- 单方向总仓位是否超限（Faith: ≤12 单位）
- 总风险暴露占账户比例是否合理

### 第六步：心理检查（L5）
- 是否完全接受这笔交易可能亏损？（Douglas）
- 是否会在连续亏损后坚持系统？（Faith: 可能连续亏 17 笔）
- 是否有"这笔肯定赚钱"的幻想？（Douglas: 幻想状态）
- 止损设好了吗？（五本书共识）

## 注意事项

1. **数据源限于加密货币**：binpan 只支持 Binance，不含股票/期货。传统市场的分析需要其他数据源（yfinance, IB API 等）。
2. **回测引擎简化**：binpan 的回测不支持滑点模拟、展期处理等 Clenow 强调的实盘细节。对于严格回测建议使用 backtrader 或自建。
3. **API Key 非必须**：公开行情数据不需要 Binance API Key。只有账户相关功能才需要。
4. **Colab 不可用**：Binance API 对 Google Colab IP 有限制。
5. **依赖较重**：scikit-learn, numba, psycopg2 等，首次安装需要一些时间。

## 版本

- binpan >= 0.10.2
- Python >= 3.12
