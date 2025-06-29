# okx_quant_strategy/config.py
API_KEY = "your_api_key"
SECRET_KEY = "your_secret_key"
PASSPHRASE = "your_passphrase"

MAX_OPEN_POSITIONS = 5
COOLDOWN_DURATION_HOURS = 24
MIN_VOLUME_THRESHOLD = 1_000_000  # 最低交易量过滤
BASE_URL = "https://www.okx.com"


# okx_quant_strategy/okx_api.py
import requests
import time
from config import API_KEY, SECRET_KEY, PASSPHRASE, BASE_URL

headers = {
    'Content-Type': 'application/json',
    'OK-ACCESS-KEY': API_KEY,
    'OK-ACCESS-SIGN': '',
    'OK-ACCESS-TIMESTAMP': '',
    'OK-ACCESS-PASSPHRASE': PASSPHRASE,
}

def fetch_usdt_contracts():
    url = f"{BASE_URL}/api/v5/public/instruments?instType=SWAP"
    r = requests.get(url)
    contracts = r.json()['data']
    return [c['instId'] for c in contracts if c['ctValCcy'] == 'USDT']

def fetch_kline(symbol, bar, limit=100):
    url = f"{BASE_URL}/api/v5/market/candles?instId={symbol}&bar={bar}&limit={limit}"
    r = requests.get(url)
    data = r.json()['data']
    return list(reversed([[float(x[1]), float(x[2]), float(x[3]), float(x[4])] for x in data]))  # O,H,L,C


# okx_quant_strategy/utils.py

def find_highs_lows(candles):
    temp = []
    for i in range(1, len(candles) - 1):
        o, h, l, c = candles[i]
        prev_h, next_h = candles[i - 1][1], candles[i + 1][1]
        prev_l, next_l = candles[i - 1][2], candles[i + 1][2]

        is_high = h > prev_h and h > next_h
        is_low = l < prev_l and l < next_l

        if is_high and is_low:
            temp.append((i, 'both', h, l))
        elif is_high:
            temp.append((i, 'high', h))
        elif is_low:
            temp.append((i, 'low', l))

    filtered = []
    for p in temp:
        if not filtered:
            if p[1] == 'both':
                filtered.append((p[0], 'high', p[2]))
            else:
                filtered.append(p)
        else:
            last_type = filtered[-1][1]
            if p[1] == 'both':
                chosen = 'low' if last_type == 'high' else 'high'
                value = p[3] if chosen == 'low' else p[2]
                filtered.append((p[0], chosen, value))
            elif p[1] != last_type:
                filtered.append(p)
            else:
                if p[1] == 'high' and p[2] > filtered[-1][2]:
                    filtered[-1] = p
                elif p[1] == 'low' and p[2] < filtered[-1][2]:
                    filtered[-1] = p
    return filtered


def build_trend(points):
    trend = None
    trend_info = {
        'highs': [],
        'lows': [],
        'status': None,
        'hl': None,
        'hh': None,
        'll': None,
        'lh': None
    }

    i = 0
    while i <= len(points) - 4:
        p1, p2, p3, p4 = points[i:i+4]
        if p1[1] == 'high' and p2[1] == 'low' and p3[1] == 'high' and p4[1] == 'low':
            if p3[2] > p1[2] and p4[2] > p2[2]:
                trend = 'uptrend'
                trend_info['hh'] = p3
                trend_info['hl'] = p4
                trend_info['status'] = trend
                i += 4
                break
        elif p1[1] == 'low' and p2[1] == 'high' and p3[1] == 'low' and p4[1] == 'high':
            if p3[2] < p1[2] and p4[2] < p2[2]:
                trend = 'downtrend'
                trend_info['ll'] = p3
                trend_info['lh'] = p4
                trend_info['status'] = trend
                i += 4
                break
        i += 1

    if trend is None:
        return None, trend_info

    pending_low = None
    pending_high = None

    for j in range(i, len(points)):
        p = points[j]

        if trend == 'uptrend':
            if p[1] == 'low':
                if p[2] < trend_info['hl'][2]:
                    trend = 'downtrend'
                    trend_info['ll'] = p
                    prev_highs = [x for x in points[:j] if x[1] == 'high']
                    trend_info['lh'] = prev_highs[-1] if prev_highs else trend_info['hh']
                    pending_low = None
                    pending_high = None
                else:
                    if pending_low is None or p[2] < pending_low[2]:
                        pending_low = p
            elif p[1] == 'high' and pending_low:
                if p[2] > trend_info['hh'][2] and pending_low[2] > trend_info['hl'][2]:
                    trend_info['hh'] = p
                    trend_info['hl'] = pending_low
                    pending_low = None

        elif trend == 'downtrend':
            if p[1] == 'high':
                if p[2] > trend_info['lh'][2]:
                    trend = 'uptrend'
                    trend_info['hh'] = p
                    prev_lows = [x for x in points[:j] if x[1] == 'low']
                    trend_info['hl'] = prev_lows[-1] if prev_lows else trend_info['ll']
                    pending_low = None
                    pending_high = None
                else:
                    if pending_high is None or p[2] > pending_high[2]:
                        pending_high = p
            elif p[1] == 'low' and pending_high:
                if p[2] < trend_info['ll'][2] and pending_high[2] < trend_info['lh'][2]:
                    trend_info['ll'] = p
                    trend_info['lh'] = pending_high
                    pending_high = None

    trend_info['status'] = trend
    trend_info['highs'] = [p for p in points if p[1] == 'high']
    trend_info['lows'] = [p for p in points if p[1] == 'low']
    return trend, trend_info


