#!/usr/bin/env python3
"""
数据管道 — 统一数据层
================================
职责：拉取 K 线 → 计算全部技术指标 → 标准化输出
不做任何分析判断。分析交给 LLM。

覆盖所有 binpan 黑坑：
  - 列名大写（内部统一转小写 open/high/low/close/volume）
  - EMA 只接受单窗口（封装为逐个调用）
  - pandas_ta 已移除（ADX/SuperTrend/Ichimoku 全部手动计算）
  - 代理自动检测配置

用法：
  from data_pipeline import fetch_and_compute, get_analysis_data
  df = fetch_and_compute("AVAXUSDT", "1d", 120)
  data = get_analysis_data("AVAXUSDT", "1d", 120)
"""

import os, sys, json, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ═══════════════════════════ 代理自动配置 ═══════════════════════════

def _auto_proxy():
    """探测可用代理：环境变量 > 127.0.0.1:7890 > 直连"""
    if os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy"):
        return
    candidates = [("http://127.0.0.1:7890", "http://127.0.0.1:7890"),
                  ("http://127.0.0.1:1087", "http://127.0.0.1:1087")]
    for http_p, https_p in candidates:
        try:
            import urllib.request
            ph = urllib.request.ProxyHandler({"http": http_p, "https": https_p})
            op = urllib.request.build_opener(ph)
            resp = op.open(urllib.request.Request(
                "https://api.binance.com/api/v3/ping", None), timeout=5)
            if resp.status == 200:
                os.environ["HTTP_PROXY"] = http_p
                os.environ["HTTPS_PROXY"] = https_p
                os.environ["http_proxy"] = http_p
                os.environ["https_proxy"] = https_p
                return
        except Exception:
            continue

_auto_proxy()


# ═══════════════════════════ 底层辅助 ═══════════════════════════

def _ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def _sma(series, period):
    return series.rolling(window=period).mean()

def _true_range(df):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    return pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)


# ═══════════════════════════ DataPipeline ═══════════════════════════

