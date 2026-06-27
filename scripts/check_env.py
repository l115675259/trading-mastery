#!/usr/bin/env python3
"""Environment checker & bootstrapper for Trading Mastery skill."""

import sys, subprocess, os

def check_python():
    v = sys.version_info
    ok = v >= (3, 12)
    print(f"  Python {v.major}.{v.minor}.{v.micro} — {'✓' if ok else '✗ NEED 3.12+'}  [{sys.executable}]")
    return ok

def check_package(name, import_name=None):
    try:
        __import__(import_name or name)
        print(f"  {name:<20} ✓")
        return True
    except ImportError:
        print(f"  {name:<20} ✗ missing")
        return False

def check_proxy():
    import urllib.request
    try:
        proxy = os.environ.get('HTTP_PROXY', 'http://127.0.0.1:7890')
        os.environ['HTTP_PROXY'] = proxy
        os.environ['HTTPS_PROXY'] = proxy
        
        req = urllib.request.Request('https://fapi.binance.com/fapi/v1/ping', method='GET')
        proxy_handler = urllib.request.ProxyHandler({'http': proxy, 'https': proxy})
        opener = urllib.request.build_opener(proxy_handler)
        resp = opener.open(req, timeout=8)
        print(f"  Binance FAPI ping:  ✓ (proxy={proxy})")
        return True
    except Exception as e:
        print(f"  Binance FAPI ping:  ✗ ({e})")
        return False

def check_binance_data():
    try:
        import binpan
        sym = binpan.Symbol(symbol='btcusdt', tick_interval='1d', time_zone='UTC', limit=2)
        df = sym.df
        if df is not None and len(df) > 0:
            print(f"  Binance data fetch: ✓ ({len(df)} BTC bars)")
            return True
    except Exception as e:
        print(f"  Binance data fetch: ✗ ({e})")
    return False

def print_install_guide(missing):
    print(f"\n{'='*55}")
    print(f"  INSTALL GUIDE")
    print(f"{'='*55}")
    pip = f'"{sys.executable}" -m pip'
    print(f"  pip: {pip} install --break-system-packages")
    print(f"  packages: {' '.join(missing)}")
    
def main():
    print(f"Trading Mastery — Environment Check\n")
    all_ok = True
    
    print(f"[1/4] Python version")
    all_ok &= check_python()
    
    print(f"\n[2/4] Required packages")
    pkgs = [
        ('binpan', 'binpan'),
        ('pandas', 'pandas'),
        ('numpy', 'numpy'),
        ('backtrader', 'backtrader'),
        ('ccxt', 'ccxt'),
        ('requests', 'requests'),
    ]
    missing = []
    for name, imp in pkgs:
        if not check_package(name, imp):
            missing.append(name)
            all_ok = False
    
    print(f"\n[3/4] Network & proxy")
    all_ok &= check_proxy()
    
    print(f"\n[4/4] Binance data access")
    all_ok &= check_binance_data()
    
    if missing:
        print_install_guide(missing)
    
    print(f"\n{'='*55}")
    if all_ok:
        print(f"  ✓ ALL CHECKS PASSED — ready to trade")
    else:
        print(f"  ✗ Some checks failed — fix above then re-run")
    print(f"{'='*55}")
    return 0 if all_ok else 1

if __name__ == '__main__':
    sys.exit(main())
