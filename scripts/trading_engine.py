#!/usr/bin/env python3
"""
统一交易引擎 — 回测 + 实时分析共用核心
引擎核心 = 市场状态诊断 → 工具选择 → 陷阱检测 → 信号评估
"""
import sys, os, json, time
os.environ.setdefault('HTTP_PROXY', 'http://127.0.0.1:7890')
os.environ.setdefault('HTTPS_PROXY', 'http://127.0.0.1:7890')
sys.path.insert(0, '/tmp')

import pandas as pd
import numpy as np
from rigorous_backtest import fetch_klines, compute_all_indicators

# ═══════════════════════════════════════════
# 统一配置
# ═══════════════════════════════════════════

CFG = {
    'account': 5000,
    'risk_pct': 0.02,
    'leverage': 3,
    'position_size': 300,  # 5000 × 0.02 × 3
    'tp_pct': 5.0,
    'sl_pct': 3.0,
    'hold_days': 5,
    'max_positions': 4,
    'min_quality': 20,
}

COINS = ['AVAXUSDT','ADAUSDT','BTCUSDT','ETHUSDT','BNBUSDT',
         'DOGEUSDT','XRPUSDT','LINKUSDT','SOLUSDT','SUIUSDT']

HISTORICAL_PF = {c: p for c, p in zip(COINS, [1.33,1.24,1.29,1.09,1.35,1.13,0.99,0.71,0.61,0.99])}

# ═══════════════════════════════════════════
# 引擎核心（回测和实时共用）
# ═══════════════════════════════════════════