class DataPipeline:
    """统一数据管道"""

    @staticmethod
    def fetch(symbol: str, interval: str = "1d", limit: int = 120,
              tz: str = "Asia/Shanghai") -> pd.DataFrame:
        """从 Binance 拉取 K 线。返回列名小写标准化的 DataFrame。"""
        import binpan
        sym = binpan.Symbol(
            symbol=symbol.upper(), tick_interval=interval,
            time_zone=tz, limit=limit)
        df = sym.df.copy()
        # 列名标准化：大写 → 小写
        rm = {}
        for col in df.columns:
            lo = col.lower()
            if lo in ("open","high","low","close","volume"):
                rm[col] = lo
        if rm:
            df = df.rename(columns=rm)
        for c in ("open","high","low","close","volume"):
            if c not in df.columns:
                raise KeyError(f"Missing column '{c}'. Got: {list(df.columns)}")
        return df

    @staticmethod
    def compute_all(df: pd.DataFrame) -> pd.DataFrame:
        """计算全部技术指标（35+ 列）。输入需含 open/high/low/close/volume。"""
        df = df.copy()
        c = df["close"]; h = df["high"]; l = df["low"]
        tr = _true_range(df)
        df["tr"] = tr

        # 均线
        for p in (12, 26, 50, 100):
            df[f"ema_{p}"] = _ema(c, p)
        for p in (20, 50, 100, 200):
            if len(df) >= p:
                df[f"sma_{p}"] = _sma(c, p)

        # MACD
        e12, e26 = _ema(c, 12), _ema(c, 26)
        df["macd_dif"] = e12 - e26
        df["macd_dea"] = _ema(df["macd_dif"], 9)
        df["macd_hist"] = 2 * (df["macd_dif"] - df["macd_dea"])

        # RSI(14)
        delta = c.diff(); gain = delta.clip(lower=0); loss = (-delta).clip(lower=0)
        df["rsi_14"] = 100 - 100 / (1 + _ema(gain,14) / _ema(loss,14).replace(0,np.nan))

        # Stochastic
        l14 = l.rolling(14).min(); h14 = h.rolling(14).max()
        df["stoch_k"] = 100 * (c - l14) / (h14 - l14)
        df["stoch_d"] = _sma(df["stoch_k"], 3)

        # ATR(20)
        df["atr_20"] = _ema(tr, 20)

        # Bollinger
        mid = _sma(c, 20); std = c.rolling(20).std()
        df["bb_mid"] = mid
        df["bb_upper"] = mid + 2*std
        df["bb_lower"] = mid - 2*std
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]

        # ADX(14) 手动
        up = h.diff(); down = -l.diff()
        pdm = np.where((up>down)&(up>0), up, 0)
        mdm = np.where((down>up)&(down>0), down, 0)
        atr14 = _ema(tr, 14)
        pdi = 100 * _ema(pd.Series(pdm, index=df.index), 14) / atr14
        mdi = 100 * _ema(pd.Series(mdm, index=df.index), 14) / atr14
        dx = 100 * abs(pdi - mdi) / (pdi + mdi + 0.0001)
        df["adx"] = _ema(dx, 14)
        df["plus_di"] = pdi
        df["minus_di"] = mdi

        # Supertrend(10,3)
        atr10 = _ema(tr,10); hl2 = (h+l)/2
        up_basic = hl2 + 3.0*atr10
        lo_basic = hl2 - 3.0*atr10
        up_band = pd.Series(np.nan, index=df.index)
        lo_band = pd.Series(np.nan, index=df.index)
        st = pd.Series(1, index=df.index)
        if len(df)>0:
            up_band.iloc[0] = up_basic.iloc[0] if pd.notna(up_basic.iloc[0]) else np.nan
            lo_band.iloc[0] = lo_basic.iloc[0] if pd.notna(lo_basic.iloc[0]) else np.nan
        for i in range(1, len(df)):
            up_band.iloc[i] = (up_basic.iloc[i]
                if pd.notna(up_basic.iloc[i]) and (
                   pd.isna(up_band.iloc[i-1]) or
                   up_basic.iloc[i] < up_band.iloc[i-1] or
                   c.iloc[i-1] > up_band.iloc[i-1])
                else up_band.iloc[i-1])
            lo_band.iloc[i] = (lo_basic.iloc[i]
                if pd.notna(lo_basic.iloc[i]) and (
                   pd.isna(lo_band.iloc[i-1]) or
                   lo_basic.iloc[i] > lo_band.iloc[i-1] or
                   c.iloc[i-1] < lo_band.iloc[i-1])
                else lo_band.iloc[i-1])
            st.iloc[i] = (
                1 if pd.notna(up_band.iloc[i-1]) and c.iloc[i] > up_band.iloc[i-1]
                else (-1 if pd.notna(lo_band.iloc[i-1]) and c.iloc[i] < lo_band.iloc[i-1]
                else st.iloc[i-1]))
        df["st_value"] = np.where(st==1, lo_band, up_band)
        df["st_trend"] = st

        # Heikin-Ashi
        df["ha_close"] = (df["open"] + h + l + c) / 4
        ha_open = pd.Series(np.nan, index=df.index)
        if len(df)>0:
            ha_open.iloc[0] = (df["open"].iloc[0] + c.iloc[0]) / 2
        for i in range(1, len(df)):
            ha_open.iloc[i] = (ha_open.iloc[i-1] + df["ha_close"].iloc[i-1]) / 2
        df["ha_open"] = ha_open
        df["ha_high"] = df[["high","ha_open","ha_close"]].max(axis=1)
        df["ha_low"]  = df[["low","ha_open","ha_close"]].min(axis=1)

        # Ichimoku (纯 pandas)
        df["tenkan"] = (h.rolling(9).max() + l.rolling(9).min()) / 2
        df["kijun"]  = (h.rolling(26).max() + l.rolling(26).min()) / 2
        df["senkou_a"] = ((df["tenkan"] + df["kijun"]) / 2).shift(26)
        df["senkou_b"] = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)

        # Difference Index (日式超买超卖)
        df["diff_idx_25"] = (c - _sma(c, 25)) / _sma(c, 25) * 100

        # 量比
        df["vol_sma_20"] = _sma(df["volume"], 20)
        df["volume_ratio"] = df["volume"] / df["vol_sma_20"]

        return df

    @staticmethod
    def summary(df: pd.DataFrame, bars: int = 15) -> dict:
        """生成 LLM 分析所需的数据摘要。
        包含最新 bar 的关键数值 + 最近 N 根 K 线的完整数据。"""
        real = df[df["close"].notna()]
        if len(real) == 0:
            return {"error": "No valid data"}
        latest = real.iloc[-1]

        def f(k, nd=4):
            v = latest.get(k)
            if pd.isna(v): return None
            return round(float(v), nd)

        summary_data = {
            "latest_date": str(latest.name),
            "price":    f("close"),
            "open":     f("open"),  "high": f("high"),  "low": f("low"),
            "volume":   f("volume", 0), "volume_ratio": f("volume_ratio", 2),
            # 趋势
            "ema_12": f("ema_12"), "ema_26": f("ema_26"),
            "ema_50": f("ema_50"), "ema_100": f("ema_100"),
            "sma_20": f("sma_20"), "sma_50": f("sma_50"),
            "adx":    f("adx"), "plus_di": f("plus_di"), "minus_di": f("minus_di"),
            "st_value": f("st_value"), "st_trend": f("st_trend", 0),
            # 动量
            "rsi_14": f("rsi_14"), "stoch_k": f("stoch_k"), "stoch_d": f("stoch_d"),
            "macd_dif": f("macd_dif"), "macd_dea": f("macd_dea"), "macd_hist": f("macd_hist"),
            # 波动
            "atr_20": f("atr_20"),
            "bb_lower": f("bb_lower"), "bb_mid": f("bb_mid"),
            "bb_upper": f("bb_upper"), "bb_width": f("bb_width", 4),
            # 日式
            "tenkan": f("tenkan"), "kijun": f("kijun"),
            "senkou_a": f("senkou_a"), "senkou_b": f("senkou_b"),
            "ha_open": f("ha_open"), "ha_close": f("ha_close"),
            "diff_idx_25": f("diff_idx_25", 2),
        }

        # 最近 N 根 K 线详情
        tail = real.tail(bars)
        detail_cols = [c for c in [
            "open","high","low","close","volume",
            "ema_12","ema_26","ema_50","ema_100",
            "sma_20","sma_50",
            "rsi_14","stoch_k","stoch_d",
            "macd_dif","macd_dea","macd_hist",
            "adx","plus_di","minus_di",
            "atr_20","bb_lower","bb_mid","bb_upper","bb_width",
            "st_value","st_trend",
            "tenkan","kijun","senkou_a","senkou_b",
            "ha_open","ha_high","ha_low","ha_close",
            "diff_idx_25","volume_ratio",
        ] if c in tail.columns]

        detail_rows = []
        for idx, row in tail.iterrows():
            r = {"date": str(idx)}
            for col in detail_cols:
                v = row[col]
                r[col] = (round(float(v), 6) if pd.notna(v) and not isinstance(v, (int,np.integer))
                          else (int(v) if isinstance(v, (int,np.integer)) and pd.notna(v)
                          else (None if pd.isna(v) else v)))
            detail_rows.append(r)

        return {"summary": summary_data, "recent_bars": detail_rows,
                "columns_available": detail_cols}

    @staticmethod
    def save(df: pd.DataFrame, path: str):
        df_out = df.copy()
        df_out.index = df_out.index.astype(str)
        df_out.to_json(path, orient="records", date_format="iso")
        return path


