# okx_quant_strategy/strategy_15m.py
# ──────────────────────────────────────────
"""
15 m 状态机（维持原有高低点 / 趋势过滤等全部规则）
  · 仅在 update() 开头增加止盈 / 止损检测
"""
# ──────────────────────────────────────────
import time
from utils   import build_trend, find_highs_lows_15m
from logger  import log_message, log_trade
from okx_api import round_price
from risk_control import (
    active_positions, can_open_new_position,
    register_position, cancel_position, set_cooldown
)

trend15_states = {}          # 外部可直接访问全部状态

# ═══════════════════════════════════════
class Trend15State:
    def __init__(self, symbol, ob, main_trend,
                 ref_ts, kline_history):
        self.symbol      = symbol
        self.ob          = ob
        self.main_trend  = main_trend          # 上级 4 h 趋势
        self.ref_ts      = ref_ts
        self.trend       = 'downtrend' if main_trend=='uptrend' else 'uptrend'

        self.kline_buffer = kline_history[:]   # 升序
        self.ll=self.lh=self.hl=self.hh=None
        self.ob_touched   = False
        self.exchange_trend=False
        self.order_sent   = False
        self.hl_candidates=[]; self.lh_candidates=[]

        self._init_structure()

    # ---------- 找触碰点并初始化高低点 ----------
    def _init_structure(self):
        for i,k in enumerate(self.kline_buffer):
            _,_,h,l,_ = k
            if self.main_trend=='uptrend' and self.ob['bottom']<=l<=self.ob['top']:
                self.ob_touched=True; start=i; break
            if self.main_trend=='downtrend' and self.ob['bottom']<=h<=self.ob['top']:
                self.ob_touched=True; start=i; break
        else:
            return
        pts = find_highs_lows_15m(self.kline_buffer[start:], self.main_trend, start)
        tr, info = build_trend(pts)
        if self.main_trend=='uptrend':
            self.lh, self.ll = info.get('lh'), info.get('ll')
            self.trend='downtrend'
        else:
            self.hl, self.hh = info.get('hl'), info.get('hh')
            self.trend='uptrend'

    # ---------- 每根 15 m 推进 ----------
    def update(self, k):
        # ★★★★★★★★★★★★★★★★★★★★★★
        # ★  1) 止盈 / 止损检测  (新增)  ★
        # ★★★★★★★★★★★★★★★★★★★★★★
        pos = active_positions.get(self.symbol)                        # ★新增
        if pos:                                                        # ★新增
            hit, prof = self._check_exit(k[4], pos)                    # ★新增
            if hit:                                                    # ★新增
                cancel_position(self.symbol)                           # ★新增
                log_trade(self.symbol, pos['trend'],                   # ★新增
                          pos['entry'], pos['sl'], pos['tp'], prof)    # ★新增
                self.order_sent = False                                # ★新增
        # ---------- 原逻辑开始 ----------
        ts,o,h,l,c = k
        self.kline_buffer.append(k)

        # 若尚未触碰 OB，再检查一次
        if not self.ob_touched:
            self._init_structure()
            return

        # ① 实体穿透 OB → 冷却
        if self.main_trend=='uptrend' and l < self.ob['bottom']:
            cancel_position(self.symbol); set_cooldown(self.symbol,24)
            self.ob_touched=False; return
        if self.main_trend=='downtrend' and h > self.ob['top']:
            cancel_position(self.symbol); set_cooldown(self.symbol,24)
            self.ob_touched=False; return

        # ② 结构破坏 → 趋势翻转 + 挂单
        if self.trend=='downtrend' and self.lh and c > self.lh[2]:
            if self.exchange_trend:
                cancel_position(self.symbol); self.ob_touched=False; return
            self.trend='uptrend'; self.exchange_trend=True
            self.hl=self.ll; self.hh=(len(self.kline_buffer)-1,'high',h)
            self._try_order('buy')
        elif self.trend=='uptrend' and self.hl and c < self.hl[2]:
            if self.exchange_trend:
                cancel_position(self.symbol); self.ob_touched=False; return
            self.trend='downtrend'; self.exchange_trend=True
            self.lh=self.hh; self.ll=(len(self.kline_buffer)-1,'low',l)
            self._try_order('sell')

        # ③ 无破坏 → 推进高低点
        elif len(self.kline_buffer) >= 3:
            self._advance_high_low()

    # ---------- 推进高低点（原版方法） ----------
    def _advance_high_low(self):
        prev = self.kline_buffer[-2]
        idx  = len(self.kline_buffer)-2
        p3,p1 = self.kline_buffer[-3], self.kline_buffer[-1]
        is_high = prev[2] > p3[2] and prev[2] > p1[2]
        is_low  = prev[3] < p3[3] and prev[3] < p1[3]

        if self.trend=='uptrend':
            if is_low:
                self.hl_candidates.append((idx,'low',prev[3]))
            elif is_high:
                if self.hl_candidates:
                    cand=min(self.hl_candidates,key=lambda x:x[2])
                    if prev[2] > (self.hh[2] if self.hh else -1e18):
                        self.hl,self.hh = cand,(idx,'high',prev[2])
                    self.hl_candidates.clear()
                elif self.hh is None or prev[2] > self.hh[2]:
                    self.hh = (idx,'high',prev[2])
        else:
            if is_high:
                self.lh_candidates.append((idx,'high',prev[2]))
            elif is_low:
                if self.lh_candidates:
                    cand=max(self.lh_candidates,key=lambda x:x[2])
                    if prev[3] < (self.ll[2] if self.ll else 1e18):
                        self.lh,self.ll = cand,(idx,'low',prev[3])
                    self.lh_candidates.clear()
                elif self.ll is None or prev[3] < self.ll[2]:
                    self.ll = (idx,'low',prev[3])

    # ---------- 下单（与原版一致） ----------
    def _try_order(self, side):
        if self.order_sent or not can_open_new_position(self.symbol):
            return
        if side=='buy' and self.hl:
            hl_idx = self.hl[0]
            for i in range(hl_idx, -1, -1):
                o,_,_,_,c = self.kline_buffer[i][1:6]
                if c < o:            # 找到下跌实体
                    entry = round_price(self.symbol, max(o,c))
                    sl    = round_price(self.symbol, self.hl[2])
                    tp    = round_price(self.symbol, entry + 2.5*(entry-sl))
                    sz    = round(100/abs(entry-sl),4)
                    register_position(self.symbol, entry, sl, tp, 'buy', sz)
                    log_trade(self.symbol,'buy',entry)
                    self.order_sent=True; break
        elif side=='sell' and self.hh:
            hh_idx = self.hh[0]
            for i in range(hh_idx, -1, -1):
                o,_,_,_,c = self.kline_buffer[i][1:6]
                if c > o:            # 上涨实体
                    entry = round_price(self.symbol, min(o,c))
                    sl    = round_price(self.symbol, self.hh[2])
                    tp    = round_price(self.symbol, entry - 2.5*(sl-entry))
                    sz    = round(100/abs(sl-entry),4)
                    register_position(self.symbol, entry, sl, tp, 'sell', sz)
                    log_trade(self.symbol,'sell',entry)
                    self.order_sent=True; break

    # ---------- 止盈 / 止损判定 ----------
    def _check_exit(self, price, pos):
        if pos['trend']=='buy':
            if price<=pos['sl']: return True,-100
            if price>=pos['tp']: return True,+250
        else:
            if price>=pos['sl']: return True,-100
            if price<=pos['tp']: return True,+250
        return False,0



