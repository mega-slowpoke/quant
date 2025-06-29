''''# okx_quant_strategy/quant_main.py

import time
from okx_api import fetch_usdt_contracts, fetch_kline
from strategy_4h import analyze_4h, is_in_cooldown
from strategy_15m import run_15m_strategy
from logger import logger

def main():
    symbols = fetch_usdt_contracts()
    logger.info(f"[主程序] 共获取 {len(symbols)} 个币种，开始轮询")

    while True:
        for symbol in symbols:
            try:
                if is_in_cooldown(symbol):
                    continue

                trend_info, ob = analyze_4h(symbol)
                if not trend_info or not ob:
                    continue

                full_15m_klines = fetch_kline(symbol, "15m", 200)
                history_klines = full_15m_klines[:100]
                new_klines = full_15m_klines[100:]

                run_15m_strategy(symbol, ob, trend_info, new_klines, history_klines)
                time.sleep(0.5)

            except Exception as e:
                logger.exception(f"[主程序异常] {symbol}: {str(e)}")

        logger.info("[主程序] 本轮全部币种轮询结束，暂停 60 秒")
        time.sleep(60)

if __name__ == "__main__":
    main()'''
# okx_quant_strategy/quant_main.py
import time, math, threading
from datetime import datetime, timedelta

from config         import MAX_OPEN_POSITIONS
from okx_api        import fetch_usdt_contracts, fetch_kline          # 15m / 4H k线
from strategy_4h    import analyze_4h, build_order_block
from strategy_15m   import Trend15State
from risk_control   import active_positions, cancel_position, is_in_cooldown
from logger         import logger, log_message

FOUR_H_WINDOW   = 120         # 4h 近 120 根
FIFTEEN_WINDOW  = 200         # 15m 近 200 根
FOUR_H_SECONDS  = 4 * 3600
FIFTEEN_SECONDS = 15 * 60

# ——————————————————————————————————————————
class SymbolTracker:
    """
    维护单币种所有状态：
      · latest_4h_ts  记录已处理的最后一根 4H 收盘
      · four_info     最新趋势 & OB
      · t15_state     当前 15m 子状态机 (Trend15State) or None
    """
    def __init__(self, symbol):
        self.symbol = symbol
        self.latest_4h_ts = 0
        self.four_info = None        # (trend_info, ob)
        self.t15_state = None
        self.cooldown_until = 0

    # — 每 4 小时调用 ——————————————————
    def update_4h(self):
        if time.time()*1000 < self.cooldown_until:
            return

        kl4 = fetch_kline(self.symbol, "4H", FOUR_H_WINDOW)
        if len(kl4) < 120:
            log_message(f"[4H] {self.symbol} 数据不足")
            return

        trend, info = analyze_4h(kl4)
        if not trend:
            return
        ob = build_order_block(kl4, info, trend)
        if not ob:
            return

        self.latest_4h_ts = int(time.time()//FOUR_H_SECONDS)*FOUR_H_SECONDS*1000
        self.four_info = (trend, info, ob)
        logger.info(f"[4H] {self.symbol} trend={trend} OB={ob}")

        # 若 4h 趋势/OB 改变，取消旧 15m 状态 & 挂单
        if self.t15_state:
            cancel_position(self.symbol)
            self.t15_state = None

    # — 每 15 分钟调用 ——————————————————
    def update_15m(self):
        if not self.four_info:
            return
        if time.time()*1000 < self.cooldown_until:
            return

        trend, info, ob = self.four_info

        if not self.t15_state:
            # 判断是否首次触碰
            k = fetch_kline(self.symbol, "15m", 1)[0]   # 最新一根
            _, o, h, l, c = k
            if (trend=='uptrend'   and ob['bottom']<=l<=ob['top']) or \
               (trend=='downtrend' and ob['bottom']<=h<=ob['top']):
                # 补齐触碰点之前 100 根作为历史
                history = fetch_kline(self.symbol, "15m", 100)
                self.t15_state = Trend15State(
                    self.symbol, ob, trend, k[0], history)
                logger.info(f"[15m] {self.symbol} 首次触碰 OB, 启动跟踪")
            return

        # 若已有子状态机 → 喂入最新 k 线
        k = fetch_kline(self.symbol, "15m", 1)[0]
        self.t15_state.update(k)

        # 穿透 OB ⇒ 冷却
        _, o, h, l, c = k
        if (trend=='uptrend' and l < ob['bottom']) or \
           (trend=='downtrend' and h > ob['top']):
            cancel_position(self.symbol)
            self.t15_state = None
            self.cooldown_until = k[0] + 24*3600*1000
            logger.info(f"[冷却] {self.symbol} 穿透 OB，休眠 24h")

# ——————————————————————————————————————————
def align_sleep(seconds):
    """
    让线程睡到下一个整分钟 / 整 4h
    """
    now = datetime.utcnow()
    delta = seconds - (now.timestamp() % seconds)
    time.sleep(delta)

def main():
    symbols = fetch_usdt_contracts()[:200]
    logger.info(f"[主程序] 载入 {len(symbols)} 个 USDT-SWAP")

    trackers = {s: SymbolTracker(s) for s in symbols}

    # ① 先对齐到最近的 15m 边界
    align_sleep(FIFTEEN_SECONDS)

    while True:
        utc_now  = datetime.utcnow()
        sec_now  = utc_now.timestamp()

        fourh_boundary   = (sec_now // FOUR_H_SECONDS) * FOUR_H_SECONDS
        fifteen_boundary = (sec_now // FIFTEEN_SECONDS) * FIFTEEN_SECONDS

        # — A. 4H 轮询（整 4h 边界触发）
        if sec_now - fourh_boundary < 5:
            logger.info("[4H轮询] 开始")
            for tr in trackers.values():
                tr.update_4h()

        # — B. 15m 轮询（整 15m 边界触发）
        if sec_now - fifteen_boundary < 5:
            logger.info("[15m轮询] 开始")
            for tr in trackers.values():
                tr.update_15m()

        # — C. 风控：同时持仓不得超过 5
        if len(active_positions) > MAX_OPEN_POSITIONS:
            # 平掉最早的多余持仓
            excess = len(active_positions) - MAX_OPEN_POSITIONS
            for sym in list(active_positions.keys())[:excess]:
                cancel_position(sym)
                logger.info(f"[风控] 平掉 {sym} 多余持仓")

        # 睡到下一分钟
        time.sleep(10)

if __name__ == "__main__":
    main()

