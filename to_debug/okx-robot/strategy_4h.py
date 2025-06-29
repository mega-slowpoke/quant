# okx_quant_strategy/strategy_4h.py

from utils import find_highs_lows, build_trend
from okx_api import fetch_kline
from logger import logger
from config import COOLDOWN_DURATION_HOURS
#from risk_control import can_open_new_position, register_position

import time

cooldown_tracker = {}

def analyze_4h(candles,symbol):
    #candles = fetch_kline(symbol, "4H", 100)
    points = find_highs_lows(candles)
    trend, trend_info = build_trend(points)
    #print("points",points)
    #print("trend",trend)
    #print("trend_info",trend_info)
    if not trend:
        #logger.info(f"[4H] 无趋势识别: {symbol}")
        return None, None

    order_block = build_order_block(candles, trend_info, trend)

    if order_block:
        logger.info(f"[4H] 识别到趋势: {trend}, OB: {order_block}")
        return trend,trend_info, order_block
    return None, None

# utils.py  ── 覆盖原函数即可
def build_order_block(candles, trend_info, trend):
    """
    依据最新 HL / LH 所在 K 线，向前寻找“最近一根反向实体”构成 OB.
      · uptrend  : HL 所在 K 线如果本身是下跌实体(O>C)，就直接用它；
                   否则继续向前找第一根下跌实体。
      · downtrend: LH 所在 K 线如果本身是上涨实体(O<C)，就直接用它；
                   否则继续向前找第一根上涨实体。
    返回格式: {'top': price, 'bottom': price}
    """
    if trend == 'uptrend' and trend_info.get('hl'):
        start = trend_info['hl'][0]           # 最新 HL 的索引
        for i in range(start, -1, -1):        # ★ 从 HL 那根开始向前
            o, h, l, c = candles[i]
            if c < o:                         # 下跌实体
                return {'top': o, 'bottom': c}
    elif trend == 'downtrend' and trend_info.get('lh'):
        start = trend_info['lh'][0]           # 最新 LH 的索引
        for i in range(start, -1, -1):        # ★ 从 LH 那根开始向前
            o, h, l, c = candles[i]
            if c > o:                         # 上涨实体
                return {'top': c, 'bottom': o}
    return None


def is_in_cooldown(symbol):
    return cooldown_tracker.get(symbol, 0) > time.time()

def set_cooldown(symbol):
    cooldown_tracker[symbol] = time.time() + 3600 * COOLDOWN_DURATION_HOURS
