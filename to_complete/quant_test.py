from quant_main import *
import okx.MarketData as MarketData
import okx.Account as Account
import matplotlib.pyplot as plt


config = read_config()
API_KEY = config.get("api_key")
SECRET_KEY = config.get("secret_key")
PASSPHRASE = config.get("passphrase")


def test_api_connection():
    flag = "1"

    market_api = MarketData.MarketAPI(API_KEY, SECRET_KEY, PASSPHRASE, False, flag)
    account_api = Account.AccountAPI(API_KEY, SECRET_KEY, PASSPHRASE, False, flag)

    # 测试市场数据获取
    result = market_api.get_candlesticks(instId="BTC-USDT-SWAP", bar="4H", limit="10")
    print("市场数据测试:", result)

    # 测试账户信息
    balance = account_api.get_account_balance()
    print("账户余额测试:", balance)


def test_kline_data():
    strategy = OKXTradingStrategy(API_KEY, SECRET_KEY, PASSPHRASE, True, "BTC-USDT-SWAP")

    # 测试4H数据获取
    h4_df = strategy.get_kline_data("BTC-USDT-SWAP", "4H", 20)
    print("4H数据形状:", h4_df.shape)
    print("4H数据列:", h4_df.columns.tolist())
    print("最新几根K线:")
    print(h4_df.tail())

    # 测试15分钟数据获取
    m15_df = strategy.get_kline_data("BTC-USDT-SWAP", "15m", 20)
    print("\n15分钟数据形状:", m15_df.shape)
    print("15分钟数据示例:")
    print(m15_df.tail())


def test_swing_points():
    strategy = OKXTradingStrategy(API_KEY, SECRET_KEY, PASSPHRASE, True, "BTC-USDT-SWAP")

    # 获取测试数据
    df = strategy.get_kline_data("BTC-USDT-SWAP", "4H", 50)

    # 测试摆动点识别
    swing_points = strategy.find_swing_points(df)
    print(f"找到 {len(swing_points['highs'])} 个高点")
    print(f"找到 {len(swing_points['lows'])} 个低点")

    # 可视化摆动点
    plt.figure(figsize=(15, 8))
    plt.plot(df.index, df['close'], label='Close Price', linewidth=1)

    # 标记高点
    for high in swing_points['highs']:
        plt.scatter(high['index'], high['price'], color='red', s=50, marker='^')

    # 标记低点
    for low in swing_points['lows']:
        plt.scatter(low['index'], low['price'], color='green', s=50, marker='v')

    plt.legend()
    plt.title('摆动点识别测试')
    plt.show()

    return swing_points


def test_filtered_points():
    strategy = OKXTradingStrategy(API_KEY, SECRET_KEY, PASSPHRASE, True, "BTC-USDT-SWAP")
    df = strategy.get_kline_data("BTC-USDT-SWAP", "4H", 50)

    # 原始摆动点
    swing_points = strategy.find_swing_points(df)
    print("原始摆动点:")
    print(f"高点数量: {len(swing_points['highs'])}")
    print(f"低点数量: {len(swing_points['lows'])}")

    # 过滤后的摆动点
    filtered_points = strategy.filter_swing_points(swing_points)
    print(f"\n过滤后摆动点数量: {len(filtered_points)}")

    # 验证高低点交替
    for i, point in enumerate(filtered_points):
        print(f"点 {i + 1}: {point['type']} - 价格: {point['price']:.2f} - 时间: {point['timestamp']}")

    # 检查是否真正交替
    types = [p['type'] for p in filtered_points]
    alternating = all(types[i] != types[i + 1] for i in range(len(types) - 1))
    print(f"\n高低点是否正确交替: {alternating}")

    return filtered_points


def test_trend_analysis():
    strategy = OKXTradingStrategy(API_KEY, SECRET_KEY, PASSPHRASE, True, "BTC-USDT-SWAP")
    df = strategy.get_kline_data("BTC-USDT-SWAP", "4H", 100)

    # 分析趋势
    h4_structure = strategy.analyze_h4_trend(df)

    print("4H趋势分析结果:")
    print(f"趋势方向: {h4_structure['trend']}")
    print(f"摆动点数量: {len(h4_structure['points']) if h4_structure['points'] else 0}")

    if h4_structure['trend'] == 'up':
        if h4_structure['higher_high']:
            print(f"Higher High: {h4_structure['higher_high']['price']:.2f}")
        if h4_structure['higher_low']:
            print(f"Higher Low: {h4_structure['higher_low']['price']:.2f}")
    elif h4_structure['trend'] == 'down':
        if h4_structure['lower_high']:
            print(f"Lower High: {h4_structure['lower_high']['price']:.2f}")
        if h4_structure['lower_low']:
            print(f"Lower Low: {h4_structure['lower_low']['price']:.2f}")

    return h4_structure


