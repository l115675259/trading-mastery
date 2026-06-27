#!/usr/bin/env python3
"""Fetch OHLCV (kline) data from Binance via binpan.

Corresponds to trading-mastery L1 (Market Understanding) and L2 (Technical Analysis).
Provides the raw data that all subsequent analysis layers consume.

Usage:
    python fetch_klines.py BTCUSDT 1d 200
    python fetch_klines.py ETHUSDT 4h 500 --output eth_4h.csv
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import binpan


def fetch(symbol: str, interval: str = "1d", limit: int = 200,
          tz: str = "UTC") -> pd.DataFrame:
    """Fetch kline data and return a clean DataFrame.

    Args:
        symbol: Trading pair, e.g. 'BTCUSDT', 'ETHUSDT'.
        interval: Kline interval: 1m, 5m, 15m, 1h, 4h, 1d, 1w, 1M.
        limit: Number of candles to fetch (max ~1000).
        tz: Timezone string, e.g. 'UTC', 'Asia/Shanghai'.

    Returns:
        DataFrame with columns: open, high, low, close, volume,
        close_time, quote_volume, trades, taker_buy_base, taker_buy_quote.
        Index is DatetimeIndex in requested timezone.
    """
    sym = binpan.Symbol(
        symbol=symbol.lower(),
        tick_interval=interval,
        time_zone=tz,
        limit=limit,
    )
    df = sym.df  # binpan property that returns the kline DataFrame

    if df is None or df.empty:
        raise RuntimeError(f"No data returned for {symbol} {interval}")

    # Ensure standard column names
    expected_cols = [
        "Open", "High", "Low", "Close", "Volume",
        "Close time", "Quote volume", "Trades",
        "Taker buy base volume", "Taker buy quote volume",
    ]
    for c in expected_cols:
        if c not in df.columns:
            df[c] = None

    return df[expected_cols]


def fetch_multi(symbols: list[str], interval: str = "1d",
                limit: int = 200, tz: str = "UTC") -> dict[str, pd.DataFrame]:
    """Fetch multiple symbols at once.

    Returns:
        Dict mapping symbol -> DataFrame.
    """
    results = {}
    for sym in symbols:
        try:
            results[sym] = fetch(sym, interval, limit, tz)
            print(f"  [OK] {sym}: {len(results[sym])} candles", file=sys.stderr)
        except Exception as e:
            print(f"  [FAIL] {sym}: {e}", file=sys.stderr)
    return results


def main():
    parser = argparse.ArgumentParser(description="Fetch Binance kline data")
    parser.add_argument("symbol", help="Trading pair, e.g. BTCUSDT")
    parser.add_argument("interval", nargs="?", default="1d",
                        help="Kline interval (default: 1d)")
    parser.add_argument("limit", nargs="?", type=int, default=200,
                        help="Number of candles (default: 200)")
    parser.add_argument("--tz", default="UTC", help="Timezone (default: UTC)")
    parser.add_argument("--output", "-o", help="Save to CSV file")
    parser.add_argument("--multi", nargs="*",
                        help="Fetch multiple symbols instead")
    args = parser.parse_args()

    if args.multi:
        results = fetch_multi(args.multi, args.interval, args.limit, args.tz)
        if args.output:
            for sym, df in results.items():
                out = Path(args.output).with_stem(
                    f"{Path(args.output).stem}_{sym}"
                )
                df.to_csv(out)
                print(f"Saved {sym} -> {out}")
        else:
            for sym, df in results.items():
                print(f"\n=== {sym} ===")
                print(df.tail(5).to_string())
    else:
        df = fetch(args.symbol, args.interval, args.limit, args.tz)
        if args.output:
            df.to_csv(args.output)
            print(f"Saved to {args.output}")
        else:
            print(df.tail(20).to_string())


if __name__ == "__main__":
    main()
