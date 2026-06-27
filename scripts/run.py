#!/usr/bin/env python3
"""
统一入口 — 跨环境自愈 + 模式路由
====================================
用法：
  python run.py live AVAXUSDT            # 实时分析单币
  python run.py backtest --coins BTC,ETH  # 批量回测
  python run.py scan --coins top10        # 快速扫描信号

环境自愈流程：
  Step 1: 查找 Python 3.12+（brew/conda/system）
  Step 2: 检查并自动安装缺失包
  Step 3: 配置代理（7890 > 1087 > 直连）
  Step 4: 验证 Binance 连通
  Step 5: 执行任务
"""

import os, sys, subprocess, json, time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


# ═══════════════════════════════ Step 1: 查找 Python ═══════════════════════════════

def _find_python() -> str:
    """返回可用的 Python 3.12+ 路径，找不到则退出。"""
    current = sys.executable
    try:
        v = sys.version_info
        if v.major == 3 and v.minor >= 12:
            return current
    except Exception:
        pass

    # 搜索候选
    candidates = [
        "/opt/homebrew/bin/python3",
        "/opt/homebrew/bin/python3.14",
        "/opt/homebrew/bin/python3.13",
        "/opt/homebrew/bin/python3.12",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
        "/opt/anaconda3/bin/python3",
    ]
    # 也搜 brew 的所有 python3.x
    import glob
    for p in glob.glob("/opt/homebrew/bin/python3.*"):
        if p not in candidates:
            candidates.append(p)

    for c in candidates:
        try:
            result = subprocess.run([c, "-c",
                "import sys; v=sys.version_info; "
                "sys.exit(0 if v.major==3 and v.minor>=12 else 1)"],
                capture_output=True, timeout=5)
            if result.returncode == 0:
                print(f"  [env] Using Python: {c}")
                return c
        except Exception:
            continue

    print("ERROR: No Python 3.12+ found. Install it:")
    print("  brew install python@3.14")
    print("  or:  https://www.python.org/downloads/")
    sys.exit(1)


# ═══════════════════════════════ Step 2: 检查依赖 ═══════════════════════════════

def _check_deps(python: str) -> bool:
    """检查所需包，缺失则自动安装。返回 True 表示一切就绪。"""
    required = {
        "binpan": "binpan",
        "pandas": "pandas",
        "numpy": "numpy",
        "requests": "requests",
    }
    missing = []
    for pkg, mod in required.items():
        try:
            result = subprocess.run(
                [python, "-c", f"import {mod}"],
                capture_output=True, timeout=10)
            if result.returncode != 0:
                missing.append(pkg)
        except Exception:
            missing.append(pkg)

    if not missing:
        return True

    print(f"  [env] Missing packages: {', '.join(missing)}")
    print(f"  [env] Installing...")
    try:
        subprocess.run(
            [python, "-m", "pip", "install", "--break-system-packages"]
            + missing,
            check=True, capture_output=True, timeout=120)
        print(f"  [env] Packages installed.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  [env] Install failed: {e.stderr.decode() if e.stderr else e}")
        print(f"  [env] Manual install:")
        print(f"    {python} -m pip install --break-system-packages {' '.join(missing)}")
        return False


# ═══════════════════════════════ Step 3: 代理配置 ═══════════════════════════════

def _setup_proxy() -> bool:
    """探测并配置代理。返回 True 表示 Binance 可达。"""
    if os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy"):
        return _test_binance()

    proxies = [
        ("http://127.0.0.1:7890", "http://127.0.0.1:7890"),
        ("http://127.0.0.1:1087", "http://127.0.0.1:1087"),
    ]

    for http_p, https_p in proxies:
        os.environ["HTTP_PROXY"] = http_p
        os.environ["HTTPS_PROXY"] = https_p
        os.environ["http_proxy"] = http_p
        os.environ["https_proxy"] = https_p
        if _test_binance():
            print(f"  [env] Proxy OK: {http_p}")
            return True

    # 直连
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(k, None)
    if _test_binance():
        print(f"  [env] Direct connection OK")
        return True

    print("  [env] Cannot reach Binance. Check network/proxy.")
    return False


def _test_binance() -> bool:
    try:
        import urllib.request
        req = urllib.request.Request("https://api.binance.com/api/v3/ping", None,
            headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=8)
        return resp.status == 200 and resp.read() == b'{}'
    except Exception:
        return False


# ═══════════════════════════════ Step 4+5: 引导 ───────────────────────────────