def test_order_block():
    strategy = OKXTradingStrategy(API_KEY, SECRET_KEY, PASSPHRASE, True, "BTC-USDT-SWAP")
    df = strategy.get_kline_data("BTC-USDT-SWAP", "4H", 100)

    # 分析趋势和OB
    h4_structure = strategy.analyze_h4_trend(df)
    h4_ob = strategy.identify_order_block(df, h4_structure)

    print("订单块识别结果:")
    if h4_ob:
        print(f"OB类型: {h4_ob['type']}")
        print(f"OB高点: {h4_ob['high']:.2f}")
        print(f"OB低点: {h4_ob['low']:.2f}")
        print(f"OB时间: {h4_ob['timestamp']}")

        # 检查当前价格是否在OB范围内
        current_price = df.iloc[-1]['close']
        is_touching = strategy.check_ob_touch(current_price, h4_ob)
        print(f"当前价格 {current_price:.2f} 是否触及OB: {is_touching}")
    else:
        print("未找到有效的订单块")

    return h4_ob


def test_m15_structure():
    strategy = OKXTradingStrategy(API_KEY, SECRET_KEY, PASSPHRASE, True, "BTC-USDT-SWAP")

    # 获取数据
    h4_df = strategy.get_kline_data("BTC-USDT-SWAP", "4H", 100)
    m15_df = strategy.get_kline_data("BTC-USDT-SWAP", "15m", 200)

    # 分析4H结构
    h4_structure = strategy.analyze_h4_trend(h4_df)

    if h4_structure['trend'] == 'up':
        # 分析15分钟结构
        m15_structure = strategy.analyze_m15_structure(m15_df, h4_structure)

        print("15分钟结构分析:")
        print(f"趋势: {m15_structure.get('trend', 'None')}")
        if m15_structure.get('lower_high'):
            print(f"Lower High: {m15_structure['lower_high']['price']:.2f}")
        if m15_structure.get('lower_low'):
            print(f"Lower Low: {m15_structure['lower_low']['price']:.2f}")

        return m15_structure


def test_structure_break():
    strategy = OKXTradingStrategy(API_KEY, SECRET_KEY, PASSPHRASE, True, "BTC-USDT-SWAP")

    # 模拟一些测试数据
    test_candle = {
        'open': 45000,
        'close': 45200,
        'high': 45300,
        'low': 44900
    }

    test_structure = {
        'trend': 'down',
        'lower_high': {'price': 45100}
    }

    # 测试结构突破检测
    is_break = strategy.check_structure_break(test_candle, test_structure)
    print(f"测试K线实体高点: {max(test_candle['open'], test_candle['close'])}")
    print(f"Lower High价格: {test_structure['lower_high']['price']}")
    print(f"是否发生结构突破: {is_break}")


def test_trading_signals():
    """测试交易信号生成，但不实际下单"""
    strategy = OKXTradingStrategy(API_KEY, SECRET_KEY, PASSPHRASE, True, "BTC-USDT-SWAP")

    # 重写place_order方法，只打印不实际下单
    def mock_place_order(side, price, stop_loss, take_profit, size=0.01):
        print(f"\n=== 模拟下单 ===")
        print(f"方向: {side}")
        print(f"入场价: {price:.2f}")
        print(f"止损价: {stop_loss:.2f}")
        print(f"止盈价: {take_profit:.2f}")
        print(f"风险: {abs(price - stop_loss):.2f}")
        print(f"盈亏比: {abs(take_profit - price) / abs(price - stop_loss):.2f}")
        print(f"仓位: {size}")

    strategy.place_order = mock_place_order

    # 运行一次完整的分析流程
    h4_df = strategy.get_kline_data("BTC-USDT-SWAP", "4H", 100)
    h4_structure = strategy.analyze_h4_trend(h4_df)
    h4_ob = strategy.identify_order_block(h4_df, h4_structure)

    print("=== 4H分析结果 ===")
    print(f"趋势: {h4_structure['trend']}")
    if h4_ob:
        print(f"OB类型: {h4_ob['type']}")
        print(f"OB范围: {h4_ob['low']:.2f} - {h4_ob['high']:.2f}")


if __name__ == "__main__":
    print("----- test api connection ----")
    test_api_connection()

    print()
    test_kline_data()

    test_swing_points()

    test_filtered_points()

    test_trend_analysis()
    test_order_block()

    test_m15_structure()

    test_structure_break()

    test_trading_signals()