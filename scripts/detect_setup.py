#!/usr/bin/env python3
"""Detect trading setups by scanning candlestick patterns, trend conditions,
and indicator signals.

Corresponds to trading-mastery L2 (Technical Analysis, Nison/Murphy/Elliott)
and L3 (Trading Systems, Clenow/Faith).

Usage:
    python detect_setup.py data_with_indicators.csv
"""

import argparse
import sys

import pandas as pd
import numpy as np


# ═══════════════════════════════════════════════════════════════
# Candlestick pattern detection (Nison)
# ═══════════════════════════════════════════════════════════════

def _body(df: pd.DataFrame) -> pd.Series:
    return (df["Close"] - df["Open"]).abs()


def _upper_shadow(df: pd.DataFrame) -> pd.Series:
    return df["High"] - df[["Open", "Close"]].max(axis=1)


def _lower_shadow(df: pd.DataFrame) -> pd.Series:
    return df[["Open", "Close"]].min(axis=1) - df["Low"]


def is_long_body(df: pd.DataFrame, i: int, multiplier: float = 3.0) -> bool:
    """Long body = body >= 3x average body of prior candles — Nison Ch2."""
    if i < 10:
        return False
    avg_body = _body(df).iloc[i - 10:i].mean()
    return _body(df).iloc[i] >= avg_body * multiplier


def detect_hammer(df: pd.DataFrame, i: int) -> bool:
    """Hammer: small body at top, long lower shadow >= 3x body, tiny upper shadow — Nison Ch3."""
    if i < 5:
        return False
    body = _body(df).iloc[i]
    if body == 0:
        body = abs(df["Close"].iloc[i] - df["Open"].iloc[i])
    if body < 1e-8:
        return False
    lower = _lower_shadow(df).iloc[i]
    upper = _upper_shadow(df).iloc[i]
    body_upper = df[["Open", "Close"]].max(axis=1).iloc[i]
    body_lower = df[["Open", "Close"]].min(axis=1).iloc[i]
    body_center = (body_upper + body_lower) / 2
    bar_range = df["High"].iloc[i] - df["Low"].iloc[i]
    if bar_range == 0:
        return False
    # Body in upper third
    if body_lower < body_center:
        return False
    # Lower shadow >= 3x body
    if lower < body * 3:
        return False
    # Upper shadow very small
    if upper > body * 0.5:
        return False
    # Must appear after a decline
    recent = df["Close"].iloc[max(0, i - 5):i]
    if len(recent) < 3:
        return False
    return recent.iloc[-1] < recent.iloc[0]


def detect_shooting_star(df: pd.DataFrame, i: int) -> bool:
    """Shooting Star: small body at bottom, long upper shadow >= 3x — Nison Ch3."""
    if i < 5:
        return False
    body = _body(df).iloc[i]
    if body < 1e-8:
        return False
    upper = _upper_shadow(df).iloc[i]
    lower = _lower_shadow(df).iloc[i]
    body_upper = df[["Open", "Close"]].max(axis=1).iloc[i]
    body_lower = df[["Open", "Close"]].min(axis=1).iloc[i]
    body_center = (body_upper + body_lower) / 2
    # Body in lower third
    if body_upper > body_center:
        return False
    if upper < body * 3:
        return False
    if lower > body * 0.5:
        return False
    # Must appear after a rally
    recent = df["Close"].iloc[max(0, i - 5):i]
    return recent.iloc[-1] > recent.iloc[0]


def detect_doji(df: pd.DataFrame, i: int) -> bool:
    """Doji: open == close (or extremely tiny body) — Nison Ch2."""
    body = _body(df).iloc[i]
    bar_range = df["High"].iloc[i] - df["Low"].iloc[i]
    if bar_range == 0:
        return True
    return body / bar_range < 0.05


