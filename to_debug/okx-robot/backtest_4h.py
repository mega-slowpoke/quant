# okx_quant_strategy/backtest_slice.py
# ──────────────────────────────────────────
import pandas as pd
from datetime    import datetime, timezone, timedelta
from config      import MAX_OPEN_POSITIONS
from okx_api     import (
    fetch_usdt_contracts, fetch_4h_with_ts, fetch_15m
)
from strategy_4h import analyze_4h
from strategy_15m import Trend15State, trend15_states
from risk_control import active_positions, cancel_position, set_cooldown
from logger       import log_trade, log_message

CN_TZ = timezone(timedelta(hours=8))
def fmt(ms): return datetime.fromtimestamp(ms/1000, CN_TZ)\
                             .strftime('%Y-%m-%d %H:%M 整')

def exit_check(price,pos):
    if pos['trend']=='buy':
        if price<=pos['sl']: return True,-100
        if price>=pos['tp']: return True,+250
    else:
        if price>=pos['sl']: return True,-100
        if price<=pos['tp']: return True,+250
    return False,0

def first_touch_idx(kl15, tr, ob):
    for j,(_,o,h,l,c) in enumerate(kl15):
        if tr=='uptrend'   and ob['bottom']<=l<=ob['top']:
            return j
        if tr=='downtrend' and ob['bottom']<=h<=ob['top']:
            return j
    return None
# ──────────────────────────────────────────
def backtest_symbol(sym:str):

    kl4, ts4 = fetch_4h_with_ts(sym, 300)      # OHLC + 每根 4h 的时间戳
    if len(kl4) < 120:
        log_message(f'{sym} 4H 数据不足'); return None

    wins=losses=pnl=0
    cur_tr=cur_ob=None
    state_open=False
    state=None

    i=100                                      # 先用 100 根观察期
    while i < len(kl4):

        # 1. 计算最新 4H 趋势 & OB
        tr, info, ob = analyze_4h(kl4[:i+1], sym)
        if tr is None or ob is None:
            i+=1; continue

        # 2. 首次赋值
        if cur_tr is None:
            cur_tr, cur_ob = tr, ob

        # 3. 4H 趋势 / OB 改变 ⇒ 撤单 & 清理 15m
        if tr!=cur_tr or ob!=cur_ob:
            cancel_position(sym)
            trend15_states.pop(sym, None)
            state_open=False
            cur_tr, cur_ob = tr, ob

        # 4. 计算本根 4H 时间段
        st_4h, et_4h = ts4[i], ts4[i]+4*3600*1000-1
        log_message(f'[4H] {sym} {fmt(st_4h)} 趋势={tr}, OB={ob}')

        # 5. 若尚未进入 15m 状态机，需用 HH/LL 时间向前取 15m
        if not state_open:
            ref_idx = info['hh'][0] if tr=='uptrend' else info['ll'][0]
            #print("hh or ll",ref_idx)

            ### TODO : 一个强劲的上升趋势可能在20天前就形成了一个Higher Low。之后价格一路上涨，即便有小回调，但没有跌破那个关键的低点
            ## 在这里fetch_15m
            ref_ts  = ts4[ref_idx]
            kl15_window = fetch_15m(sym, ref_ts, et_4h)
            #print("kl15_window",kl15_window)
            if not kl15_window: i+=1; continue

            idx = first_touch_idx(kl15_window, tr, ob)
            #log_message(f'15m触碰ob idx={idx}')
            if idx is None:                     # 整窗无触碰
                i+=1; continue

            hist15  = kl15_window[:idx]         # 初始化片段
            feed15  = kl15_window[idx:]         # 含触碰及之后
            state   = Trend15State(sym, ob, tr, st_4h, hist15)
            state_open=True
        else:
            # 已在跟踪：仅取本根 4H 的 15m
            feed15 = fetch_15m(sym, st_4h, et_4h)
            if not feed15: i+=1; continue

        # 6. 逐根 15m 推进
        for ts,o,h,l,c in feed15:
            state.update([ts,o,h,l,c])

            # a) 止盈 / 止损
            pos = active_positions.get(sym)
            if pos:
                done, prof = exit_check(c, pos)
                if done:
                    removed = cancel_position(sym)
                    if removed:
                        wins  += prof>0
                        losses+= prof<0
                        pnl   += prof
                        log_trade(sym, removed['trend'],
                                  removed['entry'], removed['sl'],
                                  removed['tp'], prof)

            # b) OB 刺穿 ⇒ 冷却 & 清理
            if (tr=='uptrend' and l<ob['bottom']) or \
               (tr=='downtrend' and h>ob['top']):
                set_cooldown(sym, 24)
                cancel_position(sym)
                trend15_states.pop(sym, None)
                state_open=False
                break

            # c) 内部结构破坏 → 退出等待下一次触碰
            if state_open and (not state.ob_touched):
                state_open=False
                break

        i+=1                                    # 下一根 4H

    trades=wins+losses
    if trades==0: return None
    return {
        'symbol'  : sym,
        'trades'  : trades,
        'wins'    : wins,
        'losses'  : losses,
        'pnl'     : pnl,
        'win_rate': wins/trades*100
    }