def _show_usage():
    print("""
  Usage:
    python run.py live SYMBOL              # 实时分析
    python run.py backtest --coins C1,C2   # 批量回测
    python run.py scan --coins top10       # 快速扫描
""")


# ═══════════════════════════════ main ─────────────────────────────────────────

def main():
    print("\n  Trading Mastery Engine — Bootstrap\n")

    # Step 1-3: 环境自愈
    python = _find_python()
    if not _check_deps(python):
        sys.exit(1)
    if not _setup_proxy():
        sys.exit(1)

    # Step 5: 添加 scripts 目录到 path
    scripts_dir = str(SKILL_DIR / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    print(f"  [env] All checks passed.\n")

    # 解析命令
    if len(sys.argv) < 2:
        _show_usage()
        sys.exit(0)

    mode = sys.argv[1].lower()

    if mode == "live":
        symbol = sys.argv[2] if len(sys.argv) > 2 else "AVAXUSDT"
        print(f"  [live] Analyzing {symbol.upper()}...")
        print(f"  [live] Python computes data → LLM analyzes → Decision")
        from data_pipeline import get_analysis_data
        data = get_analysis_data(symbol.upper(), interval="1d", limit=120)
        # Save for LLM to read
        out_path = f"/tmp/{symbol.upper()}_analysis_data.json"
        with open(out_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"  [live] Data ready: {out_path}")
        print(f"  [live] Real bars: {len(data.get('recent_bars',[]))}")
        print(f"  [live] Columns: {len(data.get('columns_available',[]))}")
        print(f"\n  === LLM ANALYSIS PROTOCOL ===")
        print(f"  Protocol: {SKILL_DIR}/references/LLM_ANALYSIS_PROMPT.md")
        print(f"  Data: {out_path}")
        print(f"  The LLM must now read both and execute Phase 1→4.")

    elif mode == "backtest":
        coins_str = "AVAXUSDT,ADAUSDT,BTCUSDT"
        for a in sys.argv[2:]:
            if a.startswith("--coins="):
                coins_str = a.split("=", 1)[1]
            elif a == "--coins" and sys.argv.index(a) + 1 < len(sys.argv):
                coins_str = sys.argv[sys.argv.index(a) + 1]
        coins = [c.strip().upper() for c in coins_str.split(",")]
        print(f"  [backtest] Coins: {coins}")
        print(f"  [backtest] Python fetches data + computes indicators.")
        print(f"  [backtest] LLM must analyze each candidate signal.")
        print(f"  [backtest] Then BacktestEngine simulates trades.")

        from data_pipeline import fetch_and_compute
        from backtest_engine import BacktestEngine

        for coin in coins:
            try:
                df = fetch_and_compute(coin, "1d", limit=400)
                real = df[df["close"].notna()]
                print(f"  [backtest] {coin}: {len(real)} bars, {df.shape[1]} cols")
                # Save for LLM batch analysis
                out = f"/tmp/{coin}_backtest_data.json"
                df_out = real.copy()
                df_out.index = df_out.index.astype(str)
                df_out.to_json(out, orient="records", date_format="iso")
                print(f"    Saved → {out}")
            except Exception as e:
                print(f"    ERROR: {e}")

        print(f"\n  [backtest] Data ready for LLM analysis.")
        print(f"  [backtest] LLM must output signals as JSON for BacktestEngine.")

    elif mode == "scan":
        print(f"  [scan] Scanning for current signals...")
        print(f"  [scan] Python computes data → LLM scans each coin → signals list")

        from data_pipeline import get_analysis_data
        coins = ["AVAXUSDT","ADAUSDT","BTCUSDT","ETHUSDT","BNBUSDT",
                 "DOGEUSDT","XRPUSDT","LINKUSDT","SOLUSDT","SUIUSDT"]
        for coin in coins:
            try:
                data = get_analysis_data(coin, interval="1d", limit=60)
                s = data.get("summary", {})
                print(f"  {coin}: price={s.get('price')} adx={s.get('adx')} "
                      f"ema50={s.get('ema_50')} ema100={s.get('ema_100')} "
                      f"rsi={s.get('rsi_14')} st_trend={s.get('st_trend')}")
            except Exception as e:
                print(f"  {coin}: ERROR - {e}")

        print(f"\n  [scan] LLM must now evaluate each coin for signals.")

    else:
        _show_usage()


if __name__ == "__main__":
    main()