def detect_engulfing_bullish(df: pd.DataFrame, i: int) -> bool:
    """Bullish Engulfing — Nison Ch3."""
    if i < 1:
        return False
    prev_open, prev_close = df["Open"].iloc[i - 1], df["Close"].iloc[i - 1]
    curr_open, curr_close = df["Open"].iloc[i], df["Close"].iloc[i]
    prev_red = prev_close < prev_open
    curr_green = curr_close > curr_open
    if not (prev_red and curr_green):
        return False
    return curr_open <= prev_close and curr_close >= prev_open


def detect_engulfing_bearish(df: pd.DataFrame, i: int) -> bool:
    """Bearish Engulfing — Nison Ch3."""
    if i < 1:
        return False
    prev_open, prev_close = df["Open"].iloc[i - 1], df["Close"].iloc[i - 1]
    curr_open, curr_close = df["Open"].iloc[i], df["Close"].iloc[i]
    prev_green = prev_close > prev_open
    curr_red = curr_close < curr_open
    if not (prev_green and curr_red):
        return False
    return curr_open >= prev_close and curr_close <= prev_open


def detect_harami(df: pd.DataFrame, i: int) -> bool:
    """Harami (pregnant) pattern — Nison Ch3."""
    if i < 1:
        return False
    prev_body = _body(df).iloc[i - 1]
    curr_body = _body(df).iloc[i]
    if prev_body < 1e-8:
        return False
    # Previous body should be long
    if i < 10:
        return False
    avg_body = _body(df).iloc[i - 10:i].mean()
    if prev_body < avg_body * 1.5:
        return False
    # Current body contained within previous
    prev_high = max(df["Open"].iloc[i - 1], df["Close"].iloc[i - 1])
    prev_low = min(df["Open"].iloc[i - 1], df["Close"].iloc[i - 1])
    curr_high = max(df["Open"].iloc[i], df["Close"].iloc[i])
    curr_low = min(df["Open"].iloc[i], df["Close"].iloc[i])
    return curr_high <= prev_high and curr_low >= prev_low


# ═══════════════════════════════════════════════════════════════
# Trend detection (Murphy / Clenow / Faith)
# ═══════════════════════════════════════════════════════════════

def trend_direction(df: pd.DataFrame, i: int) -> str:
    """Determine trend direction using multiple tools.

    Returns: 'up', 'down', or 'neutral'.
    Consensus across: ma cross, ADX, Supertrend, Ichimoku.
    """
    votes = {"up": 0, "down": 0}

    # EMA 50 vs EMA 100 (Clenow filter)
    if "ema_50" in df.columns and "ema_100" in df.columns:
        if pd.notna(df["ema_50"].iloc[i]) and pd.notna(df["ema_100"].iloc[i]):
            if df["ema_50"].iloc[i] > df["ema_100"].iloc[i]:
                votes["up"] += 1
            else:
                votes["down"] += 1

    # Supertrend
    if "st_trend" in df.columns:
        if pd.notna(df["st_trend"].iloc[i]):
            if df["st_trend"].iloc[i] == 1:
                votes["up"] += 1
            else:
                votes["down"] += 1

    # Ichimoku: price vs cloud
    if "ichimoku_senkou_a" in df.columns and "ichimoku_senkou_b" in df.columns:
        a = df["ichimoku_senkou_a"].iloc[i]
        b = df["ichimoku_senkou_b"].iloc[i]
        if pd.notna(a) and pd.notna(b):
            cloud_top = max(a, b)
            cloud_bottom = min(a, b)
            if df["Close"].iloc[i] > cloud_top:
                votes["up"] += 1
            elif df["Close"].iloc[i] < cloud_bottom:
                votes["down"] += 1

    # ADX > 25 = trending market
    if "adx" in df.columns:
        if pd.notna(df["adx"].iloc[i]) and df["adx"].iloc[i] > 25:
            if "plus_di" in df.columns and "minus_di" in df.columns:
                if df["plus_di"].iloc[i] > df["minus_di"].iloc[i]:
                    votes["up"] += 1
                else:
                    votes["down"] += 1

    if votes["up"] > votes["down"]:
        return "up"
    elif votes["down"] > votes["up"]:
        return "down"
    return "neutral"


