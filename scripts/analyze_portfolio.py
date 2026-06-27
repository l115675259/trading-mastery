#!/usr/bin/env python3
"""Multi-symbol portfolio analysis.

Corresponds to trading-mastery L4 (Risk Management).
Implements ATR-based position sizing (Clenow/Faith), correlation analysis,
and sector exposure tracking.

Usage:
    python analyze_portfolio.py --symbols BTCUSDT ETHUSDT SOLUSDT --interval 1d
    python analyze_portfolio.py --from-csv btc.csv eth.csv sol.csv
"""

import argparse
import sys

import pandas as pd
import numpy as np
import binpan


def fetch_and_compute(symbols: list[str], interval: str = "1d",
                      limit: int = 200, tz: str = "UTC") -> dict[str, pd.DataFrame]:
    """Fetch multiple symbols and compute ATR for each."""
    results = {}
    for sym in symbols:
        try:
            s = binpan.Symbol(
                symbol=sym.lower(),
                tick_interval=interval,
                time_zone=tz,
                limit=limit,
            )
            df = s.klines
            if df is None or df.empty:
                print(f"  [SKIP] {sym}: no data", file=sys.stderr)
                continue

            # Compute ATR
            prev_close = df["Close"].shift(1)
            tr = pd.concat([
                df["High"] - df["Low"],
                (df["High"] - prev_close).abs(),
                (df["Low"] - prev_close).abs(),
            ], axis=1).max(axis=1)
            df["atr_20"] = tr.ewm(span=20, adjust=False).mean()

            results[sym] = df
            print(f"  [OK] {sym}: {len(df)} candles, "
                  f"ATR={df['atr_20'].iloc[-1]:.2f}",
                  file=sys.stderr)
        except Exception as e:
            print(f"  [FAIL] {sym}: {e}", file=sys.stderr)

    return results


# ═══════════════════════════════════════════════════════════════
# Position sizing (Clenow / Faith)
# ═══════════════════════════════════════════════════════════════

def compute_position_sizes(
    data: dict[str, pd.DataFrame],
    account_value: float = 1_000_000,
    risk_per_unit: float = 0.01,  # Turtle: 1% per unit
    max_units_per_market: int = 4,
    max_correlated_units: int = 6,
    max_total_units: int = 12,
) -> pd.DataFrame:
    """Compute position sizes for a portfolio.

    Based on Faith Ch8 (Turtle position sizing) and Clenow Ch3 (ATR formula).
    """
    rows = []
    for sym, df in data.items():
        close = df["Close"].iloc[-1]
        atr = df["atr_20"].iloc[-1]
        if pd.isna(atr) or atr <= 0:
            continue

        # Dollar volatility per contract (approx — use close as proxy for point value)
        dollar_vol = atr  # For crypto, ATR in quote currency is the $ vol per unit

        # Turtle: units = account * 1% / (N * point_value)
        units = account_value * risk_per_unit / dollar_vol
        units_limited = min(units, max_units_per_market)

        rows.append({
            "symbol": sym,
            "price": round(close, 2),
            "atr_20": round(atr, 2),
            "atr_pct": round(atr / close * 100, 2),
            "raw_units": round(units, 4),
            "limited_units": round(units_limited, 4),
            "position_value": round(units_limited * close, 0),
            "daily_risk": round(units_limited * atr, 0),
            "risk_pct": round(units_limited * atr / account_value * 100, 2),
        })

    result = pd.DataFrame(rows)
    if not result.empty:
        result["pct_of_account"] = (
            result["position_value"] / account_value * 100
        ).round(1)
    return result


# ═══════════════════════════════════════════════════════════════
# Correlation analysis (Clenow Ch4 / Faith)
# ═══════════════════════════════════════════════════════════════

def compute_correlation(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compute returns correlation matrix.

    High correlation (>0.7) between symbols warns of false diversification.
    """
    returns = {}
    for sym, df in data.items():
        r = df["Close"].pct_change().dropna()
        returns[sym] = r

    if len(returns) < 2:
        return pd.DataFrame()

    corr_df = pd.DataFrame(returns).corr()
    return corr_df


def flag_high_correlation(corr: pd.DataFrame, threshold: float = 0.7) -> list[str]:
    """Flag pairs with correlation above threshold."""
    warnings = []
    if corr.empty:
        return warnings
    pairs = set()
    for i in range(len(corr.columns)):
        for j in range(i + 1, len(corr.columns)):
            val = corr.iloc[i, j]
            if abs(val) >= threshold:
                pair = tuple(sorted([corr.columns[i], corr.columns[j]]))
                if pair not in pairs:
                    pairs.add(pair)
                    warnings.append(
                        f"  HIGH CORRELATION: {pair[0]} <-> {pair[1]} = {val:.3f}  "
                        f"(> {threshold}) — verify position limits (Faith: max 6 units)"
                    )
    return warnings


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Multi-symbol portfolio analysis with ATR position sizing"
    )
    parser.add_argument("--symbols", nargs="+",
                        default=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
                        help="Symbols to analyze (default: BTC ETH SOL)")
    parser.add_argument("--interval", default="1d",
                        help="Kline interval (default: 1d)")
    parser.add_argument("--limit", type=int, default=200,
                        help="Candles per symbol (default: 200)")
    parser.add_argument("--account", type=float, default=100000,
                        help="Account value in USD (default: 100000)")
    parser.add_argument("--risk", type=float, default=0.01,
                        help="Risk per unit as fraction (default: 0.01)")
    args = parser.parse_args()

    print("Fetching data...", file=sys.stderr)
    data = fetch_and_compute(args.symbols, args.interval, args.limit)

    if not data:
        print("No data fetched.", file=sys.stderr)
        return

    # Position sizing
    print("\n=== Position Sizing (Turtle/Clenow ATR method) ===")
    positions = compute_position_sizes(
        data,
        account_value=args.account,
        risk_per_unit=args.risk,
    )
    print(positions.to_string(index=False))

    total_risk = positions["daily_risk"].sum() if not positions.empty else 0
    total_value = positions["position_value"].sum() if not positions.empty else 0
    print(f"\nTotal position value: ${total_value:,.0f} "
          f"({total_value/args.account*100:.1f}% of account)")
    print(f"Total daily risk:     ${total_risk:,.0f} "
          f"({total_risk/args.account*100:.2f}% of account)")
    print(f"    (Faith: aim for ~1% daily risk per unit, "
          f"max {4 * len(data)} total units)")

    # Correlation
    print("\n=== Correlation Matrix ===")
    corr = compute_correlation(data)
    if not corr.empty:
        print(corr.round(3).to_string())
        warnings = flag_high_correlation(corr)
        if warnings:
            print("\n  !! Correlation Warnings (Faith: check position limits):")
            for w in warnings:
                print(w)
        else:
            print("\n  No high correlation pairs detected.")
    else:
        print("  (need at least 2 symbols)")


if __name__ == "__main__":
    main()