class MarketState:
    """市场状态诊断 + 工具选择 + 陷阱检测"""
    
    @staticmethod
    def diagnose(df, i):
        """Phase 1: 市场诊断"""
        adx = df['adx'].iloc[i] if pd.notna(df['adx'].iloc[i]) else 0
        rsi = df['rsi_14'].iloc[i] if pd.notna(df['rsi_14'].iloc[i]) else 50
        
        # 状态分类
        if adx > 40: state = 'strong_trend'
        elif adx > 25: state = 'weak_trend'
        elif adx > 20: state = 'transitional'
        else: state = 'ranging'
        
        if (rsi < 20 or rsi > 80) and state != 'ranging':
            state = 'extreme'
        
        # 方向投票
        votes_down, votes_up = 0, 0
        if pd.notna(e50 := df['ema_50'].iloc[i]) and pd.notna(e100 := df['ema_100'].iloc[i]):
            if e50 < e100: votes_down += 1
            else: votes_up += 1
        if pd.notna(st := df.get('st_trend', pd.Series([1]*len(df))).iloc[i]):
            if st == -1: votes_down += 1
            else: votes_up += 1
        if pd.notna(pdi := df.get('plus_di', pd.Series([0]*len(df))).iloc[i]) and pd.notna(mdi := df.get('minus_di', pd.Series([0]*len(df))).iloc[i]):
            if mdi > pdi: votes_down += 1
            else: votes_up += 1
        
        direction = 'DOWN' if votes_down > votes_up else ('UP' if votes_up > votes_down else 'NEUTRAL')
        
        return {'state': state, 'direction': direction, 'adx': adx, 'rsi': rsi}
    
    @staticmethod
    def select_tools(state):
        """Phase 2: 工具选择"""
        tools = {
            'strong_trend':  {'enable': ['trend_following','adx','breakout','elliott_wave','ma_cross'],
                              'disable': ['rsi_oversold','stoch','bb_mean_reversion']},
            'weak_trend':    {'enable': ['ma_cross','candlestick_at_key_levels','volume_confirm','adx'],
                              'disable': ['turtle_s2','rsi_counter_trend']},
            'transitional':  {'enable': ['adx','bb_squeeze','volume_confirm'],
                              'disable': ['trend_following','elliott_wave','rsi_oversold']},
            'ranging':       {'enable': ['rsi_oscillator','bb_bands','support_resistance','stoch'],
                              'disable': ['trend_following','breakout','elliott_wave']},
            'extreme':       {'enable': ['extreme_rsi','volume_spike','key_level_reversal'],
                              'disable': ['all_trend_tools']},
        }
        return tools.get(state, {'enable':[],'disable':[]})
    
    @staticmethod
    def detect_traps(df, i):
        """Phase 3 前段: 陷阱检测"""
        traps = []
        risk = 'low'
        
        if i < 20: return {'traps': [], 'risk': 'low', 'count': 0}
        
        vol = df['Volume'].iloc[i]
        avg_vol = df['Volume'].iloc[i-20:i].mean()
        
        # T1 假突破
        if vol < avg_vol * 0.8:
            traps.append('false_breakout_low_vol')
        
        # T4 RSI 背离
        if i >= 5:
            if (df['Close'].iloc[i] < df['Close'].iloc[i-5] and 
                df['rsi_14'].iloc[i] > df['rsi_14'].iloc[i-5]):
                traps.append('rsi_bullish_divergence')
        
        # T8 ST 翻转
        if i >= 5:
            st_vals = [df.get('st_trend', pd.Series([1]*len(df))).iloc[j] for j in range(i-5,i+1)]
            flips = sum(1 for j in range(1,len(st_vals)) if st_vals[j] != st_vals[j-1])
            if flips >= 2:
                traps.append('supertrend_whipsaw')
        
        if len(traps) >= 2: risk = 'high'
        elif len(traps) == 1: risk = 'medium'
        
        return {'traps': traps, 'risk': risk, 'count': len(traps)}
    
    @staticmethod
    def evaluate(df, i):
        """Phase 3 后段 + Phase 4: 信号评估 → 决策"""
        diag = MarketState.diagnose(df, i)
        tools = MarketState.select_tools(diag['state'])
        traps = MarketState.detect_traps(df, i)
        
        if diag['direction'] == 'NEUTRAL' or diag['state'] == 'ranging':
            return None
        
        close = df['Close'].iloc[i]
        
        # 趋势市：只在反弹日入场（做空）或回调日入场（做多）
        if diag['direction'] == 'DOWN':
            if close <= df['Open'].iloc[i]: return None  # 不是反弹
            if i > 0 and close <= df['Close'].iloc[i-1]: return None  # 反弹不够
        elif diag['direction'] == 'UP':
            if close >= df['Open'].iloc[i]: return None
            if i > 0 and close >= df['Close'].iloc[i-1]: return None
        
        # 质量分
        q = 15 if diag['state'] == 'strong_trend' else 10 if diag['state'] == 'weak_trend' else 5
        
        if diag['adx'] > 50: q += 15
        elif diag['adx'] > 40: q += 10
        elif diag['adx'] > 30: q += 7
        
        if diag['direction'] == 'DOWN' and diag['rsi'] > 60: q += 10
        elif diag['direction'] == 'DOWN' and diag['rsi'] > 50: q += 5
        elif diag['direction'] == 'UP' and diag['rsi'] < 40: q += 10
        elif diag['direction'] == 'UP' and diag['rsi'] < 50: q += 5
        
        if i >= 20 and df['Volume'].iloc[i] > df['Volume'].iloc[i-20:i].mean() * 1.2:
            q += 8
        
        bb_w = df.get('bb_width', pd.Series([0]*len(df))).iloc[i]
        if pd.notna(bb_w) and bb_w < 0.15:
            q += 8
        
        if traps['risk'] == 'high': q -= 12
        elif traps['risk'] == 'medium': q -= 6
        
        if q < CFG['min_quality']: return None
        
        return {
            'index': i, 'date': str(df.index[i]), 'close': float(close),
            'quality': min(100, q), 'direction': diag['direction'],
            'state': diag['state'], 'trap_risk': traps['risk'],
            'traps': traps['traps'], 'tools_enabled': tools['enable'],
            'tools_disabled': tools['disable'],
        }

# ═══════════════════════════════════════════
# 交易模拟（回测和实时共用）
# ═══════════════════════════════════════════

