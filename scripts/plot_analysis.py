#!/usr/bin/env python3
"""Generate analysis charts with indicators, S/R, and trade markers.

Corresponds to trading-mastery L2 (Technical Analysis visualization).
Uses binpan's Plotly integration for interactive charts.

Usage:
    python plot_analysis.py data_with_indicators.csv
    python plot_analysis.py data_with_indicators.csv --show-sr
"""

import argparse
import sys

import pandas as pd
import numpy as np

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False


# ═══════════════════════════════════════════════════════════════
# Support & Resistance via K-Means clustering
# ═══════════════════════════════════════════════════════════════

def detect_sr_kmeans(df: pd.DataFrame, n_clusters: int = 5) -> list[float]:
    """Detect support/resistance levels using K-Means on price highs and lows.

    If scikit-learn is available, uses K-Means (Nison binpan integration).
    Otherwise falls back to simple swing high/low clustering.
    """
    try:
        from sklearn.cluster import KMeans

        # Use swing highs and lows
        highs = df["High"].values.reshape(-1, 1)
        lows = df["Low"].values.reshape(-1, 1)
        all_points = np.vstack([highs, lows])

        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        kmeans.fit(all_points)
        levels = sorted(kmeans.cluster_centers_.flatten().tolist())
        return levels

    except ImportError:
        # Fallback: simple percentile-based levels
        levels = []
        close = df["Close"].values
        for pct in [5, 25, 50, 75, 95]:
            levels.append(float(np.percentile(close, pct)))
        return sorted(set(levels))


# ═══════════════════════════════════════════════════════════════
# Chart generation
# ═══════════════════════════════════════════════════════════════

