# okx_quant_strategy/config.py

API_KEY = "your_api_key"
SECRET_KEY = "your_secret_key"
PASSPHRASE = "your_passphrase"

BASE_URL = "https://www.okx.com"
MAX_OPEN_POSITIONS = 5
COOLDOWN_DURATION_HOURS = 24
MIN_VOLUME_THRESHOLD = 1_000_000  # 最低交易量过滤
FIXED_RISK_USD = 100  # 固定止损金额（单位：USDT）
TP_RATIO = 2.5  # 盈亏比
BACKTEST = True          # 回测=True；实盘=False


