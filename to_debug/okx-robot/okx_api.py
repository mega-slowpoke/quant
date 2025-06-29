# okx_quant_strategy/okx_api.py
# ──────────────────────────────────────────
"""
统一行情 / 下单接口（只保留一次定义）
· 支持 PROXIES 可选 SOCKS5
· _safe_get() 带指数退避 + 动态减包
· 提供：
    fetch_usdt_contracts()   # 合约列表
    fetch_4h_with_ts()       # 4H → (klines, ts_list)
    fetch_15m()              # 任意窗口 15m
    fetch_kline()            # 通用单次拉 n 根 K 线（用于实盘轮询）
    round_price()            # 对齐价格精度
"""
# ──────────────────────────────────────────
import time, json, hmac, hashlib, base64, requests
from datetime import datetime
from requests.exceptions import (
    ProxyError, SSLError, ConnectionError, ReadTimeout, RequestException
)
from config import API_KEY, SECRET_KEY, PASSPHRASE, BASE_URL

# ========== 网络全局设置 ==========
HEADERS = {"User-Agent": "Mozilla/5.0"}
PROXIES = {
    # 如需代理请填入；没有则保持 None
    # "http":  "socks5h://127.0.0.1:7890",
    # "https": "socks5h://127.0.0.1:7890",
} or None
TIMEOUT = (10, 60)               # connect, read

# ========== 统一安全 GET ==========
def _safe_get(url:str, params:dict, tag:str,
              limit_key:str="limit", max_retry:int=5, min_limit:int=25):
    wait   = 5
    limit  = params.get(limit_key, 300)
    for n in range(max_retry):
        try:
            params[limit_key] = limit
            r = requests.get(url, headers=HEADERS, proxies=PROXIES,
                             timeout=TIMEOUT, params=params)
            r.raise_for_status()
            return r.json()
        except (ProxyError, SSLError, ConnectionError,
                ReadTimeout, RequestException) as e:
            print(f"[{tag}] 第{n+1}次失败(limit={limit}): {e}")
            time.sleep(wait); wait *= 2
            limit = max(min_limit, limit//2)
    return {}

# ═══════════════════════════════════════
# 1) 合约列表
# ═══════════════════════════════════════
def fetch_usdt_contracts():
    url = f"{BASE_URL}/api/v5/public/instruments"
    js  = _safe_get(url, {"instType":"SWAP"}, tag="symbols")
    return [d["instId"] for d in js.get("data", [])
            if d["instId"].endswith("-USDT-SWAP")]

# ═══════════════════════════════════════
# 2) 4H K 线 + 时间戳
# ═══════════════════════════════════════
def fetch_4h_with_ts(symbol:str, bars:int=300):
    url = f"{BASE_URL}/api/v5/market/candles"
    js  = _safe_get(url, {"instId":symbol,"bar":"4H","limit":bars},
                    tag=f"{symbol}-4H")
    rows = js.get("data", [])[::-1]         # 升序
    kls, ts = [], []
    for r in rows:
        ts.append(int(r[0]))
        kls.append([float(x) for x in r[1:5]])  # O,H,L,C
        #print("kls.length",len(kls))
    return kls, ts

# ═══════════════════════════════════════
# 3) 任意窗口 15m
# ═══════════════════════════════════════
def fetch_15m(symbol:str, start_ts:int, end_ts:int, limit:int=300):
    url  = f"{BASE_URL}/api/v5/market/history-candles"
    out, after = [], start_ts
    while after <= end_ts:
        js = _safe_get(url, {"instId":symbol,"bar":"15m",
                             "after":after,"limit":limit},
                       tag=f"{symbol}-15m")
        rows = js.get("data", [])
        if not rows: break
        for r in rows[::-1]:                # 保证升序追加
            ts = int(r[0])
            if ts > end_ts: return out
            o,h,l,c = map(float, r[1:5])
            out.append([ts,o,h,l,c])
        after = int(rows[-1][0]) + 1
        if len(rows) < limit: break
        time.sleep(0.05)
    return sorted(out, key=lambda x: x[0])

# ═══════════════════════════════════════
# 4) 通用 fetch_kline（实盘轮询等用）
# ═══════════════════════════════════════
def fetch_kline(symbol:str, bar:str='15m', limit:int=100):
    """
    返回最近 `limit` 根（升序）  [o,h,l,c]
    """
    url = f"{BASE_URL}/api/v5/market/candles"
    js  = _safe_get(url, {"instId":symbol,"bar":bar,"limit":limit},
                    tag=f"{symbol}-{bar}")
    rows = js.get("data", [])[::-1]
    return [[float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in rows]

# ═══════════════════════════════════════
# 5) 精度工具
# ═══════════════════════════════════════
_tick_cache={}
def _fetch_tick(symbol:str):
    if symbol in _tick_cache: return _tick_cache[symbol]
    url = f"{BASE_URL}/api/v5/public/instruments"
    js  = _safe_get(url, {"instType":"SWAP","instId":symbol},
                    tag=f"{symbol}-tick")
    tick = float(js["data"][0]["tickSz"])
    _tick_cache[symbol]=tick; return tick

def round_price(symbol:str, price:float):
    tick=_fetch_tick(symbol); return round(price/tick)*tick

# 其余（签名下单等）若后续实盘需要再补，这里保持简单行情模块



