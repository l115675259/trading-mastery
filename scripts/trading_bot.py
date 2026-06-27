#!/usr/bin/env python3
"""
Binance Futures Testnet Automated Trading Bot
Integrates: binpan (data) + trading-mastery skill (analysis) + ccxt (execution)

Usage:
  python trading_bot.py --simulate              # Scan all coins, show signals
  python trading_bot.py --trade --coin AVAX     # Place a SHORT order on AVAX
  python trading_bot.py --status                # Show positions & orders
  python trading_bot.py --close-all             # Close all positions
"""

import sys, os, json, argparse, time
from datetime import datetime

# Fix import path for rigorous_backtest module
sys.path.insert(0, '/tmp')

import pandas as pd
import numpy as np
import ccxt

# ── Config ───────────────────────────────────────────────────

PROXY = 'http://127.0.0.1:7890'

TESTNET_CONFIG = {
    'urls': {
        'api': {
            'public': 'https://testnet.binancefuture.com/fapi/v1',
            'private': 'https://testnet.binancefuture.com/fapi/v1',
        }
    },
    'options': {'defaultType': 'future'},
    'proxies': {'http': PROXY, 'https': PROXY},
    'timeout': 20000,
}

# Coins to scan with their historical stats
COIN_STATS = {
    "AVAXUSDT": {"WR": 58.0, "PF": 1.33, "rank": 1},
    "ADAUSDT":  {"WR": 53.1, "PF": 1.24, "rank": 2},
    "BTCUSDT":  {"WR": 53.1, "PF": 1.29, "rank": 3},
    "BNBUSDT":  {"WR": 53.1, "PF": 1.35, "rank": 4},
    "ETHUSDT":  {"WR": 52.0, "PF": 1.09, "rank": 5},
    "DOGEUSDT": {"WR": 52.0, "PF": 1.13, "rank": 6},
    "XRPUSDT":  {"WR": 51.0, "PF": 0.99, "rank": 7},
    "SUIUSDT":  {"WR": 40.0, "PF": 0.99, "rank": 8},
    "LINKUSDT": {"WR": 36.7, "PF": 0.71, "rank": 9},
    "SOLUSDT":  {"WR": 39.6, "PF": 0.61, "rank": 10},
}

# Strategy parameters (from rigorous backtest optimization)
STRATEGY = {
    "exit_days": 5,           # 5-day swing
    "quality_threshold": 40,  # Minimum quality score
    "min_pf": 1.05,           # Minimum historical profit factor
    "tp_pct": 5.0,            # Take profit at +5%
    "sl_pct": 3.0,            # Stop loss at -3%
    "leverage": 3,            # 3x leverage
    "position_size_usdt": 15, # 5 USDT × 3x = 15 USDT position
}

# ── Exchange Setup ────────────────────────────────────────────

def get_exchange(api_key: str = None, secret: str = None) -> ccxt.Exchange:
    """Create ccxt exchange instance for Binance Futures Testnet."""
    config = dict(TESTNET_CONFIG)
    if api_key and secret:
        config['apiKey'] = api_key
        config['secret'] = secret
    return ccxt.binance(config)

def get_public_exchange() -> ccxt.Exchange:
    """Public-only exchange for price checks."""
    ex = ccxt.binance(dict(TESTNET_CONFIG))
    ex.load_markets()
    return ex

# ── Signal Analysis (uses rigorous_backtest module) ──────────

def analyze_current_signal(coin: str):
    """Run full skill analysis on the latest bar of a coin."""
    from rigorous_backtest import (
        fetch_klines, compute_all_indicators, full_signal_analysis
    )
    
    try:
        df = fetch_klines(coin, limit=400)
    except Exception as e:
        return None, f"FETCH_FAIL: {e}"
    
    df = compute_all_indicators(df)
    i = len(df) - 1
    
    analysis = full_signal_analysis(df, i)
    if analysis is None:
        return None, "NO_SIGNAL"
    
    return analysis, df