def build_order_block(candles, trend_info, trend):
    if trend == 'uptrend':
        last_hl_idx = trend_info['hl'][0]
        for i in range(last_hl_idx-1, -1, -1):
            if candles[i][3] < candles[i][0]:
                return {'top': candles[i][0], 'bottom': candles[i][3]}
    elif trend == 'downtrend':
        last_lh_idx = trend_info['lh'][0]
        for i in range(last_lh_idx-1, -1, -1):
            if candles[i][3] > candles[i][0]:
                return {'top': candles[i][3], 'bottom': candles[i][0]}
    return None

# === 工具函数 ===
def find_highs_lows_15m(retros, trend, ob_touch_index):
    points = []
    for i in range(1, len(retros) - 1):
        prev, curr, next_ = retros[i - 1], retros[i], retros[i + 1]
        is_high = curr[2] > prev[2] and curr[2] > next_[2]:
        #points.append((i, 'high', curr[2]))
        is_low = curr[3] < prev[3] and curr[3] < next_[3]:
        #points.append((i, 'low', curr[3]))
        if is_high and is_low:
            points.append((i, 'both', h, l))
        elif is_high:
            points.append((i, 'high', h))
        elif is_low:
            points.append((i, 'low', l))
    ob_k = retros[0]
    if trend == 'uptrend':
        points = [(0, 'low', ob_k[3])] + points
    elif trend == 'downtrend':
        points = [(0, 'high', ob_k[2])] + points
    filtered = []
    for p in points:
        if not filtered:
            if p[1] == 'both':
                filtered.append((p[0], 'high', p[2]))
            else:
                filtered.append(p)
        else:
            last_type = filtered[-1][1]
            if p[1] == 'both':
                chosen = 'low' if last_type == 'high' else 'high'
                value = p[3] if chosen == 'low' else p[2]
                filtered.append((p[0], chosen, value))
            elif p[1] != last_type:
                filtered.append(p)
            else:
                if p[1] == 'high' and p[2] > filtered[-1][2]:
                    filtered[-1] = p
                elif p[1] == 'low' and p[2] < filtered[-1][2]:
                    filtered[-1] = p
    return filtered
# === 整理后的高低点结构推进逻辑 ===
if len(self.kline_buffer) >= 3:
    prev = self.kline_buffer[-2]
    prev_idx = len(self.kline_buffer) - 2
    is_high = prev[2] > self.kline_buffer[-3][2] and prev[2] > self.kline_buffer[-1][2]
    is_low = prev[3] < self.kline_buffer[-3][3] and prev[3] < self.kline_buffer[-1][3]

    if self.trend == 'uptrend':
        if is_low:
            if not hasattr(self, 'hl_candidates'):
                self.hl_candidates = []
            self.hl_candidates.append((prev_idx, 'low', prev[3]))

        elif is_high:
            if self.hl_candidates:
                candidate_hl = min(self.hl_candidates, key=lambda x: x[2])
                if prev[2] > self.hh[2]:
                    self.hl = candidate_hl
                    self.hh = (prev_idx, 'high', prev[2])
                self.hl_candidates = []
            elif prev[2] > self.hh[2]:
                self.hh = (prev_idx, 'high', prev[2])

    elif self.trend == 'downtrend':
        if is_high:
            if not hasattr(self, 'lh_candidates'):
                self.lh_candidates = []
            self.lh_candidates.append((prev_idx, 'high', prev[2]))

        elif is_low:
            if self.lh_candidates:
                candidate_lh = max(self.lh_candidates, key=lambda x: x[2])
                if prev[3] < self.ll[2]:
                    self.lh = candidate_lh
                    self.ll = (prev_idx, 'low', prev[3])
                self.lh_candidates = []
            elif prev[3] < self.ll[2]:
                self.ll = (prev_idx, 'low', prev[3])