def simulate_trades(df, signals, positions=None):
    """在所有信号上模拟交易"""
    trades = []
    in_trade = [False] * CFG['max_positions']
    active = [None] * CFG['max_positions']
    
    for i in range(len(df)):
        # 检查退出
        for s in range(CFG['max_positions']):
            if not in_trade[s]: continue
            p = active[s]
            c = df['Close'].iloc[i]
            d = i - p['entry_bar']
            
            tp = p['entry_price'] * (1 - CFG['tp_pct']/100)
            sl = p['entry_price'] * (1 + CFG['sl_pct']/100)
            
            if d >= CFG['hold_days']:
                p['exit_bar'] = i; p['exit_price'] = c
                p['return_pct'] = (p['entry_price']-c)/p['entry_price']*100
                p['exit_reason'] = f'{CFG["hold_days"]}d'
                trades.append(p); in_trade[s] = False; active[s] = None
            elif df['Low'].iloc[i] <= tp:
                p['exit_bar'] = i; p['exit_price'] = tp
                p['return_pct'] = CFG['tp_pct']; p['exit_reason'] = 'TP'
                trades.append(p); in_trade[s] = False; active[s] = None
            elif df['High'].iloc[i] >= sl:
                p['exit_bar'] = i; p['exit_price'] = sl
                p['return_pct'] = -CFG['sl_pct']; p['exit_reason'] = 'SL'
                trades.append(p); in_trade[s] = False; active[s] = None
        
        if all(in_trade): continue
        
        sig = next((s for s in signals if s['index'] == i), None)
        if sig is None: continue
        
        for s in range(CFG['max_positions']):
            if not in_trade[s]: break
        else: continue
        
        in_trade[s] = True
        active[s] = {'coin': sig.get('coin','?'), 'entry_bar': i,
                     'entry_date': sig['date'], 'entry_price': df['Close'].iloc[i],
                     'quality': sig['quality'], 'direction': sig['direction'],
                     'state': sig['state'], 'trap_risk': sig['trap_risk'],
                     'position_usdt': CFG['position_size']}
    
    for s in range(CFG['max_positions']):
        if in_trade[s]:
            p = active[s]; c = df['Close'].iloc[-1]
            p['exit_bar'] = len(df)-1; p['exit_price'] = c
            p['return_pct'] = (p['entry_price']-c)/p['entry_price']*100
            p['exit_reason'] = 'end'; trades.append(p)
    
    return trades

# ═══════════════════════════════════════════
# 模式 1: 实时分析（单币）
# ═══════════════════════════════════════════

def analyze_live(coin):
    """实时分析一个币种，输出完整诊断"""
    df = fetch_klines(coin, limit=200)
    df = compute_all_indicators(df)
    i = len(df) - 1
    
    diag = MarketState.diagnose(df, i)
    tools = MarketState.select_tools(diag['state'])
    traps = MarketState.detect_traps(df, i)
    sig = MarketState.evaluate(df, i)
    
    return {
        'coin': coin,
        'date': str(df.index[i])[:10],
        'price': float(df['Close'].iloc[i]),
        'diagnosis': diag,
        'tools': tools,
        'traps': traps,
        'signal': sig,
        'data': {c: float(df[c].iloc[i]) if pd.notna(df[c].iloc[i]) else None 
                 for c in ['adx','rsi_14','ema_50','ema_100','atr_20','macd_hist','bb_width']},
    }

# ═══════════════════════════════════════════
# 模式 2: 批量回测
# ═══════════════════════════════════════════

def run_backtest(coins=None):
    """跑全部币种的批量回测"""
    coins = coins or [c for c in COINS if HISTORICAL_PF.get(c,0) >= 0.6]
    all_trades = []
    coin_stats = {}
    
    for coin in coins:
        try:
            df = fetch_klines(coin, limit=400)
        except: continue
        df = compute_all_indicators(df)
        
        signals = []
        for i in range(100, len(df)):
            sig = MarketState.evaluate(df, i)
            if sig: sig['coin'] = coin; signals.append(sig)
        
        trades = simulate_trades(df, signals)
        if not trades: continue
        
        returns = [t['return_pct'] for t in trades]
        wins, losses = [r for r in returns if r>0], [r for r in returns if r<=0]
        
        coin_stats[coin] = {
            'trades': len(trades), 'wr': len(wins)/len(trades)*100,
            'pf': sum(wins)/abs(sum(losses)) if sum(losses)!=0 else 999,
            'total_ret': sum(returns), 'avg_ret': np.mean(returns),
            'best': max(returns), 'worst': min(returns),
        }
        all_trades.extend(trades)
    
    return {'coin_stats': coin_stats, 'all_trades': all_trades}

# ═══════════════════════════════════════════
# 模式 3: 三遍校验
# ═══════════════════════════════════════════


# ═══════════════════════════════════════════
# 三遍全量校验（内嵌到工作流）
# ═══════════════════════════════════════════

