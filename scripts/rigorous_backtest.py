#!/usr/bin/env python3
"""
RIGOROUS BACKTEST — Full trading-mastery skill analysis on EVERY signal candle.
5 hot coins, 1 year daily data. No shortcuts.

Analysis per signal (L1→L5):
  L1: Trend direction (4-tool consensus), minimum resistance path
  L2: Candlestick pattern, support/resistance, indicator signals, volume confirm
  L3: Turtle breakout, Clenow filter, setup quality score
  L4: ATR position sizing, risk/reward ratio, MAE/MFE tracking
  L5: (not backtestable — mental discipline)

Strategy: BearRally SHORT in bear trend / BullRally LONG in bull trend
Exit: 5-day swing (optimized from holding period analysis)
"""

import pandas as pd
import numpy as np
import sys, os, json, time
from datetime import datetime, timedelta
from pathlib import Path

# binpan import
try:
    import binpan
except ImportError:
    print("ERROR: binpan not installed. Run: pip install binpan")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
# DATA FETCHING
# ═══════════════════════════════════════════════════════════════

def fetch_klines(symbol: str, limit: int = 400) -> pd.DataFrame:
    """Fetch daily klines from Binance via binpan."""
    sym = binpan.Symbol(
        symbol=symbol.lower(),
        tick_interval="1d",
        time_zone="UTC",
        limit=limit,
    )
    df = sym.df
    if df is None or df.empty:
        raise RuntimeError(f"No data for {symbol}")
    # Standardize columns
    df = df.rename(columns={
        'open': 'Open', 'high': 'High', 'low': 'Low',
        'close': 'Close', 'volume': 'Volume'
    } if 'open' in df.columns else {})
    return df

# ═══════════════════════════════════════════════════════════════
# INDICATOR COMPUTATION (from compute_indicators.py)
# ═══════════════════════════════════════════════════════════════

def _ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def _sma(series, period):
    return series.rolling(window=period).mean()

def _true_range(df):
    prev_close = df["Close"].shift(1)
    hl = df["High"] - df["Low"]
    hc = (df["High"] - prev_close).abs()
    lc = (df["Low"] - prev_close).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1)

