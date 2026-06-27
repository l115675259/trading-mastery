#!/usr/bin/env python3
"""Backtest trading strategies on historical data.

Corresponds to trading-mastery L3 (Trading Systems) and L4 (Risk Management).
Implements Clenow and Turtle strategies from the integrated framework.

Usage:
    python backtest_system.py data_with_indicators.csv --strategy clenow
    python backtest_system.py data_with_indicators.csv --strategy turtle --system 2
"""

import argparse
import sys

import pandas as pd
import numpy as np


# ═══════════════════════════════════════════════════════════════
# Strategy: Clenow Trend Following
# ═══════════════════════════════════════════════════════════════

def backtest_clenow(df: pd.DataFrame,
                    risk_factor: float = 0.002,
                    atr_mult: float = 3.0) -> dict:
    """Clenow trend-following strategy.

    Entry (Long): 50-EMA > 100-EMA AND close = 50-day high close
    Entry (Short): 50-EMA < 100-EMA AND close = 50-day low close
    Exit: trailing stop = highest close since entry - 3*ATR
    """
    n = len(df)
    position = 0  # 0=flat, 1=long, -1=short
    entry_price = 0.0
    highest_since_entry = 0.0
    lowest_since_entry = 0.0
    trades = []
    equity_curve = []
    equity = 1.0

    for i in range(50, n):
        close = df["Close"].iloc[i]
        atr = df.get("atr_20", pd.Series([np.nan] * n)).iloc[i]
        ema50 = df.get("ema_50", pd.Series([np.nan] * n)).iloc[i]
        ema100 = df.get("ema_100", pd.Series([np.nan] * n)).iloc[i]
        highest_50_close = df["Close"].iloc[i - 50:i].max()
        lowest_50_close = df["Close"].iloc[i - 50:i].min()

        if pd.isna(ema50) or pd.isna(ema100) or pd.isna(atr):
            equity_curve.append(equity)
            continue

        # Entry
        if position == 0:
            if ema50 > ema100 and close >= highest_50_close:
                position = 1
                entry_price = close
                highest_since_entry = close
                trades.append({
                    "entry_date": str(df.index[i]),
                    "exit_date": None,
                    "direction": "long",
                    "entry_price": entry_price,
                    "exit_price": None,
                    "return_pct": None,
                })
            elif ema50 < ema100 and close <= lowest_50_close:
                position = -1
                entry_price = close
                lowest_since_entry = close
                trades.append({
                    "entry_date": str(df.index[i]),
                    "exit_date": None,
                    "direction": "short",
                    "entry_price": entry_price,
                    "exit_price": None,
                    "return_pct": None,
                })

        # Update trailing stops
        if position == 1:
            if close > highest_since_entry:
                highest_since_entry = close
            stop = highest_since_entry - atr_mult * atr
            if close <= stop:
                ret = (close - entry_price) / entry_price
                trades[-1].update({
                    "exit_date": str(df.index[i]),
                    "exit_price": close,
                    "return_pct": ret * 100,
                })
                equity *= (1 + ret)
                position = 0

        elif position == -1:
            if close < lowest_since_entry:
                lowest_since_entry = close
            stop = lowest_since_entry + atr_mult * atr
            if close >= stop:
                ret = (entry_price - close) / entry_price
                trades[-1].update({
                    "exit_date": str(df.index[i]),
                    "exit_price": close,
                    "return_pct": ret * 100,
                })
                equity *= (1 + ret)
                position = 0

        equity_curve.append(equity)

    # Close any open position at end
    if position != 0 and trades:
        close = df["Close"].iloc[-1]
        if position == 1:
            ret = (close - entry_price) / entry_price
        else:
            ret = (entry_price - close) / entry_price
        trades[-1].update({
            "exit_date": str(df.index[-1]),
            "exit_price": close,
            "return_pct": ret * 100,
        })

    return _compute_metrics(trades, equity_curve, "Clenow")


# ═══════════════════════════════════════════════════════════════
# Strategy: Turtle (Faith)
# ═══════════════════════════════════════════════════════════════

def backtest_turtle(df: pd.DataFrame, system: int = 2) -> dict:
    """Turtle trading system.

    System 1: 20-day breakout entry, 10-day breakout exit
    System 2: 55-day breakout entry, 20-day breakout exit
    """
    entry_lookback = 20 if system == 1 else 55
    exit_lookback = 10 if system == 1 else 20

    n = len(df)
    position = 0
    entry_price = 0.0
    trades = []
    equity_curve = []
    equity = 1.0
    min_idx = max(entry_lookback, exit_lookback)

    for i in range(min_idx, n):
        close = df["Close"].iloc[i]
        entry_high = df["High"].iloc[i - entry_lookback:i].max()
        entry_low = df["Low"].iloc[i - entry_lookback:i].min()
        exit_high = df["High"].iloc[i - exit_lookback:i].max()
        exit_low = df["Low"].iloc[i - exit_lookback:i].min()

        if position == 0:
            if close >= entry_high:
                position = 1
                entry_price = close
                trades.append({
                    "entry_date": str(df.index[i]),
                    "exit_date": None,
                    "direction": "long",
                    "entry_price": entry_price,
                    "exit_price": None,
                    "return_pct": None,
                })
            elif close <= entry_low:
                position = -1
                entry_price = close
                trades.append({
                    "entry_date": str(df.index[i]),
                    "exit_date": None,
                    "direction": "short",
                    "entry_price": entry_price,
                    "exit_price": None,
                    "return_pct": None,
                })

        else:
            if position == 1 and close <= exit_low:
                ret = (close - entry_price) / entry_price
                trades[-1].update({
                    "exit_date": str(df.index[i]),
                    "exit_price": close,
                    "return_pct": ret * 100,
                })
                equity *= (1 + ret)
                position = 0
            elif position == -1 and close >= exit_high:
                ret = (entry_price - close) / entry_price
                trades[-1].update({
                    "exit_date": str(df.index[i]),
                    "exit_price": close,
                    "return_pct": ret * 100,
                })
                equity *= (1 + ret)
                position = 0

        equity_curve.append(equity)

    label = f"Turtle S{system}"
    return _compute_metrics(trades, equity_curve, label)