# === 工具函数 ===
def find_highs_lows_15m(retros, trend, ob_touch_index):
    points = []
    for i in range(1, len(retros) - 1):
        prev, curr, next_ = retros[i - 1], retros[i], retros[i + 1]
        h, l = curr[2], curr[3]
        is_high = h > prev[2] and h > next_[2]
        is_low = l < prev[3] and l < next_[3]
        if is_high and is_low:
            points.append((i, 'both', h, l))
        elif is_high:
            points.append((i, 'high', h))
        elif is_low:
            points.append((i, 'low', l))
    ob_k = retros[0]
    if trend == 'uptrend':
        points = [(0, 'low', ob_k[3])] + points
    elif trend == 'downtrend':
        points = [(0, 'high', ob_k[2])] + points
    filtered = []
    for p in points:
        if not filtered:
            if p[1] == 'both':
                filtered.append((p[0], 'high', p[2]))
            else:
                filtered.append(p)
        else:
            last_type = filtered[-1][1]
            if p[1] == 'both':
                chosen = 'low' if last_type == 'high' else 'high'
                value = p[3] if chosen == 'low' else p[2]
                filtered.append((p[0], chosen, value))
            elif p[1] != last_type:
                filtered.append(p)
            else:
                if p[1] == 'high' and p[2] > filtered[-1][2]:
                    filtered[-1] = p
                elif p[1] == 'low' and p[2] < filtered[-1][2]:
                    filtered[-1] = p
    return filtered

# === 主结构类 ===
from strategy import active_positions, cancel_position
from utils import build_trend
import time

