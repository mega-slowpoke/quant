# okx_quant_strategy/risk_control.py
# ─────────────────────────────────
import time
from collections import defaultdict

active_positions   = {}                # symbol -> position dict
cooldown_until_ms  = defaultdict(int)  # symbol -> ts_ms
MAX_OPEN_POSITIONS = 5                 # 同时挂单上限

def register_position(symbol, entry, sl, tp, trend, size=0):
    active_positions[symbol] = {
        "entry": entry, "sl": sl, "tp": tp,
        "trend": trend, "size": size,
        "ts": int(time.time()*1000)
    }

def cancel_position(symbol):
    """
    删除并返回持仓；回测 / 实盘共用
    """
    return active_positions.pop(symbol, None)

def set_cooldown(symbol, hours=24):
    cooldown_until_ms[symbol] = int(time.time()*1000) + hours*3600*1000

def is_in_cooldown(symbol):
    return time.time()*1000 < cooldown_until_ms[symbol]

def can_open_new_position(symbol):
    """
    是否允许新挂单：① 全局未超上限；② 符合冷却
    """
    return (len(active_positions) < MAX_OPEN_POSITIONS) and (not is_in_cooldown(symbol))