def is_breakout(df: pd.DataFrame, i: int, lookback: int = 20) -> dict | None:
    """Detect channel breakout — Faith (Turtle entry)."""
    if i < lookback:
        return None
    high_n = df["High"].iloc[i - lookback:i].max()
    low_n = df["Low"].iloc[i - lookback:i].min()
    curr_close = df["Close"].iloc[i]

    if curr_close > high_n:
        return {"type": "breakout_up", "level": high_n, "lookback": lookback}
    elif curr_close < low_n:
        return {"type": "breakout_down", "level": low_n, "lookback": lookback}
    return None


def check_new_high_low_streak(df: pd.DataFrame, i: int) -> dict:
    """Count consecutive new highs/lows — Nison 迭创新高(低).

    8-10 consecutive = extreme, reversal likely.
    """
    streak = {"type": None, "count": 0}

    # New highs
    if i >= 2:
        cnt = 0
        for j in range(i, max(0, i - 15), -1):
            prev_high = df["High"].iloc[j - 1] if j > 0 else df["High"].iloc[j]
            if df["High"].iloc[j] > prev_high:
                cnt += 1
            else:
                break
        if cnt >= 8:
            streak = {"type": "new_highs", "count": cnt}

    # New lows
    if i >= 2 and streak["type"] is None:
        cnt = 0
        for j in range(i, max(0, i - 15), -1):
            prev_low = df["Low"].iloc[j - 1] if j > 0 else df["Low"].iloc[j]
            if df["Low"].iloc[j] < prev_low:
                cnt += 1
            else:
                break
        if cnt >= 8:
            streak = {"type": "new_lows", "count": cnt}

    return streak


# ═══════════════════════════════════════════════════════════════
# Indicator signals (Murphy)
# ═══════════════════════════════════════════════════════════════

def check_rsi_signal(df: pd.DataFrame, i: int, trend: str) -> str | None:
    """RSI — Murphy Ch10 golden rule.

    In uptrend, RSI oversold = buy. In downtrend, RSI overbought = sell.
    """
    if i < 1 or "rsi_14" not in df.columns:
        return None
    rsi = df["rsi_14"].iloc[i]
    if pd.isna(rsi):
        return None
    if trend == "up" and rsi < 35:
        return "bullish"  # Oversold in uptrend = buy
    if trend == "down" and rsi > 65:
        return "bearish"  # Overbought in downtrend = sell
    return None


def check_macd_signal(df: pd.DataFrame, i: int) -> str | None:
    """MACD — Murphy Ch9. Golden cross / dead cross."""
    if i < 1 or "macd_dif" not in df.columns or "macd_dea" not in df.columns:
        return None
    prev_dif, prev_dea = df["macd_dif"].iloc[i - 1], df["macd_dea"].iloc[i - 1]
    curr_dif, curr_dea = df["macd_dif"].iloc[i], df["macd_dea"].iloc[i]
    if pd.isna(curr_dif) or pd.isna(curr_dea):
        return None
    if prev_dif <= prev_dea and curr_dif > curr_dea:
        return "bullish"
    if prev_dif >= prev_dea and curr_dif < curr_dea:
        return "bearish"
    return None


def check_atr_compression(df: pd.DataFrame, i: int, lookback: int = 20) -> bool:
    """ATR compression — Murphy (volatility contraction, expansion signal)."""
    if i < lookback + 5 or "atr_20" not in df.columns:
        return False
    curr_atr = df["atr_20"].iloc[i]
    min_atr = df["atr_20"].iloc[i - lookback:i].min()
    return curr_atr <= min_atr * 1.05  # Near multi-period low


# ═══════════════════════════════════════════════════════════════
# Main scanning
# ═══════════════════════════════════════════════════════════════