# ═══════════════════════════ 便捷函数 ═══════════════════════════

def fetch_and_compute(symbol: str, interval: str = "1d", limit: int = 120,
                      tz: str = "Asia/Shanghai") -> pd.DataFrame:
    """一步完成：拉取 + 全量指标计算"""
    dp = DataPipeline()
    df = dp.fetch(symbol, interval, limit, tz)
    return dp.compute_all(df)


def get_analysis_data(symbol: str, interval: str = "1d", limit: int = 120,
                      bars: int = 15) -> dict:
    """获取 LLM 分析所需的完整数据包"""
    df = fetch_and_compute(symbol, interval, limit)
    dp = DataPipeline()
    result = dp.summary(df, bars)
    result["symbol"] = symbol.upper()
    result["interval"] = interval
    return result


# ── CLI ──
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Data Pipeline")
    ap.add_argument("symbol", nargs="?", default="AVAXUSDT")
    ap.add_argument("--interval", "-i", default="1d")
    ap.add_argument("--limit", "-l", type=int, default=120)
    ap.add_argument("--save", "-s", help="保存 JSON 路径")
    ap.add_argument("--summary", action="store_true", help="输出摘要")
    args = ap.parse_args()

    df = fetch_and_compute(args.symbol, args.interval, args.limit)
    real = df[df["close"].notna()]
    print(f"  {args.symbol} {args.interval}: {len(real)} bars, {df.shape[1]} cols")

    if args.summary:
        dp = DataPipeline()
        print(json.dumps(dp.summary(df)["summary"], indent=2, default=str))
    elif args.save:
        DataPipeline().save(df, args.save)
        print(f"  Saved → {args.save}")
    else:
        DataPipeline()
        print(json.dumps(DataPipeline().summary(df)["summary"], indent=2, default=str))