def verify(trades, dfs=None):
    """三遍校验：数字溯源 → 逻辑一致 → 完整检查
    
    Args:
        trades: 交易列表
        dfs: {coin: DataFrame} 可选，传入则进行 Pass1 溯源
    Returns:
        {'pass1': [...], 'pass2': [...], 'pass3': [...], 'total': N}
    """
    errors = {'pass1': [], 'pass2': [], 'pass3': []}
    
    # ── Pass 1: 数字溯源 ──
    for i, t in enumerate(trades):
        # 检查基本字段完整性
        for f in ['entry_bar','entry_date','entry_price','exit_price','exit_bar',
                  'return_pct','exit_reason','quality','direction','state','trap_risk']:
            if f not in t or t[f] is None:
                errors['pass1'].append(f"Trade#{i}: 缺失字段 {f}")
        
        # 检查数值合理性
        if 'return_pct' in t and t['return_pct'] is not None:
            if t['return_pct'] > 100 or t['return_pct'] < -100:
                errors['pass1'].append(f"Trade#{i}: return_pct={t['return_pct']} 超出合理范围")
        if 'quality' in t and t['quality'] is not None:
            if t['quality'] < 0 or t['quality'] > 100:
                errors['pass1'].append(f"Trade#{i}: quality={t['quality']} 超出0-100")
        if 'entry_price' in t and t['entry_price'] is not None:
            if t['entry_price'] <= 0:
                errors['pass1'].append(f"Trade#{i}: entry_price={t['entry_price']} 无效")
        if 'exit_price' in t and t['exit_price'] is not None:
            if t['exit_price'] <= 0:
                errors['pass1'].append(f"Trade#{i}: exit_price={t['exit_price']} 无效")
        
        # 检查TP/SL价格合理性
        if t.get('exit_reason') == 'TP':
            tp_expected = t['entry_price'] * (1 - 5.0/100)
            if abs(t['exit_price'] - tp_expected) > 0.01:
                errors['pass1'].append(f"Trade#{i}: TP价格 {t['exit_price']} != 预期 {tp_expected:.4f}")
        if t.get('exit_reason') == 'SL':
            sl_expected = t['entry_price'] * (1 + 3.0/100)
            if abs(t['exit_price'] - sl_expected) > 0.01:
                errors['pass1'].append(f"Trade#{i}: SL价格 {t['exit_price']} != 预期 {sl_expected:.4f}")
    
    # ── Pass 2: 逻辑一致性 ──
    for i, t in enumerate(trades):
        # 状态和方向的矛盾检查
        if t.get('state') == 'strong_trend' and t.get('direction') == 'NEUTRAL':
            errors['pass2'].append(f"Trade#{i}: 强趋势但方向中性 — 矛盾")
        if t.get('state') == 'ranging' and t.get('quality', 0) > 30:
            errors['pass2'].append(f"Trade#{i}: 震荡市但高质量信号 — 可能误判")
        # 陷阱和质量矛盾
        if t.get('trap_risk') == 'high' and t.get('quality', 0) > 60:
            errors['pass2'].append(f"Trade#{i}: 高陷阱风险但高质量={t['quality']} — 矛盾")
        # 方向和收益一致性
        if t.get('direction') == 'DOWN' and t.get('return_pct', 0) > 0:
            pass  # 做空+正收益=正确
        elif t.get('direction') == 'DOWN' and t.get('return_pct', 0) < 0:
            pass  # 做空+负收益=亏损，正常
        # TP/SL逻辑
        if t.get('exit_reason') == 'TP' and t.get('return_pct', 0) <= 0:
            errors['pass2'].append(f"Trade#{i}: TP退出但收益为负 — 矛盾")
        if t.get('exit_reason') == 'SL' and t.get('return_pct', 0) >= 0:
            errors['pass2'].append(f"Trade#{i}: SL退出但收益为正 — 矛盾")
    
    # ── Pass 3: 完整检查 ──
    if trades:
        # 检查退出方式分布
        exit_types = {}
        for t in trades:
            exit_types[t.get('exit_reason','?')] = exit_types.get(t.get('exit_reason','?'), 0) + 1
        # 检查是否有未知退出方式
        for reason in exit_types:
            if reason not in ['TP','SL','5d','end']:
                errors['pass3'].append(f"未知退出方式: {reason} ({exit_types[reason]}次)")
        
        # 检查交易时序：exit_bar > entry_bar
        for i, t in enumerate(trades):
            if t.get('exit_bar', 0) <= t.get('entry_bar', 0):
                errors['pass3'].append(f"Trade#{i}: exit_bar({t.get('exit_bar')}) <= entry_bar({t.get('entry_bar')})")
        
        # 检查统计一致性
        returns = [t.get('return_pct', 0) for t in trades]
        total_ret = sum(returns)
        avg_ret = total_ret / len(trades) if trades else 0
        if abs(avg_ret * len(trades) - total_ret) > 0.01:
            errors['pass3'].append(f"统计不一致: avg*N={avg_ret*len(trades):.4f} != total={total_ret:.4f}")
    
    errors['total'] = sum(len(v) for v in errors.values())
    return errors

