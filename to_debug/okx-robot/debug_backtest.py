import time, pandas as pd
from datetime import datetime, timezone, timedelta
from config import MAX_OPEN_POSITIONS
from okx_api import fetch_usdt_contracts, fetch_4h_with_ts, fetch_15m
from strategy_4h import analyze_4h
from strategy_15m import Trend15State
from risk_control import active_positions, cancel_position
from logger import log_trade, log_message

CN_TZ = timezone(timedelta(hours=8))  # 北京时区

kl15 = fetch_15m('BTC-USDT-SWAP', 1745697600000, 1748937600000)
print("kl15",kl15)