def plot_analysis(
    df: pd.DataFrame,
    title: str = "Trading Analysis",
    show_sr: bool = True,
    sr_levels: list[float] | None = None,
) -> go.Figure:
    """Create an interactive analysis chart.

    Args:
        df: DataFrame with OHLCV and computed indicators.
        title: Chart title.
        show_sr: Show support/resistance levels.
        sr_levels: Pre-computed S/R levels. If None, auto-detected.
    """
    if not HAS_PLOTLY:
        raise ImportError("plotly is required. Install: pip install plotly")

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.55, 0.25, 0.20],
        subplot_titles=(title, "RSI(14) + Volume", "MACD"),
    )

    # ── Row 1: Candlestick + MAs + Bollinger + S/R ──
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name="Price",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        ),
        row=1, col=1,
    )

    # Moving averages
    for col, color, width in [("ema_50", "#ff9800", 1.5),
                                ("ema_100", "#2196f3", 1.5),
                                ("ema_200", "#9c27b0", 1)]:
        if col in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df.index, y=df[col],
                    mode="lines", name=col.upper(),
                    line=dict(color=color, width=width),
                ),
                row=1, col=1,
            )

    # Bollinger Bands
    if "bb_upper" in df.columns and "bb_lower" in df.columns:
        for bb_col, bb_color in [("bb_upper", "rgba(158,158,158,0.3)"),
                                   ("bb_lower", "rgba(158,158,158,0.3)")]:
            fig.add_trace(
                go.Scatter(
                    x=df.index, y=df[bb_col],
                    mode="lines", name=bb_col.upper(),
                    line=dict(color="#9e9e9e", width=0.8, dash="dot"),
                    showlegend=False,
                ),
                row=1, col=1,
            )

    # Supertrend
    if "st_value" in df.columns:
        colors = ["#26a69a" if t == 1 else "#ef5350"
                  for t in df.get("st_trend", pd.Series([1] * len(df)))]
        fig.add_trace(
            go.Scatter(
                x=df.index, y=df["st_value"],
                mode="lines", name="Supertrend",
                line=dict(color="#ff5722", width=1.2),
            ),
            row=1, col=1,
        )

    # Ichimoku cloud
    if "ichimoku_senkou_a" in df.columns and "ichimoku_senkou_b" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df.index, y=df["ichimoku_senkou_a"],
                mode="lines", name="Senkou A",
                line=dict(color="rgba(76,175,80,0.3)", width=0),
                showlegend=False,
            ),
            row=1, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df.index, y=df["ichimoku_senkou_b"],
                mode="lines", name="Senkou B",
                line=dict(color="rgba(244,67,54,0.3)", width=0),
                fill="tonexty",
                fillcolor="rgba(76,175,80,0.08)",
                showlegend=False,
            ),
            row=1, col=1,
        )

    # Support / Resistance levels
    if show_sr:
        if sr_levels is None:
            sr_levels = detect_sr_kmeans(df)
        for level in sr_levels:
            fig.add_hline(
                y=level, line_dash="dash", line_color="rgba(255,255,255,0.3)",
                row=1, col=1,
                annotation_text=f"{level:.1f}",
                annotation_position="right",
            )

    # ── Row 2: RSI + Volume ──
    if "rsi_14" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df.index, y=df["rsi_14"],
                mode="lines", name="RSI(14)",
                line=dict(color="#7c4dff", width=1.5),
            ),
            row=2, col=1,
        )
        # Overbought / oversold lines
        for val, color in [(70, "#ef5350"), (30, "#26a69a")]:
            fig.add_hline(
                y=val, line_dash="dash", line_color=color,
                opacity=0.5, row=2, col=1,
            )

    if "Volume" in df.columns:
        # Normalize volume for overlay on same row (as secondary y)
        vol_max = df["Volume"].max()
        vol_norm = df["Volume"] / vol_max * 100 * 0.3 if vol_max > 0 else df["Volume"]
        fig.add_trace(
            go.Bar(
                x=df.index, y=vol_norm,
                name="Volume (scaled)",
                marker=dict(color="rgba(158,158,158,0.5)"),
                yaxis="y4",
            ),
            row=2, col=1,
        )
        # Use secondary y-axis for volume
        fig.update_layout(
            yaxis4=dict(
                title="", overlaying="y2", side="right",
                showticklabels=False,
            )
        )

    fig.add_hline(y=50, line_dash="dot", line_color="gray",
                  opacity=0.3, row=2, col=1)

    # ── Row 3: MACD ──
    if "macd_dif" in df.columns and "macd_dea" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df.index, y=df["macd_dif"],
                mode="lines", name="DIF",
                line=dict(color="#42a5f5", width=1.2),
            ),
            row=3, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df.index, y=df["macd_dea"],
                mode="lines", name="DEA",
                line=dict(color="#ff7043", width=1.2),
            ),
            row=3, col=1,
        )
        if "macd_hist" in df.columns:
            hist_colors = ["#26a69a" if v >= 0 else "#ef5350"
                           for v in df["macd_hist"]]
            fig.add_trace(
                go.Bar(
                    x=df.index, y=df["macd_hist"],
                    name="Histogram",
                    marker=dict(color=hist_colors),
                ),
                row=3, col=1,
            )

    fig.add_hline(y=0, line_dash="dot", line_color="gray",
                  opacity=0.5, row=3, col=1)

    # ── Layout ──
    fig.update_layout(
        template="plotly_dark",
        height=900,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=20, r=20, t=60, b=20),
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="RSI", row=2, col=1, range=[0, 100])
    fig.update_yaxes(title_text="MACD", row=3, col=1)

    return fig


def main():
    parser = argparse.ArgumentParser(
        description="Generate analysis chart with indicators and S/R"
    )
    parser.add_argument("input", help="CSV with OHLCV + indicators")
    parser.add_argument("--title", default="Trading Analysis",
                        help="Chart title")
    parser.add_argument("--show-sr", action="store_true", default=True,
                        help="Show support/resistance levels")
    parser.add_argument("--output", "-o", help="Save to HTML file")
    args = parser.parse_args()

    if not HAS_PLOTLY:
        print("Error: plotly not installed. Run: pip install plotly kaleido",
              file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(args.input, index_col=0, parse_dates=True)
    print(f"Plotting {len(df)} candles...", file=sys.stderr)

    fig = plot_analysis(df, title=args.title, show_sr=args.show_sr)

    if args.output:
        fig.write_html(args.output)
        print(f"Chart saved to {args.output}")
    else:
        fig.show()


if __name__ == "__main__":
    main()