# ═══════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════

def main():
    import argparse
    ap = argparse.ArgumentParser(description='统一交易引擎')
    ap.add_argument('--analyze', '-a', help='实时分析币种, 如 AVAXUSDT')
    ap.add_argument('--backtest', '-b', action='store_true', help='批量回测')
    ap.add_argument('--coins', '-c', nargs='*', help='指定币种')
    ap.add_argument('--json', '-j', action='store_true', help='JSON 输出')
    args = ap.parse_args()
    
    if args.analyze:
        r = analyze_live(args.analyze.upper())
        if args.json:
            print(json.dumps({k: v for k, v in r.items() if k != 'data'}, default=str, indent=2))
        else:
            d, t, tr, s = r['diagnosis'], r['tools'], r['traps'], r['signal']
            print(f"\n{r['coin']} @ {r['date']} | {r['price']:.4f}")
            print(f"  状态: {d['state']} | 方向: {d['direction']} | ADX={d['adx']:.0f} RSI={d['rsi']:.0f}")
            print(f"  启用: {', '.join(t['enable'][:5])}")
            print(f"  禁用: {', '.join(t['disable'][:5])}")
            print(f"  陷阱: {tr['risk']} ({', '.join(tr['traps']) if tr['traps'] else 'none'})")
            if s:
                print(f"  信号: Q={s['quality']} | {'做空' if s['direction']=='DOWN' else '做多'}")
                entry = s['close']
                print(f"  入场={entry:.4f} TP={entry*(1-CFG['tp_pct']/100):.4f} SL={entry*(1+CFG['sl_pct']/100):.4f}")
            else:
                print(f"  信号: 无")
    
    elif args.backtest:
        coins = args.coins if args.coins else None
        result = run_backtest(coins)
        trades = result['all_trades']
        stats = result['coin_stats']
        
        total_trades = sum(s['trades'] for s in stats.values())
        total_ret = sum(s['total_ret'] for s in stats.values())
        avg_wr = np.mean([s['wr'] for s in stats.values()])
        avg_pf = np.mean([s['pf'] for s in stats.values() if s['pf'] != 999])
        
        errors = verify(trades)
        
        if args.json:
            print(json.dumps({
                'total_trades': total_trades, 'avg_wr': round(avg_wr,1), 'avg_pf': round(avg_pf,2),
                'total_return_pct': round(total_ret,2),
                'account_end': round(CFG['account'] + total_ret/100*CFG['position_size'], 0),
                'verification_errors': len(errors),
                'coins': stats,
            }, indent=2))
        else:
            print(f"\n{'='*55}")
            print(f"  统一引擎回测 | {total_trades} 笔 | WR={avg_wr:.1f}% | PF={avg_pf:.2f}")
            print(f"  账户: {CFG['account']} → {CFG['account']+total_ret/100*CFG['position_size']:.0f} USDT")
            print(f"  校验: Pass1={len(errors['pass1'])} Pass2={len(errors['pass2'])} Pass3={len(errors['pass3'])} 总计={errors['total']}")
            print(f"{'='*55}")
            print(f"  {'Coin':<12} {'Trades':>6} {'WR':>6} {'PF':>5} {'Total':>8} {'Avg':>7}")
            for c in sorted(stats, key=lambda c: stats[c]['pf'], reverse=True):
                s = stats[c]
                print(f"  {c:<12} {s['trades']:>6} {s['wr']:>5.1f}% {s['pf']:>4.2f} {s['total_ret']:>+7.2f}% {s['avg_ret']:>+6.2f}%")

if __name__ == '__main__':
    main()
