# okx_quant_strategy/logger.py
import logging
import os
from datetime import datetime

# 创建 logs 目录
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# 文件名按日期区分
log_file = os.path.join(
    LOG_DIR, f"trading_{datetime.utcnow().strftime('%Y%m%d')}.log"
)

# 配置 logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file, mode="a", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)

# ———— 供外部直接写入文本 ————
def log_message(msg: str):
    """
    简单写一条 info 级别日志，兼容 risk_control.py 的调用。
    """
    logger.info(msg)

# ———— 交易专用封装 ————
def log_trade(symbol, side, entry, sl=None, tp=None, pnl=None):
    """
    side: 'buy' or 'sell'
    可以只传必须字段，其余字段留 None
    """
    logger.info(
        f"[TRADE] {symbol} {side.upper()} entry={entry} "
        f"SL={sl} TP={tp} PnL={pnl}"
    )

