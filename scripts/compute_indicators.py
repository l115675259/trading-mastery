#!/usr/bin/env python3
"""Compute technical indicators on OHLCV data.

Corresponds to trading-mastery L2 (Technical Analysis).
Each indicator is annotated with the source book and chapter.

Usage:
    python compute_indicators.py data.csv
    python compute_indicators.py data.csv --ema 21 50 --rsi 14 --macd
"""

import argparse
import sys

import pandas as pd
import numpy as np


# ── Helper ──────────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def _tr(df: pd.DataFrame) -> pd.Series:
    """True Range — Murphy Ch4, Faith Ch8, Nison Ch2."""
    prev_close = df["Close"].shift(1)
    h_l = df["High"] - df["Low"]
    h_c = (df["High"] - prev_close).abs()
    l_c = (df["Low"] - prev_close).abs()
    return pd.concat([h_l, h_c, l_c], axis=1).max(axis=1)


# ── Indicators ──────────────────────────────────────────────

def add_sma(df: pd.DataFrame, periods: list[int]) -> pd.DataFrame:
    """Simple Moving Average — Murphy Ch9."""
    for p in periods:
        df[f"sma_{p}"] = _sma(df["Close"], p)
    return df


def add_ema(df: pd.DataFrame, periods: list[int]) -> pd.DataFrame:
    """Exponential Moving Average — Murphy Ch9."""
    for p in periods:
        df[f"ema_{p}"] = _ema(df["Close"], p)
    return df


def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26,
             signal: int = 9) -> pd.DataFrame:
    """MACD — Murphy Ch9."""
    ema_fast = _ema(df["Close"], fast)
    ema_slow = _ema(df["Close"], slow)
    df["macd_dif"] = ema_fast - ema_slow
    df["macd_dea"] = _ema(df["macd_dif"], signal)
    df["macd_hist"] = 2 * (df["macd_dif"] - df["macd_dea"])
    return df


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """RSI — Murphy Ch10."""
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = _ema(gain, period)
    avg_loss = _ema(loss, period)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df[f"rsi_{period}"] = 100 - (100 / (1 + rs))
    return df


def add_stochastic(df: pd.DataFrame, k_period: int = 14,
                   d_period: int = 3) -> pd.DataFrame:
    """Stochastic %K / %D — Murphy Ch10, Nison Ch5."""
    low_min = df["Low"].rolling(k_period).min()
    high_max = df["High"].rolling(k_period).max()
    df["stoch_k"] = 100 * (df["Close"] - low_min) / (high_max - low_min)
    df["stoch_d"] = _sma(df["stoch_k"], d_period)
    return df


