#!/usr/bin/env python3
"""
回测引擎 — 纯交易模拟 + 统计
================================
不做任何分析判断。只负责：
1. 接收信号（来自 LLM 分析）
2. 模拟交易执行（入场/止损/止盈/到期）
3. 统计胜率、盈亏比、回报等

信号格式（来自 LLM 分析）：
{
  "bar_index": int,           # K线序数
  "date": str,                # 日期
  "entry_price": float,       # 入场价
  "direction": "LONG"/"SHORT",
  "stop_loss": float,         # 止损价
  "take_profit": float,       # 止盈价
  "confidence": int,          # 质量分 0-100
  "hold_bars": int,           # 最大持仓K线数（0=无限制）
  "coin": str,                # 币种
}
"""

import numpy as np
import pandas as pd
import json
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class TradeResult:
    """单笔交易结果"""
    coin: str = ""
    entry_bar: int = 0
    entry_date: str = ""
    entry_price: float = 0.0
    exit_bar: int = 0
    exit_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    direction: str = ""
    return_pct: float = 0.0
    confidence: int = 0
    hold_bars: int = 0


class BacktestEngine:
    """纯回测模拟引擎"""

    def __init__(self, account: float = 5000.0, position_size: float = 300.0,
                 leverage: float = 3.0):
        self.account = account
        self.position_size = position_size
        self.margin = position_size / leverage
        self.leverage = leverage

    def run(self, df: pd.DataFrame, signals: List[Dict],
            tp_pct: float = 5.0, sl_pct: float = 3.0,
            max_hold_bars: int = 5) -> List[TradeResult]:
        """在给定的 DataFrame 上按信号模拟交易。"""
        trades = []
        active_trade: Optional[Dict] = None

        for i in range(len(df)):
            high = df["high"].iloc[i]
            low = df["low"].iloc[i]
            close = df["close"].iloc[i]
            date_str = str(df.index[i])

            # 检查持仓退出
            if active_trade:
                at = active_trade
                held = i - at["entry_bar"]
                hold_limit = at.get("hold_bars", max_hold_bars)
                exit_price = None
                exit_reason = ""

                if at["direction"] == "SHORT":
                    if low <= at["take_profit"]:
                        exit_price = at["take_profit"]; exit_reason = "TP"
                    elif high >= at["stop_loss"]:
                        exit_price = at["stop_loss"]; exit_reason = "SL"
                    elif hold_limit > 0 and held >= hold_limit:
                        exit_price = close; exit_reason = "timeout"
                else:  # LONG
                    if high >= at["take_profit"]:
                        exit_price = at["take_profit"]; exit_reason = "TP"
                    elif low <= at["stop_loss"]:
                        exit_price = at["stop_loss"]; exit_reason = "SL"
                    elif hold_limit > 0 and held >= hold_limit:
                        exit_price = close; exit_reason = "timeout"

                if exit_price is not None:
                    ret = ((at["entry_price"] - exit_price) / at["entry_price"] * 100
                           if at["direction"] == "SHORT"
                           else (exit_price - at["entry_price"]) / at["entry_price"] * 100)
                    trades.append(TradeResult(
                        coin=at.get("coin", "?"), entry_bar=at["entry_bar"],
                        entry_date=at["entry_date"], entry_price=at["entry_price"],
                        exit_bar=i, exit_date=date_str, exit_price=exit_price,
                        exit_reason=exit_reason, direction=at["direction"],
                        return_pct=ret, confidence=at.get("confidence", 0),
                        hold_bars=held))
                    active_trade = None

            # 检查新信号入场
            if active_trade is None:
                sig = next((s for s in signals if s.get("bar_index") == i), None)
                if sig:
                    active_trade = {
                        "entry_bar": i, "entry_date": date_str,
                        "entry_price": sig["entry_price"],
                        "direction": sig["direction"],
                        "take_profit": sig["take_profit"],
                        "stop_loss": sig["stop_loss"],
                        "coin": sig.get("coin", "?"),
                        "confidence": sig.get("confidence", 0),
                        "hold_bars": sig.get("hold_bars", max_hold_bars),
                    }

        # 数据末尾仍有持仓
        if active_trade:
            at = active_trade
            last_close = df["close"].iloc[-1]
            ret = ((at["entry_price"] - last_close) / at["entry_price"] * 100
                   if at["direction"] == "SHORT"
                   else (last_close - at["entry_price"]) / at["entry_price"] * 100)
            trades.append(TradeResult(
                coin=at.get("coin", "?"), entry_bar=at["entry_bar"],
                entry_date=at["entry_date"], entry_price=at["entry_price"],
                exit_bar=len(df) - 1, exit_date=str(df.index[-1]),
                exit_price=last_close, exit_reason="end_of_data",
                direction=at["direction"], return_pct=ret,
                confidence=at.get("confidence", 0),
                hold_bars=len(df) - at["entry_bar"]))

        return trades

    @staticmethod
    def stats(trades: List[TradeResult]) -> dict:
        """计算回测统计指标"""
        if not trades:
            return {"trades": 0, "wr": 0, "pf": 0, "total_return": 0,
                    "avg_return": 0, "best": 0, "worst": 0, "max_dd": 0}

        returns = [t.return_pct for t in trades]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]

        wr = len(wins) / len(returns) * 100
        total_win = sum(wins) if wins else 0
        total_loss = abs(sum(losses)) if losses else 1
        pf = total_win / total_loss if total_loss > 0 else 999

        cum = np.cumsum(returns)
        peak = np.maximum.accumulate(cum)
        max_dd = float(abs((cum - peak).min())) if len(cum) > 0 else 0.0

        avg_r = np.mean(returns)
        std_r = np.std(returns) if len(returns) > 1 else 1
        n = min(len(trades), 252)
        sharpe = (avg_r / std_r) * np.sqrt(n) if std_r > 0 else 0

        exit_dist = {}
        for t in trades:
            exit_dist[t.exit_reason] = exit_dist.get(t.exit_reason, 0) + 1

        return {
            "trades": len(trades), "wr": round(wr, 1), "pf": round(pf, 2),
            "sharpe": round(sharpe, 2), "total_return": round(sum(returns), 2),
            "avg_return": round(avg_r, 2), "best": round(max(returns), 2),
            "worst": round(min(returns), 2), "max_dd": round(max_dd, 2),
            "exit_distribution": exit_dist,
        }

    @staticmethod
    def account_summary(trades: List[TradeResult], initial: float = 5000.0,
                        position_size: float = 300.0) -> dict:
        """账户级别的回测汇总"""
        s = BacktestEngine.stats(trades)
        gain = sum(t.return_pct for t in trades)
        final = initial + gain / 100 * position_size
        return {
            **s,
            "initial_account": initial,
            "final_account": round(final, 0),
            "total_profit": round(final - initial, 0),
            "roi_pct": round((final - initial) / initial * 100, 2),
        }