def get_trade_plan(coin: str, close: float, trend: str):
    """Generate trade plan based on strategy parameters."""
    tp_mult = 1 - STRATEGY['tp_pct'] / 100 if trend == 'DOWN' else 1 + STRATEGY['tp_pct'] / 100
    sl_mult = 1 + STRATEGY['sl_pct'] / 100 if trend == 'DOWN' else 1 - STRATEGY['sl_pct'] / 100
    
    return {
        "side": "sell" if trend == 'DOWN' else "buy",
        "entry_price": round(close, 4),
        "tp_price": round(close * tp_mult, 4),
        "sl_price": round(close * sl_mult, 4),
        "leverage": STRATEGY['leverage'],
        "position_usdt": STRATEGY['position_size_usdt'],
    }

# ── CCXT Futures Helpers ──────────────────────────────────────

def get_ccxt_symbol(coin: str) -> str:
    """Convert BTCUSDT -> BTC/USDT:USDT (ccxt futures format)."""
    return f"{coin.replace('USDT', '')}/USDT:USDT"

def set_leverage(ex: ccxt.Exchange, symbol: str, leverage: int):
    """Set leverage for a futures symbol."""
    try:
        ex.set_leverage(leverage, symbol)
        print(f"  Leverage set to {leverage}x for {symbol}")
    except Exception as e:
        print(f"  Leverage warning: {e}")

def place_short_order(ex: ccxt.Exchange, symbol: str, plan: dict):
    """Place a SHORT market order with TP/SL on Binance Futures Testnet."""
    coin_ccxt = get_ccxt_symbol(symbol)
    
    # Set leverage
    set_leverage(ex, coin_ccxt, plan['leverage'])
    
    # Get market precision
    market = ex.market(coin_ccxt)
    amount = plan['position_usdt'] / plan['entry_price']
    amount = ex.amount_to_precision(coin_ccxt, amount)
    
    print(f"\n  ┌─ PLACING ORDER ─────────────────────────────────────")
    print(f"  │ Symbol:    {coin_ccxt}")
    print(f"  │ Side:      {plan['side'].upper()}")
    print(f"  │ Entry:     {plan['entry_price']}")
    print(f"  │ Amount:    {amount} ({plan['position_usdt']} USDT @ {plan['leverage']}x)")
    print(f"  │ TP:        {plan['tp_price']}")
    print(f"  │ SL:        {plan['sl_price']}")
    print(f"  └────────────────────────────────────────────────────")
    
    # Place market order
    try:
        order = ex.create_order(
            symbol=coin_ccxt,
            type='market',
            side=plan['side'],
            amount=float(amount),
            params={'reduceOnly': False}
        )
        print(f"\n  ✓ ORDER FILLED: {order['id']}")
        print(f"    Filled price: {order.get('average', order.get('price', 'N/A'))}")
    except Exception as e:
        print(f"\n  ✗ ORDER FAILED: {e}")
        return None
    
    # Place TP/SL orders
    try:
        tp_order = ex.create_order(
            symbol=coin_ccxt,
            type='take_profit_market',
            side='buy' if plan['side'] == 'sell' else 'sell',  # opposite
            amount=float(amount),
            params={
                'stopPrice': plan['tp_price'],
                'reduceOnly': True,
            }
        )
        print(f"  ✓ TP ORDER:    {tp_order['id']} @ {plan['tp_price']}")
    except Exception as e:
        print(f"  ✗ TP FAILED: {e}")
    
    try:
        sl_order = ex.create_order(
            symbol=coin_ccxt,
            type='stop_market',
            side='buy' if plan['side'] == 'sell' else 'sell',
            amount=float(amount),
            params={
                'stopPrice': plan['sl_price'],
                'reduceOnly': True,
            }
        )
        print(f"  ✓ SL ORDER:    {sl_order['id']} @ {plan['sl_price']}")
    except Exception as e:
        print(f"  ✗ SL FAILED: {e}")
    
    return order

# ── Commands ──────────────────────────────────────────────────