def add_atr(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Average True Range — Faith Ch8, Clenow Ch3.

    N in Turtle terminology = ATR(20).
    """
    df["tr"] = _tr(df)
    df[f"atr_{period}"] = _ema(df["tr"], period)
    return df


def add_bollinger(df: pd.DataFrame, period: int = 20,
                  std: float = 2.0) -> pd.DataFrame:
    """Bollinger Bands — Murphy Ch9."""
    mid = _sma(df["Close"], period)
    sd = df["Close"].rolling(period).std()
    df["bb_mid"] = mid
    df["bb_upper"] = mid + std * sd
    df["bb_lower"] = mid - std * sd
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    return df


def add_supertrend(df: pd.DataFrame, period: int = 10,
                   multiplier: float = 3.0) -> pd.DataFrame:
    """Supertrend — Clenow/Faith trend-following indicator.

    Based on ATR; acts as a dynamic trailing stop.
    """
    atr = _ema(_tr(df), period)
    hl2 = (df["High"] + df["Low"]) / 2

    # Basic bands
    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr

    # Initialize series
    upper = pd.Series(np.nan, index=df.index)
    lower = pd.Series(np.nan, index=df.index)
    trend = pd.Series(1, index=df.index)  # 1 = up, -1 = down

    upper.iloc[0] = upper_basic.iloc[0]
    lower.iloc[0] = lower_basic.iloc[0]

    for i in range(1, len(df)):
        # Upper band
        if upper_basic.iloc[i] < upper.iloc[i - 1] or df["Close"].iloc[i - 1] > upper.iloc[i - 1]:
            upper.iloc[i] = upper_basic.iloc[i]
        else:
            upper.iloc[i] = upper.iloc[i - 1]

        # Lower band
        if lower_basic.iloc[i] > lower.iloc[i - 1] or df["Close"].iloc[i - 1] < lower.iloc[i - 1]:
            lower.iloc[i] = lower_basic.iloc[i]
        else:
            lower.iloc[i] = lower.iloc[i - 1]

        # Trend
        if df["Close"].iloc[i] > upper.iloc[i - 1]:
            trend.iloc[i] = 1
        elif df["Close"].iloc[i] < lower.iloc[i - 1]:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i - 1]

    df["st_value"] = np.where(trend == 1, lower, upper)
    df["st_trend"] = trend
    return df


def add_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Heikin-Ashi candles — Nison (smoother trend candles)."""
    df["ha_close"] = (df["Open"] + df["High"] + df["Low"] + df["Close"]) / 4
    ha_open = pd.Series(np.nan, index=df.index)
    ha_open.iloc[0] = (df["Open"].iloc[0] + df["Close"].iloc[0]) / 2
    for i in range(1, len(df)):
        ha_open.iloc[i] = (ha_open.iloc[i - 1] + df["ha_close"].iloc[i - 1]) / 2
    df["ha_open"] = ha_open
    df["ha_high"] = df[["High", "ha_open", "ha_close"]].max(axis=1)
    df["ha_low"] = df[["Low", "ha_open", "ha_close"]].min(axis=1)
    return df


def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Average Directional Index — Murphy Ch4 (trend strength)."""
    tr = _tr(df)
    up = df["High"].diff()
    down = -df["Low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0)
    minus_dm = np.where((down > up) & (down > 0), down, 0)
    atr = _ema(tr, period)
    plus_di = 100 * _ema(pd.Series(plus_dm, index=df.index), period) / atr
    minus_di = 100 * _ema(pd.Series(minus_dm, index=df.index), period) / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    df["adx"] = _ema(dx, period)
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di
    return df


def add_ichimoku(df: pd.DataFrame) -> pd.DataFrame:
    """Ichimoku Cloud — Nison Ch5 (Japanese integrated indicator)."""
    high_9 = df["High"].rolling(9).max()
    low_9 = df["Low"].rolling(9).min()
    high_26 = df["High"].rolling(26).max()
    low_26 = df["Low"].rolling(26).min()
    high_52 = df["High"].rolling(52).max()
    low_52 = df["Low"].rolling(52).min()

    df["ichimoku_tenkan"] = (high_9 + low_9) / 2
    df["ichimoku_kijun"] = (high_26 + low_26) / 2
    df["ichimoku_senkou_a"] = ((df["ichimoku_tenkan"] + df["ichimoku_kijun"]) / 2).shift(26)
    df["ichimoku_senkou_b"] = ((high_52 + low_52) / 2).shift(26)
    df["ichimoku_chikou"] = df["Close"].shift(-26)
    return df


def add_difference_index(df: pd.DataFrame, period: int = 25) -> pd.DataFrame:
    """Difference Index — Nison Ch5 (Japanese oscillator).

    DI = (close - MA) / MA * 100
    Used for overbought/oversold and divergence detection.
    """
    ma = _sma(df["Close"], period)
    df[f"diff_idx_{period}"] = (df["Close"] - ma) / ma * 100
    return df


# ── ALL ─────────────────────────────────────────────────────

def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Compute a comprehensive indicator suite on the DataFrame."""
    df = df.copy()

    # Murphy Ch9: Moving averages
    df = add_sma(df, [20, 50, 100, 200])
    df = add_ema(df, [12, 26, 50, 100])
    df = add_macd(df)
    df = add_bollinger(df)

    # Murphy Ch10: Oscillators
    df = add_rsi(df, 14)
    df = add_stochastic(df)

    # Murphy Ch4 / Faith Ch8: ATR & ADX
    df = add_atr(df, 20)
    df = add_adx(df, 14)

    # Clenow / Faith: Supertrend
    df = add_supertrend(df, 10, 3.0)

    # Nison: Ichimoku & Heikin-Ashi
    df = add_ichimoku(df)
    df = add_heikin_ashi(df)

    # Nison: Difference Index
    df = add_difference_index(df, 25)

    return df


# ── CLI ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Compute technical indicators for trading analysis"
    )
    parser.add_argument("input", help="CSV file with OHLCV data")
    parser.add_argument("--output", "-o", help="Output CSV path")
    parser.add_argument("--all", action="store_true", default=True,
                        help="Compute all indicators (default)")
    args = parser.parse_args()

    df = pd.read_csv(args.input, index_col=0, parse_dates=True)
    print(f"Input: {len(df)} rows, columns: {list(df.columns)}", file=sys.stderr)

    result = compute_all(df)
    print(f"Output: {len(result.columns)} columns", file=sys.stderr)

    if args.output:
        result.to_csv(args.output)
        print(f"Saved to {args.output}")
    else:
        # Print last 10 rows of key columns
        key_cols = ["Close", "ema_50", "ema_100", "rsi_14", "atr_20", "st_trend"]
        available = [c for c in key_cols if c in result.columns]
        print(result[available].tail(10).to_string())


if __name__ == "__main__":
    main()