'''# 全文件：15m 状态机（支持批量 + 空值守护）
import time
from logger import log_message
from risk_control import active_positions, register_position, cancel_position
from okx_api import round_price, place_limit_order

# 在文件顶部新增
from logger import log_message

def mock_order(action, symbol, entry, sl, tp, size):
    log_message(f"[MOCK-ORDER] {action.upper()} {symbol} "
                f"entry={entry} sl={sl} tp={tp} size={size}")

from order_exec import send_order


class Trend15State:
    def __init__(self, symbol, ob, main_trend, touch_ts, history_kl):
        self.symbol     = symbol
        self.ob         = ob
        self.main_trend = main_trend
        self.kline      = history_kl[:]          # [[ts,o,h,l,c]...]
        self.trend      = 'downtrend' if main_trend=='uptrend' else 'uptrend'

        self.hl=self.hh=self.ll=self.lh=None
        self.ob_touched = True
        self.order_sent = False

        # 先把历史 K 推进去，让结构点就绪
        for k in self.kline[:-1]:
            self._update_structure_point(k, is_history=True)

    # —— 内部：单根结构推进 ——
    def _update_structure_point(self, k, is_history=False):
        ts,o,h,l,c = k
        idx = len(self.kline) - 1 if not is_history else 0

        # 简化：只用高 / 低点更新结构，空值时初始化
        if self.trend=='uptrend':
            if self.hl is None: self.hl=(idx,'low',l)
            if self.hh is None: self.hh=(idx,'high',h)
            if l < self.hl[2]:
                self.trend='downtrend'; self.ll=(idx,'low',l); self.lh=self.hh
        else:
            if self.ll is None: self.ll=(idx,'low',l)
            if self.lh is None: self.lh=(idx,'high',h)
            if h > self.lh[2]:
                self.trend='uptrend'; self.hh=(idx,'high',h); self.hl=self.ll

    # —— 内部：批量 / 单根统一更新 ——
    def _update_structure(self):
        if len(self.kline) < 3:
            return
        self._update_structure_point(self.kline[-2])   # 核心判断

    # —— 内部：尝试挂单 ——
    # —— 内部：尝试挂单 ——
    def _try_order(self, k):
        if self.order_sent:
            return
        ts, o, h, l, c = k

        if self.trend == 'uptrend' and self.hl:
            entry = max(o, c)
            sl = self.hl[2]
            tp = entry + 2.5 * (entry - sl)
            size = round(100 / abs(entry - sl), 4)
            register_position(self.symbol, entry, sl, tp, 'buy', size)  # ★ 修
            #place_limit_order(self.symbol, round_price(self.symbol, entry),
                              'buy', sl, tp, size)
            # ... 在 _try_order 中把 place_limit_order(..) 改为 mock_order(..)
            #mock_order('buy', self.symbol, entry, sl, tp, size)
            send_order('buy', self.symbol, entry, sl, tp, size)
            self.order_sent = True

        elif self.trend == 'downtrend' and self.lh:
            entry = min(o, c)
            sl = self.lh[2]
            tp = entry - 2.5 * (sl - entry)
            size = round(100 / abs(sl - entry), 4)
            register_position(self.symbol, entry, sl, tp, 'sell', size)  # ★ 修
            #place_limit_order(self.symbol, round_price(self.symbol, entry),
                              'sell', sl, tp, size)
            send_order('sell', self.symbol, entry, sl, tp, size)
            #mock_order('sell', self.symbol, entry, sl, tp, size)
            self.order_sent = True

    # ———— 对外：单根 ————
    def update(self, k):
        self.kline.append(k)
        self._update_structure()
        self._try_order(k)

    # ———— 对外：批量 ————
    def update_batch(self, klines):
        for k in klines:
            self.update(k)

    # ———— 是否结束 ————
    @property
    def is_finished(self):
        return (not self.ob_touched) or \
               (self.order_sent and self.symbol not in active_positions)
'''

