# okx_quant_strategy/order_exec.py
from config   import BACKTEST
from logger   import log_message
from okx_api  import place_limit_order, round_price

def send_order(action, symbol, entry, sl, tp, size):
    """
    action: 'buy' or 'sell'
    回测 → 打印；实盘 → 真下单
    """
    if BACKTEST:
        log_message(f"[MOCK-ORDER] {action.upper()} {symbol} "
                    f"entry={entry} sl={sl} tp={tp} size={size}")
    else:
        place_limit_order(symbol,
                          round_price(symbol, entry),
                          action, sl, tp, size)