def scan(df: pd.DataFrame) -> list[dict]:
    """Scan the DataFrame for all trading setups.

    Returns a list of dicts, each describing one setup at a specific bar index.
    """
    setups = []
    n = len(df)

    for i in range(10, n):
        signals = []
        trend = trend_direction(df, i)
        is_compressed = check_atr_compression(df, i)

        # —— Candlestick patterns (Nison) ——
        if detect_hammer(df, i):
            signals.append({
                "source": "Nison",
                "pattern": "hammer",
                "direction": "bullish",
            })
        if detect_shooting_star(df, i):
            signals.append({
                "source": "Nison",
                "pattern": "shooting_star",
                "direction": "bearish",
            })
        if detect_doji(df, i):
            signals.append({
                "source": "Nison",
                "pattern": "doji",
                "direction": "neutral",
            })
        if detect_engulfing_bullish(df, i):
            signals.append({
                "source": "Nison",
                "pattern": "bullish_engulfing",
                "direction": "bullish",
            })
        if detect_engulfing_bearish(df, i):
            signals.append({
                "source": "Nison",
                "pattern": "bearish_engulfing",
                "direction": "bearish",
            })
        if detect_harami(df, i):
            signals.append({
                "source": "Nison",
                "pattern": "harami",
                "direction": "neutral",
            })

        # —— Breakout (Faith) ——
        for lb in [20, 55]:
            bo = is_breakout(df, i, lb)
            if bo:
                signals.append({
                    "source": "Faith",
                    "pattern": f"breakout_{lb}d",
                    "direction": "bullish" if "up" in bo["type"] else "bearish",
                    "level": bo["level"],
                })

        # —— New high/low streak (Nison) ——
        streak = check_new_high_low_streak(df, i)
        if streak["type"]:
            direction = "bearish" if streak["type"] == "new_highs" else "bullish"
            signals.append({
                "source": "Nison",
                "pattern": f"{streak['type']}_streak_{streak['count']}",
                "direction": direction,
            })

        # —— Indicator signals (Murphy) ——
        rsi_sig = check_rsi_signal(df, i, trend)
        if rsi_sig:
            signals.append({
                "source": "Murphy",
                "pattern": f"rsi_{rsi_sig}",
                "direction": rsi_sig,
            })
        macd_sig = check_macd_signal(df, i)
        if macd_sig:
            signals.append({
                "source": "Murphy",
                "pattern": f"macd_{macd_sig}",
                "direction": macd_sig,
            })
        if is_compressed:
            signals.append({
                "source": "Murphy",
                "pattern": "atr_compression",
                "direction": "neutral",
            })

        if not signals:
            continue

        setups.append({
            "index": i,
            "date": str(df.index[i]),
            "close": float(df["Close"].iloc[i]),
            "trend": trend,
            "signals": signals,
            "atr_20": float(df["atr_20"].iloc[i]) if "atr_20" in df.columns else None,
            "rsi_14": float(df["rsi_14"].iloc[i]) if "rsi_14" in df.columns else None,
            "adx": float(df["adx"].iloc[i]) if "adx" in df.columns else None,
        })

    return setups


def main():
    parser = argparse.ArgumentParser(
        description="Scan for trading setups using multi-book analysis"
    )
    parser.add_argument("input", help="CSV with OHLCV + indicators")
    parser.add_argument("--limit", "-n", type=int, default=20,
                        help="Show only the last N setups (default: 20)")
    args = parser.parse_args()

    df = pd.read_csv(args.input, index_col=0, parse_dates=True)
    setups = scan(df)

    if not setups:
        print("No setups detected.")
        return

    # Print the most recent setups
    for s in setups[-args.limit:]:
        sig_str = " | ".join(
            f"{sig['source']}:{sig['pattern']}[{sig['direction']}]"
            for sig in s["signals"]
        )
        print(
            f"[{s['date']}] close={s['close']:.2f} "
            f"trend={s['trend']} rsi={s['rsi_14']:.0f} "
            f"adx={s['adx']:.0f} | {sig_str}"
        )

    print(f"\nTotal setups: {len(setups)}")


if __name__ == "__main__":
    main()
