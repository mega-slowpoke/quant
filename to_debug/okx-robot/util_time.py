# okx_quant_strategy/util_time.py
from datetime import datetime, timezone, timedelta

CN_TZ = timezone(timedelta(hours=8))

def fmt_ts(ms: int) -> str:
    """毫秒时间戳 → ‘YYYY-MM-DD HH:MM 整 (UTC+8)’"""
    return datetime.fromtimestamp(ms / 1000, CN_TZ)\
                   .strftime("%Y-%m-%d %H:%M 整")