def cmd_simulate():
    """Scan all coins and show current signals."""
    print(f"\n{'='*80}")
    print(f"  SIGNAL SCAN — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  Strategy: 5d Swing | Q≥{STRATEGY['quality_threshold']} | PF≥{STRATEGY['min_pf']}")
    print(f"{'='*80}")
    
    print(f"\n  {'Coin':<12} {'Price':>10} {'Trend':>6} {'Q':>4} {'WR%':>6} {'PF':>6} {'ADX':>5} {'RSI':>5} {'Wave':<16} {'Action':<16} {'Signals'}")
    print(f"  {'-'*12} {'-'*10} {'-'*6} {'-'*4} {'-'*6} {'-'*6} {'-'*5} {'-'*5} {'-'*16} {'-'*16} {'-'*40}")
    
    actionable = []
    
    for coin, stats in COIN_STATS.items():
        analysis, status = analyze_current_signal(coin)
        
        if analysis is None:
            close = "?"
            trend = "?"
            q = 0
            wave = "?"
            signals = []
            action = f"SKIP({status[:10]})"
            adx = "?"
            rsi = "?"
        else:
            close = analysis['close']
            trend = analysis['trend']
            q = analysis['quality_score']
            wave = analysis['wave_position']
            signals = analysis['signals']
            adx = analysis.get('adx', '?')
            rsi = analysis.get('rsi_14', '?')
            
            if q >= STRATEGY['quality_threshold'] and trend != 'NEUTRAL' and stats['PF'] >= STRATEGY['min_pf']:
                action = f"★ {trend}" if trend else "★"
                actionable.append((coin, analysis))
            else:
                action = f"{trend} (skip)"
        
        sig_str = ','.join(signals[:3]) if signals else status
        stat = COIN_STATS.get(coin, {"WR": "?", "PF": "?"})
        print(f"  {coin:<12} {close:>10.4f} {trend:<6} {q:>4} {stat['WR']:>5.1f}% {stat['PF']:>5.2f} {str(adx):>5} {str(rsi):>5} {wave:<16} {action:<16} {sig_str}")
    
    print(f"\n  {'─'*60}")
    print(f"  ACTIONABLE SIGNALS: {len(actionable)}")
    for coin, a in sorted(actionable, key=lambda x: x[1]['quality_score'], reverse=True):
        plan = get_trade_plan(coin, a['close'], a['trend'])
        print(f"\n  ▸ {coin} | Q={a['quality_score']} | {a['trend']} | {a['wave_position']}")
        print(f"    Entry={plan['entry_price']}  TP={plan['tp_price']}  SL={plan['sl_price']}  Lev={plan['leverage']}x  Size={plan['position_usdt']}USDT")
        print(f"    Signals: {', '.join(a['signals'][:5])}")
    
    return actionable

def cmd_trade(coin: str, api_key: str = None, secret: str = None):
    """Place a trade on the best signal for a coin."""
    # First, do the analysis
    analysis, status = analyze_current_signal(coin)
    
    if analysis is None:
        print(f"  Cannot analyze {coin}: {status}")
        return
    
    stat = COIN_STATS.get(coin, {"WR": 0, "PF": 0})
    
    print(f"\n  Analysis for {coin}:")
    print(f"    Price:   {analysis['close']}")
    print(f"    Trend:   {analysis['trend']} (strength {analysis['trend_strength']}/4)")
    print(f"    Quality: {analysis['quality_score']}")
    print(f"    Wave:    {analysis['wave_position']}")
    print(f"    Signals: {', '.join(analysis['signals'])}")
    print(f"    History: WR={stat['WR']}% PF={stat['PF']}")
    
    # Validate strategy conditions
    if analysis['quality_score'] < STRATEGY['quality_threshold']:
        print(f"\n  ✗ REJECTED: Quality {analysis['quality_score']} < {STRATEGY['quality_threshold']}")
        return
    if analysis['trend'] == 'NEUTRAL':
        print(f"\n  ✗ REJECTED: No clear trend direction")
        return
    if stat['PF'] < STRATEGY['min_pf']:
        print(f"\n  ✗ REJECTED: Historical PF {stat['PF']} < {STRATEGY['min_pf']}")
        return
    
    plan = get_trade_plan(coin, analysis['close'], analysis['trend'])
    
    # Connect to exchange
    if not api_key or not secret:
        print("\n  ✗ No API keys provided. Use --api-key and --api-secret")
        print("    Get them from: https://testnet.binancefuture.com → API Management")
        return
    
    ex = get_exchange(api_key, secret)
    try:
        ex.load_markets()
        print(f"\n  Connected to Binance Futures Testnet ✓")
    except Exception as e:
        print(f"\n  ✗ Connection failed: {e}")
        return
    
    # Place order
    place_short_order(ex, coin, plan)