# ──────────────────────────────────────────
if __name__=='__main__':
    #syms = fetch_usdt_contracts()[:200] or \
    #       ['BTC-USDT-SWAP','ETH-USDT-SWAP','SOL-USDT-SWAP']
    syms = ['PI-USDT-SWAP']
    res=[]
    for s in syms:
        print(f'\n=== 回测 {s} ===')
        r = backtest_symbol(s)
        if r: res.append(r)

    if res:
        df = pd.DataFrame(res)
        print(df)
        print('组合总盈亏', df['pnl'].sum(), 'USDT | 平均胜率',
              f"{df['win_rate'].mean():.2f}%")
    else:
        print('⚠ 无交易触发')


'''import time, pandas as pd
from datetime import datetime, timezone, timedelta
from config       import MAX_OPEN_POSITIONS
from okx_api      import fetch_usdt_contracts, fetch_4h_with_ts, fetch_15m
from strategy_4h  import analyze_4h
from strategy_15m import Trend15State
from risk_control import active_positions, cancel_position
from logger       import log_trade, log_message

CN_TZ = timezone(timedelta(hours=8))          # 北京时区

def fmt_ts(ts_ms:int)->str:
    """毫秒时间戳 → ‘YYYY-MM-DD HH:MM 整 (UTC+8)’"""
    return datetime.fromtimestamp(ts_ms/1000, CN_TZ)\
                   .strftime("%Y-%m-%d %H:%M 整")

# ————— 固定盈亏 —————
def exit_check(price,pos):
    if pos['trend']=='buy':
        if price<=pos['sl']: return True,-100
        if price>=pos['tp']: return True,+250
    else:
        if price>=pos['sl']: return True,-100
        if price<=pos['tp']: return True,+250
    return False,0

# ————— 回测单合约 —————
def backtest_symbol(symbol):
    kl4, ts4 = fetch_4h_with_ts(symbol, 300)
    if len(kl4) < 120:
        return None

    wins=losses=pnl=0
    cooldown_until = 0
    i = 100
    while i < len(kl4):
        trend, trend_info, ob = analyze_4h(kl4[:i+1], symbol)
        if trend is None or ob is None:
            i += 1; continue

        start_ts = ts4[i]
        end_ts   = ts4[i+1]-1 if i+1 < len(ts4) else int(time.time()*1000)
        bar_time = fmt_ts(start_ts)
        log_message(f"[4H] {symbol} {bar_time}  趋势={trend}, OB={ob}")

        kl15 = fetch_15m(symbol, start_ts, end_ts)
        if not kl15:
            i += 1; continue

        touched_idx = next(
            (j for j,(_,o,h,l,c) in enumerate(kl15)
             if (trend=='uptrend'   and ob['bottom']<=l<=ob['top']) or
                (trend=='downtrend' and ob['bottom']<=h<=ob['top'])),
            None)
        if touched_idx is None:
            i += 1; continue

        # —— 进入 15m 逻辑 ——
        t15 = Trend15State(symbol, ob, trend, kl15[touched_idx][0], kl15)
        for ts,o,h,l,c in kl15[touched_idx:]:
            t15.update([ts,o,h,l,c])

            if symbol in active_positions:
                done, prof = exit_check(c, active_positions[symbol])
                if done:
                    wins += prof>0; losses += prof<0; pnl += prof
                    log_trade(symbol, active_positions[symbol]['trend'],
                              active_positions[symbol]['entry'],
                              active_positions[symbol]['sl'],
                              active_positions[symbol]['tp'], prof)
                    cancel_position(symbol)

            if (trend=='uptrend' and l<ob['bottom']) or \
               (trend=='downtrend' and h>ob['top']):
                cooldown_until = ts + 86_400_000
                cancel_position(symbol); break
        i += 1

    trades=wins+losses
    return None if trades==0 else {
        "symbol":symbol,"trades":trades,"wins":wins,
        "losses":losses,"pnl":pnl,
        "win_rate":wins/trades*100 if trades else 0
    }

# ————— 主入口 —————
if __name__ == "__main__":
    symbols = fetch_usdt_contracts()[:MAX_OPEN_POSITIONS] or \
              ["BTC-USDT-SWAP","ETH-USDT-SWAP","SOL-USDT-SWAP"]

    results=[]
    for s in symbols:
        print(f"\n=== 回测 {s} ===")
        res=backtest_symbol(s)
        if res: results.append(res)

    if results:
        df=pd.DataFrame(results)
        print(df)
        print("组合总盈亏", df['pnl'].sum(),"USDT | 平均胜率",
              f"{df['win_rate'].mean():.2f}%")
    else:
        print("⚠ 无交易触发")'''