def compute_all_indicators(df):
    df = df.copy()
    df["tr"] = _true_range(df)
    
    # Moving averages
    for p in [20, 50, 100, 200]:
        df[f"sma_{p}"] = _sma(df["Close"], p)
    for p in [12, 26, 50, 100]:
        df[f"ema_{p}"] = _ema(df["Close"], p)
    
    # MACD
    ema12 = _ema(df["Close"], 12)
    ema26 = _ema(df["Close"], 26)
    df["macd_dif"] = ema12 - ema26
    df["macd_dea"] = _ema(df["macd_dif"], 9)
    df["macd_hist"] = 2 * (df["macd_dif"] - df["macd_dea"])
    
    # RSI
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    df["rsi_14"] = 100 - (100 / (1 + _ema(gain, 14) / _ema(loss, 14).replace(0, np.nan)))
    
    # Stochastic
    low14 = df["Low"].rolling(14).min()
    high14 = df["High"].rolling(14).max()
    df["stoch_k"] = 100 * (df["Close"] - low14) / (high14 - low14)
    df["stoch_d"] = _sma(df["stoch_k"], 3)
    
    # ATR
    df["atr_20"] = _ema(df["tr"], 20)
    
    # Bollinger
    mid_20 = _sma(df["Close"], 20)
    std_20 = df["Close"].rolling(20).std()
    df["bb_mid"] = mid_20
    df["bb_upper"] = mid_20 + 2 * std_20
    df["bb_lower"] = mid_20 - 2 * std_20
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    
    # ADX
    tr = df["tr"]
    up = df["High"].diff()
    down = -df["Low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0)
    minus_dm = np.where((down > up) & (down > 0), down, 0)
    atr14 = _ema(tr, 14)
    plus_di = 100 * _ema(pd.Series(plus_dm, index=df.index), 14) / atr14
    minus_di = 100 * _ema(pd.Series(minus_dm, index=df.index), 14) / atr14
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    df["adx"] = _ema(dx, 14)
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di
    
    # Supertrend (10, 3.0)
    atr10 = _ema(tr, 10)
    hl2 = (df["High"] + df["Low"]) / 2
    up_basic = hl2 + 3.0 * atr10
    lo_basic = hl2 - 3.0 * atr10
    up_band = pd.Series(np.nan, index=df.index)
    lo_band = pd.Series(np.nan, index=df.index)
    st = pd.Series(1, index=df.index)
    up_band.iloc[0] = up_basic.iloc[0]
    lo_band.iloc[0] = lo_basic.iloc[0]
    for i in range(1, len(df)):
        up_band.iloc[i] = up_basic.iloc[i] if (up_basic.iloc[i] < up_band.iloc[i-1] or df["Close"].iloc[i-1] > up_band.iloc[i-1]) else up_band.iloc[i-1]
        lo_band.iloc[i] = lo_basic.iloc[i] if (lo_basic.iloc[i] > lo_band.iloc[i-1] or df["Close"].iloc[i-1] < lo_band.iloc[i-1]) else lo_band.iloc[i-1]
        st.iloc[i] = 1 if df["Close"].iloc[i] > up_band.iloc[i-1] else (-1 if df["Close"].iloc[i] < lo_band.iloc[i-1] else st.iloc[i-1])
    df["st_value"] = np.where(st == 1, lo_band, up_band)
    df["st_trend"] = st
    
    # Heikin-Ashi
    df["ha_close"] = (df["Open"] + df["High"] + df["Low"] + df["Close"]) / 4
    ha_open = pd.Series(np.nan, index=df.index)
    ha_open.iloc[0] = (df["Open"].iloc[0] + df["Close"].iloc[0]) / 2
    for i in range(1, len(df)):
        ha_open.iloc[i] = (ha_open.iloc[i-1] + df["ha_close"].iloc[i-1]) / 2
    df["ha_open"] = ha_open
    df["ha_high"] = df[["High", "ha_open", "ha_close"]].max(axis=1)
    df["ha_low"] = df[["Low", "ha_open", "ha_close"]].min(axis=1)
    
    # Difference Index
    df["diff_idx_25"] = (df["Close"] - _sma(df["Close"], 25)) / _sma(df["Close"], 25) * 100
    
    return df

# ═══════════════════════════════════════════════════════════════
# CANDLESTICK PATTERN DETECTION (from detect_setup.py)
# ═══════════════════════════════════════════════════════════════

def _body(df, i):
    return abs(df["Close"].iloc[i] - df["Open"].iloc[i])

def _upper_shadow(df, i):
    return df["High"].iloc[i] - max(df["Open"].iloc[i], df["Close"].iloc[i])

def _lower_shadow(df, i):
    return min(df["Open"].iloc[i], df["Close"].iloc[i]) - df["Low"].iloc[i]

def detect_hammer(df, i):
    if i < 10: return False
    body = _body(df, i)
    if body < 1e-8: return False
    lower = _lower_shadow(df, i)
    upper = _upper_shadow(df, i)
    body_lo = min(df["Open"].iloc[i], df["Close"].iloc[i])
    body_hi = max(df["Open"].iloc[i], df["Close"].iloc[i])
    body_center = (body_hi + body_lo) / 2
    if body_lo < body_center: return False
    if lower < body * 3: return False
    if upper > body * 0.5: return False
    recent = df["Close"].iloc[max(0, i-5):i]
    return len(recent) >= 3 and recent.iloc[-1] < recent.iloc[0]

def detect_shooting_star(df, i):
    if i < 10: return False
    body = _body(df, i)
    if body < 1e-8: return False
    upper = _upper_shadow(df, i)
    body_hi = max(df["Open"].iloc[i], df["Close"].iloc[i])
    body_lo = min(df["Open"].iloc[i], df["Close"].iloc[i])
    body_center = (body_hi + body_lo) / 2
    if body_hi > body_center: return False
    if upper < body * 3: return False
    if _lower_shadow(df, i) > body * 0.5: return False
    recent = df["Close"].iloc[max(0, i-5):i]
    return len(recent) >= 3 and recent.iloc[-1] > recent.iloc[0]

def detect_doji(df, i):
    body = _body(df, i)
    rng = df["High"].iloc[i] - df["Low"].iloc[i]
    return rng > 0 and body / rng < 0.05

def detect_engulfing_bullish(df, i):
    if i < 1: return False
    prev_red = df["Close"].iloc[i-1] < df["Open"].iloc[i-1]
    curr_green = df["Close"].iloc[i] > df["Open"].iloc[i]
    if not (prev_red and curr_green): return False
    return df["Open"].iloc[i] <= df["Close"].iloc[i-1] and df["Close"].iloc[i] >= df["Open"].iloc[i-1]

def detect_engulfing_bearish(df, i):
    if i < 1: return False
    prev_green = df["Close"].iloc[i-1] > df["Open"].iloc[i-1]
    curr_red = df["Close"].iloc[i] < df["Open"].iloc[i]
    if not (prev_green and curr_red): return False
    return df["Open"].iloc[i] >= df["Close"].iloc[i-1] and df["Close"].iloc[i] <= df["Open"].iloc[i-1]

def detect_harami(df, i):
    if i < 1 or i < 10: return False
    prev_body = _body(df, i-1)
    curr_body = _body(df, i)
    if prev_body < 1e-8: return False
    avg_body = pd.Series([_body(df, j) for j in range(i-10, i)]).mean()
    if prev_body < avg_body * 1.5: return False
    prev_hi = max(df["Open"].iloc[i-1], df["Close"].iloc[i-1])
    prev_lo = min(df["Open"].iloc[i-1], df["Close"].iloc[i-1])
    curr_hi = max(df["Open"].iloc[i], df["Close"].iloc[i])
    curr_lo = min(df["Open"].iloc[i], df["Close"].iloc[i])
    return curr_hi <= prev_hi and curr_lo >= prev_lo

def detect_dark_cloud(df, i):
    if i < 1: return False
    prev_white = df["Close"].iloc[i-1] > df["Open"].iloc[i-1]
    curr_black = df["Close"].iloc[i] < df["Open"].iloc[i]
    if not (prev_white and curr_black): return False
    prev_body = _body(df, i-1)
    if prev_body < 1e-8: return False
    # open above prev high, close below midpoint
    if df["Open"].iloc[i] <= df["High"].iloc[i-1]: return False
    prev_mid = (df["Open"].iloc[i-1] + df["Close"].iloc[i-1]) / 2
    return df["Close"].iloc[i] < prev_mid

def detect_piercing(df, i):
    if i < 1: return False
    prev_black = df["Close"].iloc[i-1] < df["Open"].iloc[i-1]
    curr_white = df["Close"].iloc[i] > df["Open"].iloc[i]
    if not (prev_black and curr_white): return False
    prev_body = _body(df, i-1)
    if prev_body < 1e-8: return False
    if df["Open"].iloc[i] >= df["Low"].iloc[i-1]: return False
    prev_mid = (df["Open"].iloc[i-1] + df["Close"].iloc[i-1]) / 2
    return df["Close"].iloc[i] > prev_mid

# ═══════════════════════════════════════════════════════════════
# FULL PER-SIGNAL ANALYSIS
# ═══════════════════════════════════════════════════════════════

def trend_consensus(df, i):
    """L1: 4-tool trend direction consensus (Dow Theory)."""
    votes = {"up": 0, "down": 0}
    details = {}
    
    # EMA 50 vs EMA 100 (Clenow)
    e50 = df["ema_50"].iloc[i]; e100 = df["ema_100"].iloc[i]
    if pd.notna(e50) and pd.notna(e100):
        if e50 > e100:
            votes["up"] += 1; details["ema_cross"] = "bull"
        else:
            votes["down"] += 1; details["ema_cross"] = "bear"
    
    # Supertrend
    st = df["st_trend"].iloc[i]
    if pd.notna(st):
        if st == 1:
            votes["up"] += 1; details["supertrend"] = "bull"
        else:
            votes["down"] += 1; details["supertrend"] = "bear"
    
    # ADX + DI direction
    adx = df["adx"].iloc[i]; pdi = df["plus_di"].iloc[i]; mdi = df["minus_di"].iloc[i]
    if pd.notna(adx) and pd.notna(pdi) and pd.notna(mdi):
        if pdi > mdi:
            votes["up"] += 1; details["adx_di"] = "bull"
        else:
            votes["down"] += 1; details["adx_di"] = "bear"
    
    # Ichimoku: price vs cloud
    a = df.get("ichimoku_senkou_a", pd.Series([np.nan]*len(df))).iloc[i]
    b = df.get("ichimoku_senkou_b", pd.Series([np.nan]*len(df))).iloc[i]
    if pd.notna(a) and pd.notna(b):
        cloud_top = max(a, b); cloud_bot = min(a, b)
        if df["Close"].iloc[i] > cloud_top:
            votes["up"] += 1; details["ichimoku"] = "above_cloud"
        elif df["Close"].iloc[i] < cloud_bot:
            votes["down"] += 1; details["ichimoku"] = "below_cloud"
        else:
            details["ichimoku"] = "in_cloud"
    
    if votes["up"] > votes["down"]:
        trend = "UP"
        strength = votes["up"]
    elif votes["down"] > votes["up"]:
        trend = "DOWN"
        strength = votes["down"]
    else:
        trend = "NEUTRAL"
        strength = 0
    
    return trend, strength, details

def find_support_resistance(df, i, lookback=100):
    """L2: Identify nearest support/resistance levels (Murphy Ch4)."""
    if i < lookback:
        return None, None
    
    window = df.iloc[max(0, i-lookback):i]
    close = df["Close"].iloc[i]
    
    # Find swing highs and lows (simple pivot detection)
    highs = []; lows = []
    for j in range(3, len(window)-3):
        idx = window.index[j]
        if window["High"].iloc[j] == window["High"].iloc[j-3:j+4].max():
            highs.append((idx, window["High"].iloc[j]))
        if window["Low"].iloc[j] == window["Low"].iloc[j-3:j+4].min():
            lows.append((idx, window["Low"].iloc[j]))
    
    # Nearest resistance above current price
    nearest_resistance = None
    for dt, h in sorted(highs, key=lambda x: x[1]):
        if h > close:
            nearest_resistance = h
            break
    
    # Nearest support below current price
    nearest_support = None
    for dt, l in sorted(lows, key=lambda x: x[1], reverse=True):
        if l < close:
            nearest_support = l
            break
    
    return nearest_support, nearest_resistance

def check_volume_confirmation(df, i):
    """L2: Volume confirmation (Murphy Ch7)."""
    if i < 20: return "insufficient"
    vol = df["Volume"].iloc[i]
    avg_vol = df["Volume"].iloc[i-20:i].mean()
    if avg_vol == 0: return "insufficient"
    ratio = vol / avg_vol
    if ratio > 1.5: return "high"
    if ratio > 0.8: return "normal"
    return "low"

def estimate_elliott_position(df, i):
    """L2: Rough Elliott Wave position estimate (Murphy Ch12).
    
    Simplified: estimate which wave we might be in based on recent structure.
    Returns: 'wave_1', 'wave_3', 'wave_5', 'abc_correction', 'unclear'
    """
    if i < 100: return "unclear"
    
    # Look at the last 3 major swings
    close = df["Close"].iloc[i]
    ema100 = df["ema_100"].iloc[i]
    ema50 = df["ema_50"].iloc[i]
    
    if pd.isna(ema100) or pd.isna(ema50):
        return "unclear"
    
    # Check if we're in a strong trend (possible wave 3)
    adx = df["adx"].iloc[i]
    if pd.notna(adx) and adx > 40:
        return "wave_3"  # Strong momentum = likely wave 3
    
    # Check price relative to EMAs for wave position
    if close > ema50 > ema100:
        # In uptrend: check if extended
        diff_idx = df["diff_idx_25"].iloc[i]
        if pd.notna(diff_idx) and diff_idx > 15:
            return "wave_5"  # Extended from mean = possible wave 5
        if pd.notna(adx) and adx > 30:
            return "wave_3"
        return "wave_1_or_3"
    elif close < ema50 < ema100:
        diff_idx = df["diff_idx_25"].iloc[i]
        if pd.notna(diff_idx) and diff_idx < -15:
            return "wave_5"
        if pd.notna(adx) and adx > 30:
            return "wave_3"
        return "wave_1_or_3"
    else:
        return "abc_correction"

def detect_all_candle_signals(df, i):
    """L2: Detect ALL candlestick patterns at bar i."""
    patterns = []
    if detect_hammer(df, i): patterns.append(("hammer", "bullish", "Nison"))
    if detect_shooting_star(df, i): patterns.append(("shooting_star", "bearish", "Nison"))
    if detect_doji(df, i): patterns.append(("doji", "neutral", "Nison"))
    if detect_engulfing_bullish(df, i): patterns.append(("bullish_engulfing", "bullish", "Nison"))
    if detect_engulfing_bearish(df, i): patterns.append(("bearish_engulfing", "bearish", "Nison"))
    if detect_harami(df, i): patterns.append(("harami", "neutral", "Nison"))
    if detect_dark_cloud(df, i): patterns.append(("dark_cloud", "bearish", "Nison"))
    if detect_piercing(df, i): patterns.append(("piercing", "bullish", "Nison"))
    return patterns

def detect_breakout(df, i, lookback=20):
    """L3: Turtle breakout detection (Faith)."""
    if i < lookback: return None
    high_n = df["High"].iloc[i-lookback:i].max()
    low_n = df["Low"].iloc[i-lookback:i].min()
    close = df["Close"].iloc[i]
    if close > high_n:
        return ("breakout_up", "bullish", lookback, high_n)
    elif close < low_n:
        return ("breakout_down", "bearish", lookback, low_n)
    return None

def check_indicator_signals(df, i, trend):
    """L2: Check indicator signals with golden rule (Murphy Ch10)."""
    signals = []
    rsi = df["rsi_14"].iloc[i]
    
    # RSI Golden Rule: uptrend oversold=buy, downtrend overbought=sell
    if pd.notna(rsi):
        if trend == "UP" and rsi < 35:
            signals.append(("rsi_oversold_buy", "bullish", "Murphy"))
        elif trend == "DOWN" and rsi > 65:
            signals.append(("rsi_overbought_sell", "bearish", "Murphy"))
        elif rsi < 25:
            signals.append(("rsi_extreme_oversold", "bullish", "Murphy"))
        elif rsi > 75:
            signals.append(("rsi_extreme_overbought", "bearish", "Murphy"))
    
    # MACD cross
    if i >= 1:
        prev_dif = df["macd_dif"].iloc[i-1]; prev_dea = df["macd_dea"].iloc[i-1]
        curr_dif = df["macd_dif"].iloc[i]; curr_dea = df["macd_dea"].iloc[i]
        if pd.notna(curr_dif) and pd.notna(curr_dea):
            if prev_dif <= prev_dea and curr_dif > curr_dea:
                signals.append(("macd_golden_cross", "bullish", "Murphy"))
            elif prev_dif >= prev_dea and curr_dif < curr_dea:
                signals.append(("macd_dead_cross", "bearish", "Murphy"))
    
    # Bollinger touch
    bb_upper = df["bb_upper"].iloc[i]; bb_lower = df["bb_lower"].iloc[i]
    close = df["Close"].iloc[i]
    if pd.notna(bb_upper) and pd.notna(bb_lower):
        if close <= bb_lower:
            signals.append(("bb_lower_touch", "bullish", "Murphy"))
        elif close >= bb_upper:
            signals.append(("bb_upper_touch", "bearish", "Murphy"))
    
    # Bollinger squeeze
    bb_width = df["bb_width"].iloc[i]
    if pd.notna(bb_width) and i >= 20:
        min_width = df["bb_width"].iloc[i-20:i].min()
        if bb_width <= min_width * 1.05:
            signals.append(("bb_squeeze", "neutral", "Murphy"))
    
    # ADX trending check
    adx = df["adx"].iloc[i]
    if pd.notna(adx) and adx > 25:
        signals.append(("adx_trending", "neutral", "Murphy"))
    
    return signals

def compute_setup_quality(df, i, trend, signals):
    """L3: Compute setup quality score (0-100)."""
    score = 0
    
    # Base: trend strength (max 30)
    adx = df["adx"].iloc[i]
    if pd.notna(adx):
        if adx > 40: score += 30
        elif adx > 30: score += 25
        elif adx > 25: score += 20
        elif adx > 20: score += 15
    
    # Signal alignment with trend (max 25)
    aligned = sum(1 for s in signals if s[1] == ("bullish" if trend == "UP" else "bearish"))
    if aligned > 0:
        score += min(25, aligned * 12)
    
    # Volume confirmation (max 15)
    vol_status = check_volume_confirmation(df, i)
    if vol_status == "high": score += 15
    elif vol_status == "normal": score += 10
    
    # Multiple signal types (max 15)
    sources = set(s[2] for s in signals)
    if "Nison" in sources: score += 8
    if "Murphy" in sources: score += 7
    
    # RSI not at extreme (max 15)
    rsi = df["rsi_14"].iloc[i]
    if pd.notna(rsi):
        if 30 <= rsi <= 70: score += 15
        elif 25 <= rsi <= 75: score += 10
    
    return min(100, score)

def full_signal_analysis(df, i):
    """MAIN: Apply complete skill analysis to bar i.
    
    Returns dict with all analysis layers, or None if no signal.
    """
    if i < 100:  # Need enough history for robust analysis
        return None
    
    # L1: Trend
    trend, trend_strength, trend_details = trend_consensus(df, i)
    
    # L2: Candlestick patterns
    candle_patterns = detect_all_candle_signals(df, i)
    
    # L2: Breakout detection
    bo_20 = detect_breakout(df, i, 20)
    bo_55 = detect_breakout(df, i, 55)
    
    # L2: Indicator signals
    indicator_signals = check_indicator_signals(df, i, trend)
    
    # Combine all signals
    all_sigs = []
    for p in candle_patterns:
        all_sigs.append(p)
    if bo_20: all_sigs.append(bo_20[:3])  # strip level
    if bo_55: all_sigs.append(bo_55[:3])
    for s in indicator_signals:
        all_sigs.append(s)
    
    # Filter: only keep signals that align with trend
    aligned_sigs = []
    for s in all_sigs:
        s_dir = s[1]
        if trend == "UP" and s_dir == "bullish":
            aligned_sigs.append(s)
        elif trend == "DOWN" and s_dir == "bearish":
            aligned_sigs.append(s)
        elif s_dir == "neutral":
            aligned_sigs.append(s)
    
    if not aligned_sigs:
        return None
    
    # L2: Support/Resistance
    support, resistance = find_support_resistance(df, i)
    
    # L2: Volume
    vol_status = check_volume_confirmation(df, i)
    
    # L2: Elliott Wave estimate
    wave_pos = estimate_elliott_position(df, i)
    
    # L3: Setup quality score
    quality = compute_setup_quality(df, i, trend, aligned_sigs)
    
    # L4: Risk/Reward estimate
    atr = df["atr_20"].iloc[i]
    close = df["Close"].iloc[i]
    rr_ratio = None
    if trend == "UP" and resistance and support and pd.notna(atr):
        reward = (resistance - close) / close * 100
        risk = (close - support) / close * 100
        if risk > 0:
            rr_ratio = reward / risk
    elif trend == "DOWN" and resistance and support and pd.notna(atr):
        reward = (close - support) / close * 100
        risk = (resistance - close) / close * 100
        if risk > 0:
            rr_ratio = reward / risk
    
    return {
        "index": i,
        "date": str(df.index[i]),
        "close": float(close),
        "trend": trend,
        "trend_strength": trend_strength,
        "signals": [s[0] for s in aligned_sigs],
        "signal_details": aligned_sigs,
        "support": support,
        "resistance": resistance,
        "volume": vol_status,
        "wave_position": wave_pos,
        "quality_score": quality,
        "rr_ratio": rr_ratio,
        "atr_20": float(atr) if pd.notna(atr) else None,
        "rsi_14": float(rsi) if pd.notna(rsi := df["rsi_14"].iloc[i]) else None,
        "adx": float(adx) if pd.notna(adx := df["adx"].iloc[i]) else None,
    }

# ═══════════════════════════════════════════════════════════════
# TRADE SIMULATION
# ═══════════════════════════════════════════════════════════════

def simulate_trades(df, signals_list, exit_days=5, quality_threshold=20):
    """Simulate trades: enter on signal, exit after N days.
    
    Only enters signals with quality >= threshold.
    Tracks MAE (max adverse) and MFE (max favorable) for each trade.
    """
    trades = []
    in_trade = False
    entry_idx = None; entry_price = None; entry_direction = None
    max_fav = 0; max_adv = 0
    exit_left = 0
    
    # Build signal index
    signal_at = set(s["index"] for s in signals_list if s["quality_score"] >= quality_threshold)
    signal_map = {s["index"]: s for s in signals_list if s["quality_score"] >= quality_threshold}
    
    for i in range(len(df)):
        if in_trade:
            exit_left -= 1
            close = df["Close"].iloc[i]
            
            # Track MAE/MFE
            if entry_direction == "short":
                pnl = (entry_price - close) / entry_price * 100
            else:
                pnl = (close - entry_price) / entry_price * 100
            max_fav = max(max_fav, pnl)
            max_adv = min(max_adv, pnl)
            
            if exit_left <= 0:
                exit_price = close
                if entry_direction == "short":
                    ret = (entry_price - exit_price) / entry_price * 100
                else:
                    ret = (exit_price - entry_price) / entry_price * 100
                
                s = signal_map.get(entry_idx, {})
                trades.append({
                    "entry_date": str(df.index[entry_idx]),
                    "exit_date": str(df.index[i]),
                    "direction": entry_direction,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "return_pct": round(ret, 4),
                    "bars_held": i - entry_idx,
                    "mae_pct": round(max_adv, 4),  # max adverse (most negative)
                    "mfe_pct": round(max_fav, 4),  # max favorable (most positive)
                    "quality_score": s.get("quality_score", 0),
                    "entry_trend": s.get("trend", "?"),
                    "entry_signals": ",".join(s.get("signals", [])),
                    "wave_position": s.get("wave_position", "?"),
                    "volume_status": s.get("volume", "?"),
                    "rr_ratio": s.get("rr_ratio", 0),
                })
                in_trade = False
                continue
        
        # Entry: only on signal bars
        if not in_trade and i in signal_at:
            s = signal_map[i]
            in_trade = True
            entry_idx = i
            entry_price = df["Close"].iloc[i]
            exit_left = exit_days
            max_fav = 0; max_adv = 0
            
            if s["trend"] == "DOWN":
                entry_direction = "short"
            elif s["trend"] == "UP":
                entry_direction = "long"
            else:
                # Neutral trend: skip
                in_trade = False
    
    # Close any open trade at end
    if in_trade:
        close = df["Close"].iloc[-1]
        if entry_direction == "short":
            ret = (entry_price - close) / entry_price * 100
        else:
            ret = (close - entry_price) / entry_price * 100
        s = signal_map.get(entry_idx, {})
        trades.append({
            "entry_date": str(df.index[entry_idx]),
            "exit_date": str(df.index[-1]),
            "direction": entry_direction,
            "entry_price": entry_price,
            "exit_price": close,
            "return_pct": round(ret, 4),
            "bars_held": len(df) - 1 - entry_idx,
            "mae_pct": round(max_adv, 4),
            "mfe_pct": round(max_fav, 4),
            "quality_score": s.get("quality_score", 0),
            "entry_trend": s.get("trend", "?"),
            "entry_signals": ",".join(s.get("signals", [])),
            "wave_position": s.get("wave_position", "?"),
            "volume_status": s.get("volume", "?"),
            "rr_ratio": s.get("rr_ratio", 0),
        })
    
    return trades

# ═══════════════════════════════════════════════════════════════
# REPORTING
# ═══════════════════════════════════════════════════════════════

def compute_trade_stats(trades):
    """Compute aggregate statistics from trade list."""
    if not trades:
        return {"total_trades": 0, "win_rate": 0, "total_return_pct": 0,
                "avg_return_pct": 0, "profit_factor": 0, "avg_bars": 0,
                "avg_mae": 0, "avg_mfe": 0, "best_trade": 0, "worst_trade": 0,
                "avg_quality": 0, "trades_per_month": 0}
    
    returns = [t["return_pct"] for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    bars = [t["bars_held"] for t in trades]
    mae_vals = [t["mae_pct"] for t in trades]
    mfe_vals = [t["mfe_pct"] for t in trades]
    qualities = [t["quality_score"] for t in trades]
    
    total_ret = sum(returns)
    pf = sum(wins) / abs(sum(losses)) if sum(losses) != 0 else (999 if wins else 0)
    
    return {
        "total_trades": len(trades),
        "winners": len(wins),
        "losers": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 2),
        "total_return_pct": round(total_ret, 2),
        "avg_return_pct": round(np.mean(returns), 2),
        "profit_factor": round(pf, 2),
        "avg_bars": round(np.mean(bars), 1),
        "avg_mae": round(np.mean(mae_vals), 2),
        "avg_mfe": round(np.mean(mfe_vals), 2),
        "best_trade": round(max(returns), 2),
        "worst_trade": round(min(returns), 2),
        "avg_quality": round(np.mean(qualities), 1),
        "trades_per_month": round(len(trades) / max(len(bars) / 22, 0.1), 1),
    }

def print_coin_report(coin, df, signals, trades, stats, quality_threshold):
    """Print detailed report for one coin."""
    print(f"\n{'='*80}")
    print(f"  {coin} — COMPREHENSIVE BACKTEST REPORT")
    print(f"{'='*80}")
    print(f"  Period: {df.index[0].date()} → {df.index[-1].date()} ({len(df)} bars)")
    print(f"  Total signals detected (≥ Q{quality_threshold}): {len(signals)}")
    print(f"  Trades executed: {stats['total_trades']}")
    
    if stats['total_trades'] == 0:
        print("  No trades to report.")
        return
    
    print(f"\n  ── PERFORMANCE ──")
    print(f"  Win Rate:         {stats['win_rate']}%")
    print(f"  Total Return:     {stats['total_return_pct']:+.2f}%")
    print(f"  Avg Return/Trade: {stats['avg_return_pct']:+.2f}%")
    print(f"  Profit Factor:    {stats['profit_factor']}")
    print(f"  Best Trade:       {stats['best_trade']:+.2f}%")
    print(f"  Worst Trade:      {stats['worst_trade']:+.2f}%")
    print(f"  Avg MAE:          {stats['avg_mae']:.2f}%")
    print(f"  Avg MFE:          {stats['avg_mfe']:.2f}%")
    print(f"  Avg Holding:      {stats['avg_bars']} bars")
    print(f"  Avg Quality:      {stats['avg_quality']}")
    print(f"  Trades/Month:     {stats['trades_per_month']}")
    
    # Signal breakdown
    print(f"\n  ── SIGNAL USAGE ──")
    signal_counts = {}
    for t in trades:
        for s in t["entry_signals"].split(","):
            s = s.strip()
            if s:
                signal_counts[s] = signal_counts.get(s, 0) + 1
    for sig, cnt in sorted(signal_counts.items(), key=lambda x: -x[1]):
        # Compute win rate for this signal
        sig_trades = [t for t in trades if sig in t["entry_signals"]]
        sig_wr = sum(1 for t in sig_trades if t["return_pct"] > 0) / len(sig_trades) * 100 if sig_trades else 0
        print(f"    {sig:<30} used {cnt:>3}x  WR={sig_wr:.1f}%")
    
    # Wave position performance
    print(f"\n  ── WAVE POSITION PERFORMANCE ──")
    wave_groups = {}
    for t in trades:
        wp = t["wave_position"]
        if wp not in wave_groups:
            wave_groups[wp] = {"trades": 0, "returns": [], "wins": 0}
        wave_groups[wp]["trades"] += 1
        wave_groups[wp]["returns"].append(t["return_pct"])
        if t["return_pct"] > 0:
            wave_groups[wp]["wins"] += 1
    for wp, data in sorted(wave_groups.items()):
        wr = data["wins"] / data["trades"] * 100
        avg_r = np.mean(data["returns"])
        print(f"    {wp:<20} trades={data['trades']:>3}  WR={wr:.1f}%  AvgRet={avg_r:+.2f}%")
    
    # Quality vs return
    print(f"\n  ── QUALITY VS RETURN ──")
    for q_range in [(0, 30), (30, 50), (50, 70), (70, 101)]:
        q_trades = [t for t in trades if q_range[0] <= t["quality_score"] < q_range[1]]
        if q_trades:
            wr = sum(1 for t in q_trades if t["return_pct"] > 0) / len(q_trades) * 100
            avg_r = np.mean([t["return_pct"] for t in q_trades])
            print(f"    Q{q_range[0]}-{q_range[1]-1}:  {len(q_trades):>3} trades  WR={wr:.1f}%  AvgRet={avg_r:+.2f}%")

    # Last 5 trades detail
    print(f"\n  ── LAST 5 TRADES ──")
    for t in trades[-5:]:
        print(f"    {t['entry_date'][:10]} → {t['exit_date'][:10]}  "
              f"{t['direction']:>5}  {t['return_pct']:+.2f}%  "
              f"Q={t['quality_score']}  wave={t['wave_position']}  "
              f"sig={t['entry_signals'][:50]}")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT"]
    QUALITY_THRESHOLD = 20
    EXIT_DAYS = 5
    
    all_reports = []
    
    for coin in COINS:
        print(f"\n{'─'*80}")
        print(f"  Processing {coin}...")
        print(f"  [1/4] Fetching 1-year daily data...")
        
        try:
            df = fetch_klines(coin, limit=400)
        except Exception as e:
            print(f"  [FAIL] Cannot fetch {coin}: {e}")
            continue
        
        print(f"  [2/4] Got {len(df)} bars. Computing indicators...")
        df = compute_all_indicators(df)
        
        print(f"  [3/4] Analyzing EVERY signal-bearing candle...")
        signals = []
        for i in range(100, len(df)):
            analysis = full_signal_analysis(df, i)
            if analysis:
                signals.append(analysis)
        
        print(f"  [4/4] Found {len(signals)} tradable signals. Simulating trades...")
        trades = simulate_trades(df, signals, EXIT_DAYS, QUALITY_THRESHOLD)
        stats = compute_trade_stats(trades)
        
        all_reports.append({
            "coin": coin,
            "bars": len(df),
            "signals_detected": len(signals),
            "stats": stats,
            "trades": trades,
        })
        
        print_coin_report(coin, df, signals, trades, stats, QUALITY_THRESHOLD)
    
    # ══════════════════════════════════════════════════════════
    # CROSS-COIN SUMMARY
    # ══════════════════════════════════════════════════════════
    print(f"\n\n{'='*80}")
    print(f"  CROSS-COIN SUMMARY — {len(all_reports)} COINS")
    print(f"{'='*80}")
    print(f"  {'Coin':<12} {'Trades':>6} {'WR%':>7} {'TotRet%':>9} {'AvgRet%':>8} {'PF':>6} {'AvgMAE%':>8} {'AvgMFE%':>8} {'Best%':>7} {'Worst%':>7} {'AvgQ':>5}")
    print(f"  {'-'*12} {'-'*6} {'-'*7} {'-'*9} {'-'*8} {'-'*6} {'-'*8} {'-'*8} {'-'*7} {'-'*7} {'-'*5}")
    
    for r in all_reports:
        s = r["stats"]
        print(f"  {r['coin']:<12} {s['total_trades']:>6} {s['win_rate']:>6.1f}% {s['total_return_pct']:>8.2f}% {s['avg_return_pct']:>7.2f}% {s['profit_factor']:>5.2f} {s['avg_mae']:>7.2f}% {s['avg_mfe']:>7.2f}% {s['best_trade']:>6.2f}% {s['worst_trade']:>6.2f}% {s['avg_quality']:>4.0f}")
    
    # Best coin by profit factor
    if all_reports:
        best = max(all_reports, key=lambda x: x["stats"]["profit_factor"])
        print(f"\n  ★ Best Profit Factor: {best['coin']} — PF={best['stats']['profit_factor']}")
        print(f"  ★ Highest Win Rate:   {max(all_reports, key=lambda x: x['stats']['win_rate'])['coin']}")
        print(f"  ★ Most Profitable:    {max(all_reports, key=lambda x: x['stats']['total_return_pct'])['coin']}")
    
    # Save JSON
    json_path = "/tmp/rigorous_backtest_report.json"
    with open(json_path, "w") as f:
        json.dump(all_reports, f, default=str, indent=2)
    print(f"\n  Full report saved: {json_path}")

if __name__ == "__main__":
    main()