class Trend15State:
    def __init__(self, symbol, ob, main_trend, hh_timestamp, kline_history):
        self.symbol = symbol
        self.ob = ob
        self.main_trend = main_trend
        self.hh_timestamp = hh_timestamp

        self.trend = 'downtrend' if main_trend == 'uptrend' else 'uptrend'
        self.kline_buffer = kline_history.copy()

        self.ll = None
        self.lh = None
        self.hl = None
        self.hh = None
        self.exchange_trend = False
        self.ob_touch_index = None
        self.ob_touched = False
        self.cooldown = False
        self.order_placed = False

        self.init_structure_if_ready()

    def init_structure_if_ready(self):
        for i, k in enumerate(self.kline_buffer):
            _, o, h, l, _ = k
            if self.main_trend == 'uptrend' and self.ob['bottom'] <= l <= self.ob['top']:
                self.ob_touched = True
                self.ob_touch_index = i
                break
            elif self.main_trend == 'downtrend' and self.ob['bottom'] <= h <= self.ob['top']:
                self.ob_touched = True
                self.ob_touch_index = i
                break

        if self.ob_touched and self.ob_touch_index is not None:
            retros = self.kline_buffer[self.ob_touch_index:]
            points = find_highs_lows_15m(retros, self.main_trend, self.ob_touch_index)
            trend, info = build_trend(points)
            if self.main_trend == 'uptrend':
                self.lh = info.get('lh', None)
                self.ll = info.get('ll', None)
            elif self.main_trend == 'downtrend':
                self.hl = info.get('hl', None)
                self.hh = info.get('hh', None)

    def update(self, new_kline):
        if self.cooldown and time.time() < self.cooldown:
            return

        ts, o, h, l, c = new_kline
        self.kline_buffer.append(new_kline)

        if not self.ob_touched:
            self.init_structure_if_ready()
            return

        if self.ob_touched:
            if self.main_trend == 'uptrend' and l < self.ob['bottom']:
                cancel_position(self.symbol)
                self.cooldown = time.time() + 3600 * 24
                self.ob_touched = False
                return
            elif self.main_trend == 'downtrend' and h > self.ob['top']:
                cancel_position(self.symbol)
                self.cooldown = time.time() + 3600 * 24
                self.ob_touched = False
                return

        if self.trend == 'downtrend' and self.lh and c > self.lh[2]:
            if self.exchange_trend:
                cancel_position(self.symbol)
                self.ob_touched = False
                return
            self.trend = 'uptrend'
            self.exchange_trend = True
            self.hl = self.ll
            self.hh = (len(self.kline_buffer) - 1, 'high', h)
            self.order_placed = True
            self.place_order('buy')

        elif self.trend == 'uptrend' and self.hl and c < self.hl[2]:
            if self.exchange_trend:
                cancel_position(self.symbol)
                self.ob_touched = False
                return
            self.trend = 'downtrend'
            self.exchange_trend = True
            self.lh = self.hh
            self.ll = (len(self.kline_buffer) - 1, 'low', l)
            self.order_placed = True
            self.place_order('sell')

        else:
            if len(self.kline_buffer) >= 3:
                prev = self.kline_buffer[-2]
                prev_idx = len(self.kline_buffer) - 2
                is_high = prev[2] > self.kline_buffer[-3][2] and prev[2] > self.kline_buffer[-1][2]
                is_low = prev[3] < self.kline_buffer[-3][3] and prev[3] < self.kline_buffer[-1][3]

                if self.trend == 'uptrend':
                    if is_low:
                        if not hasattr(self, 'hl_candidates'):
                            self.hl_candidates = []
                        self.hl_candidates.append((prev_idx, 'low', prev[3]))
                    elif is_high:
                        if self.hl_candidates:
                            candidate_hl = min(self.hl_candidates, key=lambda x: x[2])
                            if prev[2] > self.hh[2]:
                                self.hl = candidate_hl
                                self.hh = (prev_idx, 'high', prev[2])
                            self.hl_candidates = []
                        elif prev[2] > self.hh[2]:
                            self.hh = (prev_idx, 'high', prev[2])

                elif self.trend == 'downtrend':
                    if is_high:
                        if not hasattr(self, 'lh_candidates'):
                            self.lh_candidates = []
                        self.lh_candidates.append((prev_idx, 'high', prev[2]))
                    elif is_low:
                        if self.lh_candidates:
                            candidate_lh = max(self.lh_candidates, key=lambda x: x[2])
                            if prev[3] < self.ll[2]:
                                self.lh = candidate_lh
                                self.ll = (prev_idx, 'low', prev[3])
                            self.lh_candidates = []
                        elif prev[3] < self.ll[2]:
                            self.ll = (prev_idx, 'low', prev[3])
    def place_order(self, direction):
        from okx_api import place_limit_order

        if direction == 'buy':
            hl_index = self.hl[0] if self.hl else None
            if hl_index is not None:
                for i in range(hl_index, -1, -1):
                    o, _, _, _, c = self.kline_buffer[i][1:6]
                    if c < o:
                        ob_top = max(o, c)
                        sl = self.hl[2]
                        tp = ob_top + 2.5 * (ob_top - sl)
                        size = round(100 / abs(ob_top - sl), 4)
                        active_positions[self.symbol] = {
                            'entry': ob_top,
                            'sl': sl,
                            'tp': tp,
                            'trend': direction
                        }
                        place_limit_order(
                            symbol=self.symbol,
                            price=ob_top,
                            side='buy',
                            sl=sl,
                            tp=tp,
                            size=size
                        )
                        print(f"[15M ENTRY] BUY {self.symbol} @ {ob_top}, SL={sl}, TP={tp}, SIZE={size}")
                        break

        elif direction == 'sell':
            hh_index = self.hh[0] if self.hh else None
            if hh_index is not None:
                for i in range(hh_index, -1, -1):
                    o, _, _, _, c = self.kline_buffer[i][1:6]
                    if c > o:
                        ob_low = min(o, c)
                        sl = self.hh[2]
                        tp = ob_low - 2.5 * (sl - ob_low)
                        size = round(100 / abs(sl - ob_low), 4)
                        active_positions[self.symbol] = {
                            'entry': ob_low,
                            'sl': sl,
                            'tp': tp,
                            'trend': direction
                        }
                        place_limit_order(
                            symbol=self.symbol,
                            price=ob_low,
                            side='sell',
                            sl=sl,
                            tp=tp,
                            size=size
                        )
                        print(f"[15M ENTRY] SELL {self.symbol} @ {ob_low}, SL={sl}, TP={tp}, SIZE={size}")
                        break
def run_15m_strategy(symbol, ob, trend_info, new_klines, history_klines):
    hh_index = trend_info['hh'][0]
    hh_timestamp = hh_index * 4 * 3600

    if symbol not in trend15_states:
        trend15_states[symbol] = Trend15State(symbol, ob, trend_info['status'], hh_timestamp, history_klines)

    state = trend15_states[symbol]
    for k in new_klines:
        state.update(k)
    return state