def cmd_status(api_key: str = None, secret: str = None):
    """Show current positions and open orders."""
    if not api_key or not secret:
        print("  No API keys. Use --api-key and --api-secret")
        return
    
    ex = get_exchange(api_key, secret)
    ex.load_markets()
    
    print(f"\n{'='*60}")
    print(f"  POSITIONS — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'='*60}")
    
    try:
        positions = ex.fetch_positions()
        active = [p for p in positions if float(p.get('contracts', 0)) != 0]
        if not active:
            print("  No open positions.")
        for p in active:
            pnl = float(p.get('unrealizedPnl', 0))
            pnl_pct = float(p.get('percentage', 0))
            side = "SHORT" if float(p.get('contracts', 0)) < 0 else "LONG"
            print(f"  {p['symbol']:<15} {side:<6} Size={abs(float(p.get('contracts',0))):.4f} "
                  f"Entry={float(p.get('entryPrice',0)):.4f} "
                  f"PnL={pnl:+.4f} ({pnl_pct:+.2f}%)")
    except Exception as e:
        print(f"  Error: {e}")
    
    print(f"\n  ORDERS:")
    try:
        orders = ex.fetch_open_orders()
        if not orders:
            print("  No open orders.")
        for o in orders:
            print(f"  {o['symbol']:<15} {o['side']:<6} {o['type']:<20} "
                  f"Qty={o.get('amount', '?'):<10} Price={o.get('price', o.get('stopPrice', '?'))}")
    except Exception as e:
        print(f"  Error: {e}")

def cmd_close_all(api_key: str = None, secret: str = None):
    """Close all open positions."""
    if not api_key or not secret:
        print("  No API keys.")
        return
    
    ex = get_exchange(api_key, secret)
    ex.load_markets()
    
    positions = ex.fetch_positions()
    active = [p for p in positions if float(p.get('contracts', 0)) != 0]
    
    if not active:
        print("  No open positions to close.")
        return
    
    for p in active:
        sym = p['symbol']
        side = 'buy' if float(p.get('contracts', 0)) < 0 else 'sell'
        amount = abs(float(p.get('contracts', 0)))
        try:
            ex.create_order(sym, 'market', side, amount, params={'reduceOnly': True})
            print(f"  Closed {sym}: {side} {amount}")
        except Exception as e:
            print(f"  Failed to close {sym}: {e}")

# ── Main ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Binance Futures Testnet Trading Bot')
    parser.add_argument('--simulate', '-s', action='store_true', help='Scan all coins for signals')
    parser.add_argument('--trade', '-t', action='store_true', help='Place a trade')
    parser.add_argument('--status', action='store_true', help='Show positions & orders')
    parser.add_argument('--close-all', action='store_true', help='Close all positions')
    parser.add_argument('--coin', '-c', type=str, help='Coin to trade (e.g. AVAXUSDT)')
    parser.add_argument('--api-key', type=str, help='Binance Testnet API Key')
    parser.add_argument('--api-secret', type=str, help='Binance Testnet API Secret')
    args = parser.parse_args()
    
    if args.simulate:
        cmd_simulate()
    elif args.trade:
        if not args.coin:
            print("  Use --coin AVAXUSDT to specify which coin to trade")
            return
        cmd_trade(args.coin.upper(), args.api_key, args.api_secret)
    elif args.status:
        cmd_status(args.api_key, args.api_secret)
    elif args.close_all:
        cmd_close_all(args.api_key, args.api_secret)
    else:
        parser.print_help()
        print("\n  Quick start:")
        print("    python trading_bot.py --simulate")
        print("    python trading_bot.py --trade --coin AVAXUSDT --api-key KEY --api-secret SECRET")
        print("    python trading_bot.py --status --api-key KEY --api-secret SECRET")

if __name__ == '__main__':
    main()