# ═══════════════════════════════════════════════════════════════
# Metrics (Faith Ch7 + Clenow)
# ═══════════════════════════════════════════════════════════════

def _compute_metrics(trades: list, equity_curve: list, label: str) -> dict:
    eq = pd.Series(equity_curve)
    if len(eq) < 2:
        return {"label": label, "trades": 0, "error": "insufficient data"}

    returns = eq.pct_change().dropna()
    total_return = eq.iloc[-1] / eq.iloc[0] - 1
    n_years = len(eq) / 252
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / n_years) - 1 if n_years > 0 else 0

    # Max drawdown
    peak = eq.expanding().max()
    dd = (eq - peak) / peak
    max_dd = dd.min()

    # MAR ratio (Faith)
    mar = cagr / abs(max_dd) if max_dd != 0 else float("inf")

    # Sharpe ratio (simplified, risk-free=0)
    sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0

    # Trade statistics
    closed = [t for t in trades if t["return_pct"] is not None]
    winners = [t for t in closed if t["return_pct"] > 0]
    losers = [t for t in closed if t["return_pct"] <= 0]
    win_rate = len(winners) / len(closed) * 100 if closed else 0
    avg_win = np.mean([t["return_pct"] for t in winners]) if winners else 0
    avg_loss = np.mean([t["return_pct"] for t in losers]) if losers else 0
    profit_factor = (
        abs(sum(t["return_pct"] for t in winners) / sum(t["return_pct"] for t in losers))
        if losers and sum(t["return_pct"] for t in losers) != 0
        else float("inf")
    )

    # Return distribution skew (Clenow: thick tail right-skew)
    returns_list = [t["return_pct"] for t in closed]
    skew = float(pd.Series(returns_list).skew()) if len(returns_list) >= 3 else 0

    return {
        "label": label,
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "winners": len(winners),
        "losers": len(losers),
        "win_rate_pct": round(win_rate, 1),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "mar_ratio": round(mar, 2),
        "sharpe_ratio": round(sharpe, 2),
        "return_skew": round(skew, 2),
    }


def print_metrics(metrics: dict):
    print(f"\n{'='*50}")
    print(f"  Strategy: {metrics['label']}")
    print(f"{'='*50}")
    if "error" in metrics:
        print(f"  ERROR: {metrics['error']}")
        return

    print(f"  Total Trades:     {metrics['total_trades']}")
    print(f"  Closed Trades:    {metrics['closed_trades']}")
    print(f"  Win Rate:         {metrics['win_rate_pct']}%")
    print(f"  Avg Win:          {metrics['avg_win_pct']:+.2f}%")
    print(f"  Avg Loss:         {metrics['avg_loss_pct']:+.2f}%")
    print(f"  Profit Factor:    {metrics['profit_factor']}")
    print(f"  Return Skew:      {metrics['return_skew']}  (Clenow: >0 = thick tail)")
    print(f"  ---")
    print(f"  Total Return:     {metrics['total_return_pct']:+.2f}%")
    print(f"  CAGR:             {metrics['cagr_pct']:+.2f}%")
    print(f"  Max Drawdown:     {metrics['max_drawdown_pct']:+.2f}%")
    print(f"  MAR Ratio:        {metrics['mar_ratio']}")
    print(f"  Sharpe Ratio:     {metrics['sharpe_ratio']}")


def main():
    parser = argparse.ArgumentParser(
        description="Backtest trading strategies from the integrated framework"
    )
    parser.add_argument("input", help="CSV with OHLCV + indicators")
    parser.add_argument("--strategy", "-s", default="clenow",
                        choices=["clenow", "turtle", "both"],
                        help="Strategy to test (default: clenow)")
    parser.add_argument("--system", type=int, default=2,
                        choices=[1, 2], help="Turtle system (1 or 2, default: 2)")
    parser.add_argument("--risk", type=float, default=0.002,
                        help="Clenow risk factor (default: 0.002)")
    args = parser.parse_args()

    df = pd.read_csv(args.input, index_col=0, parse_dates=True)
    print(f"Data: {len(df)} rows, {df.index[0]} to {df.index[-1]}", file=sys.stderr)

    if args.strategy in ("clenow", "both"):
        m = backtest_clenow(df, risk_factor=args.risk)
        print_metrics(m)

    if args.strategy in ("turtle", "both"):
        m = backtest_turtle(df, system=args.system)
        print_metrics(m)


if __name__ == "__main__":
    main()
