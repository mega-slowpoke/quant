import okx.Account as Account
import okx.MarketData as MarketData
import okx.Trade as Trade
import okx.PublicData as PublicData
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Tuple, Optional
import json

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class OKXTradingStrategy:
    def __init__(self, api_key: str, secret_key: str, passphrase: str,
                 sandbox: bool = True, symbol: str = "BTC-USDT-SWAP"):
        # 配置OKX API
        flag = "1" if sandbox else "0"  # 实盘：0, 模拟盘：1

        self.market_api = MarketData.MarketAPI(api_key, secret_key, passphrase,
                                               False, flag)
        self.account_api = Account.AccountAPI(api_key, secret_key, passphrase,
                                              False, flag)
        self.trade_api = Trade.TradeAPI(api_key, secret_key, passphrase,
                                        False, flag)

        self.symbol = symbol
        self.cooldown_pairs = {}  # 冷却的交易对
        self.active_orders = {}  # 活跃订单

        # 策略状态
        self.h4_trend = None  # 4H趋势方向
        self.h4_ob = None  # 4H订单块
        self.m15_trend = None  # 15分钟趋势
        self.m15_structure = {}  # 15分钟结构数据

    # 获取K线数据, instId: 交易对, bar: 时间周期 ('4H', '15m')
    def get_kline_data(self, instId: str, bar: str, limit: int = 100) -> pd.DataFrame:
        try:
            result = self.market_api.get_candlesticks(instId=instId, bar=bar, limit=str(limit))

            if result['code'] != '0':
                logger.error(f"获取K线数据失败: {result['msg']}")
                return pd.DataFrame()

            data = result['data']
            df = pd.DataFrame(data,
                              columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'volCcy', 'volCcyQuote',
                                       'confirm'])

            # 数据类型转换
            df['timestamp'] = pd.to_datetime(df['timestamp'].astype(int), unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)

            # 按时间排序
            df = df.sort_values('timestamp').reset_index(drop=True)
            return df

        except Exception as e:
            logger.error(f"获取K线数据异常: {e}")
            return pd.DataFrame()

    # 找到higher high 和 higher low
    def find_swing_points(self, df: pd.DataFrame) -> Dict:
        """
        找到摆动高点和低点
        :param df: K线数据
        :return: 高点和低点字典
        """
        highs = []
        lows = []

        for i in range(1, len(df) - 1):
            # 高点：当前高点高于前后各一根K线
            if df.iloc[i]['high'] > df.iloc[i - 1]['high'] and df.iloc[i]['high'] > df.iloc[i + 1]['high']:
                highs.append({
                    'index': i,
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['high'],
                    'type': 'high'
                })

            # 低点：当前低点低于前后各一根K线
            if df.iloc[i]['low'] < df.iloc[i - 1]['low'] and df.iloc[i]['low'] < df.iloc[i + 1]['low']:
                lows.append({
                    'index': i,
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['low'],
                    'type': 'low'
                })

        return {'highs': highs, 'lows': lows}

    def filter_swing_points(self, swing_points: Dict) -> List:
        """
        过滤摆动点，确保高点低点交替出现
        :param swing_points: 原始摆动点
        :return: 过滤后的摆动点列表
        """
        all_points = swing_points['highs'] + swing_points['lows']
        all_points.sort(key=lambda x: x['index'])

        if not all_points:
            return []

        filtered_points = [all_points[0]]
        pending_points = []

        for point in all_points[1:]:
            last_point = filtered_points[-1]

            # 如果类型相同，需要选择极值
            if point['type'] == last_point['type']:
                pending_points.append(point)
            else:
                # 处理堆积的相同类型点
                if pending_points:
                    if last_point['type'] == 'high':
                        # 选择最高点
                        max_point = max([last_point] + pending_points, key=lambda x: x['price'])
                    else:
                        # 选择最低点
                        max_point = min([last_point] + pending_points, key=lambda x: x['price'])

                    filtered_points[-1] = max_point
                    pending_points = []

                filtered_points.append(point)

        # 处理最后的堆积点
        if pending_points:
            if filtered_points[-1]['type'] == 'high':
                max_point = max([filtered_points[-1]] + pending_points, key=lambda x: x['price'])
            else:
                max_point = min([filtered_points[-1]] + pending_points, key=lambda x: x['price'])
            filtered_points[-1] = max_point

        return filtered_points

    def determine_initial_trend(self, points: List) -> Optional[str]:
        """
        确定初始趋势
        :param points: 过滤后的摆动点
        :return: 趋势方向 ('up', 'down', None)
        """
        if len(points) < 4:
            return None

        # 获取前4个点
        first_four = points[:4]

        # 分离高点和低点
        highs = [p for p in first_four if p['type'] == 'high']
        lows = [p for p in first_four if p['type'] == 'low']

        if len(highs) < 2 or len(lows) < 2:
            return None

        # 按时间排序
        highs.sort(key=lambda x: x['index'])
        lows.sort(key=lambda x: x['index'])

        # 判断趋势
        higher_highs = highs[1]['price'] > highs[0]['price']
        higher_lows = lows[1]['price'] > lows[0]['price']

        if higher_highs and higher_lows:
            return 'up'

        lower_highs = highs[1]['price'] < highs[0]['price']
        lower_lows = lows[1]['price'] < lows[0]['price']

        if lower_highs and lower_lows:
            return 'down'

        return None

    def analyze_h4_trend(self, df: pd.DataFrame) -> Dict:
        """
        分析4H趋势
        :param df: 4H K线数据
        :return: 趋势分析结果
        """
        swing_points = self.find_swing_points(df)
        filtered_points = self.filter_swing_points(swing_points)

        if len(filtered_points) < 4:
            return {'trend': None, 'structure': None}

        initial_trend = self.determine_initial_trend(filtered_points)

        # 构建趋势结构
        structure = {
            'trend': initial_trend,
            'points': filtered_points,
            'higher_high': None,
            'higher_low': None,
            'lower_high': None,
            'lower_low': None
        }

        if initial_trend == 'up':
            highs = [p for p in filtered_points if p['type'] == 'high']
            lows = [p for p in filtered_points if p['type'] == 'low']

            if highs:
                structure['higher_high'] = max(highs, key=lambda x: x['price'])
            if lows:
                structure['higher_low'] = max(lows, key=lambda x: x['index'])

        elif initial_trend == 'down':
            highs = [p for p in filtered_points if p['type'] == 'high']
            lows = [p for p in filtered_points if p['type'] == 'low']

            if highs:
                structure['lower_high'] = min(highs, key=lambda x: x['index'])
            if lows:
                structure['lower_low'] = min(lows, key=lambda x: x['price'])

        return structure

    def identify_order_block(self, df: pd.DataFrame, structure: Dict) -> Optional[Dict]:
        """
        识别订单块(OB)
        :param df: K线数据
        :param structure: 趋势结构
        :return: 订单块信息
        """
        if not structure or not structure['trend']:
            return None

        trend = structure['trend']

        if trend == 'up' and structure['higher_low']:
            # 上涨趋势，找最新higher_low之前的下跌K线实体
            hl_index = structure['higher_low']['index']

            # 查找hl_index之前的下跌K线
            for i in range(hl_index - 1, -1, -1):
                if df.iloc[i]['close'] < df.iloc[i]['open']:  # 下跌K线
                    return {
                        'type': 'bullish',
                        'high': max(df.iloc[i]['open'], df.iloc[i]['close']),
                        'low': min(df.iloc[i]['open'], df.iloc[i]['close']),
                        'index': i,
                        'timestamp': df.iloc[i]['timestamp']
                    }

        elif trend == 'down' and structure['lower_high']:
            # 下跌趋势，找最新lower_high之前的上涨K线实体
            lh_index = structure['lower_high']['index']

            # 查找lh_index之前的上涨K线
            for i in range(lh_index - 1, -1, -1):
                if df.iloc[i]['close'] > df.iloc[i]['open']:  # 上涨K线
                    return {
                        'type': 'bearish',
                        'high': max(df.iloc[i]['open'], df.iloc[i]['close']),
                        'low': min(df.iloc[i]['open'], df.iloc[i]['close']),
                        'index': i,
                        'timestamp': df.iloc[i]['timestamp']
                    }

        return None

    def check_ob_touch(self, current_price: float, ob: Dict) -> bool:
        """
        检查是否触及订单块
        :param current_price: 当前价格
        :param ob: 订单块
        :return: 是否触及
        """
        if not ob:
            return False

        if ob['type'] == 'bullish':
            return ob['low'] <= current_price <= ob['high']
        else:  # bearish
            return ob['low'] <= current_price <= ob['high']

    def analyze_m15_structure(self, df: pd.DataFrame, h4_structure: Dict) -> Dict:
        """
        分析15分钟结构
        :param df: 15分钟K线数据
        :param h4_structure: 4H结构
        :return: 15分钟结构分析
        """
        if not h4_structure or not h4_structure['higher_high']:
            return {}

        # 找到4H higher_high对应的时间点
        hh_time = h4_structure['higher_high']['timestamp']

        # 筛选higher_high之后的15分钟数据
        after_hh = df[df['timestamp'] > hh_time].reset_index(drop=True)

        if len(after_hh) < 4:
            return {}

        # 分析15分钟摆动点
        swing_points = self.find_swing_points(after_hh)
        filtered_points = self.filter_swing_points(swing_points)

        # 寻找下跌趋势的四个点
        if len(filtered_points) >= 4:
            trend = self.determine_initial_trend(filtered_points)
            if trend == 'down':
                structure = {
                    'trend': 'down',
                    'points': filtered_points,
                    'lower_high': None,
                    'lower_low': None
                }

                highs = [p for p in filtered_points if p['type'] == 'high']
                lows = [p for p in filtered_points if p['type'] == 'low']

                if highs:
                    structure['lower_high'] = min(highs, key=lambda x: x['index'])
                if lows:
                    structure['lower_low'] = min(lows, key=lambda x: x['price'])

                return structure

        return {}

    def check_structure_break(self, current_candle: pd.Series, m15_structure: Dict) -> bool:
        """
        检查结构突破
        :param current_candle: 当前K线
        :param m15_structure: 15分钟结构
        :return: 是否发生结构突破
        """
        if not m15_structure or not m15_structure.get('lower_high'):
            return False

        lower_high_price = m15_structure['lower_high']['price']

        # 实体突破影线的标准
        candle_body_high = max(current_candle['open'], current_candle['close'])

        return candle_body_high > lower_high_price

    def place_order(self, side: str, price: float, stop_loss: float, take_profit: float, size: float = 0.01):
        """
        下单
        :param side: 方向 ('buy', 'sell')
        :param price: 入场价格
        :param stop_loss: 止损价格
        :param take_profit: 止盈价格
        :param size: 下单数量
        """
        try:
            # 下限价单
            order_result = self.trade_api.place_order(
                instId=self.symbol,
                tdMode="cross",
                side=side,
                ordType="limit",
                px=str(price),
                sz=str(size)
            )

            if order_result['code'] == '0':
                order_id = order_result['data'][0]['ordId']
                logger.info(f"订单已下达: {order_id}, 方向: {side}, 价格: {price}")

                # 设置止损止盈
                self.set_stop_orders(order_id, stop_loss, take_profit, side, size)

                self.active_orders[order_id] = {
                    'side': side,
                    'price': price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'size': size,
                    'timestamp': datetime.now()
                }

            else:
                logger.error(f"下单失败: {order_result['msg']}")

        except Exception as e:
            logger.error(f"下单异常: {e}")

    def set_stop_orders(self, order_id: str, stop_loss: float, take_profit: float, side: str, size: float):
        """
        设置止损止盈单
        """
        try:
            # 设置止损单
            sl_side = "sell" if side == "buy" else "buy"

            self.trade_api.place_order(
                instId=self.symbol,
                tdMode="cross",
                side=sl_side,
                ordType="conditional",
                sz=str(size),
                slTriggerPx=str(stop_loss),
                slOrdPx=str(stop_loss)
            )

            # 设置止盈单
            self.trade_api.place_order(
                instId=self.symbol,
                tdMode="cross",
                side=sl_side,
                ordType="conditional",
                sz=str(size),
                tpTriggerPx=str(take_profit),
                tpOrdPx=str(take_profit)
            )

            logger.info(f"止损止盈已设置: SL={stop_loss}, TP={take_profit}")

        except Exception as e:
            logger.error(f"设置止损止盈异常: {e}")

    def cancel_orders(self):
        """
        取消所有活跃订单
        """
        try:
            for order_id in list(self.active_orders.keys()):
                result = self.trade_api.cancel_order(instId=self.symbol, ordId=order_id)
                if result['code'] == '0':
                    logger.info(f"订单已取消: {order_id}")
                    del self.active_orders[order_id]
        except Exception as e:
            logger.error(f"取消订单异常: {e}")

    def run_strategy(self):
        """
        运行策略主循环
        """
        logger.info("策略启动...")

        while True:
            try:
                # 检查冷却期
                current_time = datetime.now()
                for pair in list(self.cooldown_pairs.keys()):
                    if current_time - self.cooldown_pairs[pair] > timedelta(days=1):
                        del self.cooldown_pairs[pair]
                        logger.info(f"交易对 {pair} 冷却期结束")

                if self.symbol in self.cooldown_pairs:
                    logger.info(f"交易对 {self.symbol} 仍在冷却期")
                    time.sleep(900)  # 15分钟后再检查
                    continue

                # 1. 获取4H K线数据并分析趋势
                h4_df = self.get_kline_data(self.symbol, '4H', 100)
                if h4_df.empty:
                    logger.warning("无法获取4H数据")
                    time.sleep(60)
                    continue

                h4_structure = self.analyze_h4_trend(h4_df)
                if not h4_structure['trend']:
                    logger.info("4H趋势不明确")
                    time.sleep(900)
                    continue

                # 2. 识别4H订单块
                h4_ob = self.identify_order_block(h4_df, h4_structure)
                if not h4_ob:
                    logger.info("未找到4H订单块")
                    time.sleep(900)
                    continue

                logger.info(f"4H趋势: {h4_structure['trend']}, OB类型: {h4_ob['type']}")

                # 3. 15分钟级别监控
                self.monitor_15min(h4_structure, h4_ob, h4_df)

            except Exception as e:
                logger.error(f"策略运行异常: {e}")
                time.sleep(60)

    def monitor_15min(self, h4_structure: Dict, h4_ob: Dict, h4_df: pd.DataFrame):
        """
        15分钟级别监控
        """
        logger.info("开始15分钟监控...")

        while True:
            try:
                # 获取15分钟数据
                m15_df = self.get_kline_data(self.symbol, '15m', 100)
                if m15_df.empty:
                    time.sleep(60)
                    continue

                current_candle = m15_df.iloc[-1]
                current_price = current_candle['close']

                # 检查是否触及4H OB
                if self.check_ob_touch(current_price, h4_ob):
                    logger.info(f"价格触及4H OB: {current_price}")

                    # 检查是否跌破OB低点
                    if ((h4_ob['type'] == 'bullish' and current_candle['close'] < h4_ob['low']) or
                            (h4_ob['type'] == 'bearish' and current_candle['close'] > h4_ob['high'])):
                        logger.info(f"价格跌破/涨破OB边界，进入冷却期")
                        self.cooldown_pairs[self.symbol] = datetime.now()
                        return

                    # 分析15分钟结构
                    if h4_structure['trend'] == 'up':
                        self.handle_bullish_ob_touch(m15_df, h4_structure, h4_ob)
                    else:
                        self.handle_bearish_ob_touch(m15_df, h4_structure, h4_ob)

                    return

                time.sleep(900)  # 15分钟检查一次

            except Exception as e:
                logger.error(f"15分钟监控异常: {e}")
                time.sleep(60)

    def handle_bullish_ob_touch(self, m15_df: pd.DataFrame, h4_structure: Dict, h4_ob: Dict):
        """
        处理看涨OB触碰
        """
        logger.info("处理看涨OB触碰...")

        # 分析15分钟结构，寻找下跌趋势
        m15_structure = self.analyze_m15_structure(m15_df, h4_structure)

        if not m15_structure or m15_structure.get('trend') != 'down':
            logger.info("15分钟下跌趋势不明确")
            return

        # 设置lower_low为触及OB的K线低点
        current_candle = m15_df.iloc[-1]
        m15_structure['lower_low'] = {
            'price': current_candle['low'],
            'index': len(m15_df) - 1,
            'timestamp': current_candle['timestamp']
        }

        logger.info(f"15分钟结构确认，开始监控结构突破...")

        # 监控结构突破
        while True:
            try:
                m15_df = self.get_kline_data(self.symbol, '15m', 100)
                if m15_df.empty:
                    time.sleep(60)
                    continue

                current_candle = m15_df.iloc[-1]

                # 检查结构突破
                if self.check_structure_break(current_candle, m15_structure):
                    logger.info("检测到结构突破，准备下单...")

                    # 构建15分钟看涨OB
                    m15_ob = self.find_m15_bullish_ob(m15_df, m15_structure)

                    if m15_ob:
                        # 计算交易参数
                        entry_price = m15_ob['high']
                        stop_loss = m15_structure['lower_low']['price']
                        risk = entry_price - stop_loss
                        take_profit = entry_price + (risk * 2.5)  # 2.5倍盈亏比

                        # 下单
                        self.place_order('buy', entry_price, stop_loss, take_profit)

                        # 监控订单执行和后续价格行为
                        self.monitor_trade_execution(m15_structure, 'up')
                        return

                # 检查是否跌破higher_low（如果存在）
                if (m15_structure.get('higher_low') and
                        self.check_body_break_below(current_candle, m15_structure['higher_low']['price'])):
                    logger.info("价格跌破higher_low，取消监控")
                    self.cancel_orders()
                    return

                time.sleep(900)  # 15分钟检查一次

            except Exception as e:
                logger.error(f"看涨OB监控异常: {e}")
                time.sleep(60)

    def handle_bearish_ob_touch(self, m15_df: pd.DataFrame, h4_structure: Dict, h4_ob: Dict):
        """
        处理看跌OB触碰
        """
        logger.info("处理看跌OB触碰...")

        # 分析15分钟结构，寻找上涨趋势
        m15_structure = self.analyze_m15_structure_bearish(m15_df, h4_structure)

        if not m15_structure or m15_structure.get('trend') != 'up':
            logger.info("15分钟上涨趋势不明确")
            return

        # 设置higher_high为触及OB的K线高点
        current_candle = m15_df.iloc[-1]
        m15_structure['higher_high'] = {
            'price': current_candle['high'],
            'index': len(m15_df) - 1,
            'timestamp': current_candle['timestamp']
        }

        logger.info(f"15分钟结构确认，开始监控结构突破...")

        # 监控结构突破
        while True:
            try:
                m15_df = self.get_kline_data(self.symbol, '15m', 100)
                if m15_df.empty:
                    time.sleep(60)
                    continue

                current_candle = m15_df.iloc[-1]

                # 检查结构突破（向下）
                if self.check_structure_break_bearish(current_candle, m15_structure):
                    logger.info("检测到向下结构突破，准备下单...")

                    # 构建15分钟看跌OB
                    m15_ob = self.find_m15_bearish_ob(m15_df, m15_structure)

                    if m15_ob:
                        # 计算交易参数
                        entry_price = m15_ob['low']
                        stop_loss = m15_structure['higher_high']['price']
                        risk = stop_loss - entry_price
                        take_profit = entry_price - (risk * 2.5)  # 2.5倍盈亏比

                        # 下单
                        self.place_order('sell', entry_price, stop_loss, take_profit)

                        # 监控订单执行和后续价格行为
                        self.monitor_trade_execution(m15_structure, 'down')
                        return

                # 检查是否涨破lower_high（如果存在）
                if (m15_structure.get('lower_high') and
                        self.check_body_break_above(current_candle, m15_structure['lower_high']['price'])):
                    logger.info("价格涨破lower_high，取消监控")
                    self.cancel_orders()
                    return

                time.sleep(900)  # 15分钟检查一次

            except Exception as e:
                logger.error(f"看跌OB监控异常: {e}")
                time.sleep(60)

    def analyze_m15_structure_bearish(self, df: pd.DataFrame, h4_structure: Dict) -> Dict:
        """
        分析15分钟结构（针对看跌场景）
        """
        if not h4_structure or not h4_structure['lower_low']:
            return {}

        # 找到4H lower_low对应的时间点
        ll_time = h4_structure['lower_low']['timestamp']

        # 筛选lower_low之后的15分钟数据
        after_ll = df[df['timestamp'] > ll_time].reset_index(drop=True)

        if len(after_ll) < 4:
            return {}

        # 分析15分钟摆动点
        swing_points = self.find_swing_points(after_ll)
        filtered_points = self.filter_swing_points(swing_points)

        # 寻找上涨趋势的四个点
        if len(filtered_points) >= 4:
            trend = self.determine_initial_trend(filtered_points)
            if trend == 'up':
                structure = {
                    'trend': 'up',
                    'points': filtered_points,
                    'higher_high': None,
                    'higher_low': None
                }

                highs = [p for p in filtered_points if p['type'] == 'high']
                lows = [p for p in filtered_points if p['type'] == 'low']

                if highs:
                    structure['higher_high'] = max(highs, key=lambda x: x['price'])
                if lows:
                    structure['higher_low'] = max(lows, key=lambda x: x['index'])

                return structure

        return {}

    def check_structure_break_bearish(self, current_candle: pd.Series, m15_structure: Dict) -> bool:
        """
        检查向下结构突破
        """
        if not m15_structure or not m15_structure.get('higher_low'):
            return False

        higher_low_price = m15_structure['higher_low']['price']

        # 实体突破影线的标准
        candle_body_low = min(current_candle['open'], current_candle['close'])

        return candle_body_low < higher_low_price

    def check_body_break_below(self, candle: pd.Series, price: float) -> bool:
        """
        检查实体是否跌破指定价格
        """
        candle_body_low = min(candle['open'], candle['close'])
        return candle_body_low < price

    def check_body_break_above(self, candle: pd.Series, price: float) -> bool:
        """
        检查实体是否涨破指定价格
        """
        candle_body_high = max(candle['open'], candle['close'])
        return candle_body_high > price

    def find_m15_bullish_ob(self, df: pd.DataFrame, m15_structure: Dict) -> Optional[Dict]:
        """
        找到15分钟看涨OB（下跌K线）
        """
        if not m15_structure or not m15_structure.get('lower_high'):
            return None

        lh_index = m15_structure['lower_high']['index']

        # 查找lower_high之前的下跌K线
        for i in range(lh_index - 1, -1, -1):
            if df.iloc[i]['close'] < df.iloc[i]['open']:  # 下跌K线
                return {
                    'type': 'bullish',
                    'high': max(df.iloc[i]['open'], df.iloc[i]['close']),
                    'low': min(df.iloc[i]['open'], df.iloc[i]['close']),
                    'index': i,
                    'timestamp': df.iloc[i]['timestamp']
                }

        return None

    def find_m15_bearish_ob(self, df: pd.DataFrame, m15_structure: Dict) -> Optional[Dict]:
        """
        找到15分钟看跌OB（上涨K线）
        """
        if not m15_structure or not m15_structure.get('higher_low'):
            return None

        hl_index = m15_structure['higher_low']['index']

        # 查找higher_low之前的上涨K线
        for i in range(hl_index - 1, -1, -1):
            if df.iloc[i]['close'] > df.iloc[i]['open']:  # 上涨K线
                return {
                    'type': 'bearish',
                    'high': max(df.iloc[i]['open'], df.iloc[i]['close']),
                    'low': min(df.iloc[i]['open'], df.iloc[i]['close']),
                    'index': i,
                    'timestamp': df.iloc[i]['timestamp']
                }

        return None

    def monitor_trade_execution(self, m15_structure: Dict, trend_direction: str):
        """
        监控交易执行和后续价格行为
        """
        logger.info(f"开始监控 {trend_direction} 趋势交易执行...")

        pending_points = []  # 存储待处理的同类型点

        while True:
            try:
                # 获取最新15分钟数据
                m15_df = self.get_kline_data(self.symbol, '15m', 100)
                if m15_df.empty:
                    time.sleep(60)
                    continue

                current_candle = m15_df.iloc[-1]

                # 检查订单状态
                if not self.active_orders:
                    logger.info("无活跃订单，退出监控")
                    return

                # 检查趋势破坏
                if trend_direction == 'up':
                    if (m15_structure.get('higher_low') and
                            self.check_body_break_below(current_candle, m15_structure['higher_low']['price'])):
                        logger.info("上涨趋势破坏，取消订单")
                        self.cancel_orders()
                        return
                else:  # down
                    if (m15_structure.get('lower_high') and
                            self.check_body_break_above(current_candle, m15_structure['lower_high']['price'])):
                        logger.info("下跌趋势破坏，取消订单")
                        self.cancel_orders()
                        return

                # 更新结构
                self.update_m15_structure(m15_df, m15_structure, trend_direction, pending_points)

                time.sleep(900)  # 15分钟检查一次

            except Exception as e:
                logger.error(f"交易监控异常: {e}")
                time.sleep(60)

    def update_m15_structure(self, df: pd.DataFrame, structure: Dict, trend_direction: str, pending_points: List):
        """
        更新15分钟结构
        """
        if len(df) < 2:
            return

        # 检查前一根K线是否是摆动点（需要后一根K线确认）
        prev_candle = df.iloc[-2]
        current_candle = df.iloc[-1]

        if len(df) < 3:
            return

        prev_prev_candle = df.iloc[-3]

        # 判断前一根K线是否是高点或低点
        is_high = (prev_candle['high'] > prev_prev_candle['high'] and
                   prev_candle['high'] > current_candle['high'])
        is_low = (prev_candle['low'] < prev_prev_candle['low'] and
                  prev_candle['low'] < current_candle['low'])

        if not (is_high or is_low):
            return

        new_point = {
            'index': len(df) - 2,
            'timestamp': prev_candle['timestamp'],
            'price': prev_candle['high'] if is_high else prev_candle['low'],
            'type': 'high' if is_high else 'low'
        }

        # 根据趋势方向处理新点
        if trend_direction == 'up':
            self.process_uptrend_point(new_point, structure, pending_points)
        else:
            self.process_downtrend_point(new_point, structure, pending_points)

    def process_uptrend_point(self, new_point: Dict, structure: Dict, pending_points: List):
        """
        处理上涨趋势中的新摆动点
        """
        last_type = None
        if structure.get('higher_high'):
            last_type = 'high'
        elif structure.get('higher_low'):
            last_type = 'low'

        if new_point['type'] == 'high':
            if last_type == 'high' or pending_points:
                # 连续高点，选择最高的
                all_highs = [new_point] + [p for p in pending_points if p['type'] == 'high']
                if structure.get('higher_high'):
                    all_highs.append({
                        'price': structure['higher_high']['price'],
                        'index': structure['higher_high']['index'],
                        'timestamp': structure['higher_high']['timestamp'],
                        'type': 'high'
                    })

                highest = max(all_highs, key=lambda x: x['price'])
                structure['higher_high'] = highest
                pending_points.clear()
            else:
                # 正常的高点更新
                if (not structure.get('higher_high') or
                        new_point['price'] > structure['higher_high']['price']):
                    structure['higher_high'] = new_point

        elif new_point['type'] == 'low':
            if last_type == 'low' or any(p['type'] == 'low' for p in pending_points):
                # 连续低点，选择最高的（higher low）
                all_lows = [new_point] + [p for p in pending_points if p['type'] == 'low']
                if structure.get('higher_low'):
                    all_lows.append({
                        'price': structure['higher_low']['price'],
                        'index': structure['higher_low']['index'],
                        'timestamp': structure['higher_low']['timestamp'],
                        'type': 'low'
                    })

                highest_low = max(all_lows, key=lambda x: x['price'])
                structure['higher_low'] = highest_low
                pending_points.clear()
            else:
                # 正常的低点更新
                if (not structure.get('higher_low') or
                        new_point['price'] > structure['higher_low']['price']):
                    structure['higher_low'] = new_point

    def process_downtrend_point(self, new_point: Dict, structure: Dict, pending_points: List):
        """
        处理下跌趋势中的新摆动点
        """
        last_type = None
        if structure.get('lower_low'):
            last_type = 'low'
        elif structure.get('lower_high'):
            last_type = 'high'

        if new_point['type'] == 'low':
            if last_type == 'low' or pending_points:
                # 连续低点，选择最低的
                all_lows = [new_point] + [p for p in pending_points if p['type'] == 'low']
                if structure.get('lower_low'):
                    all_lows.append({
                        'price': structure['lower_low']['price'],
                        'index': structure['lower_low']['index'],
                        'timestamp': structure['lower_low']['timestamp'],
                        'type': 'low'
                    })

                lowest = min(all_lows, key=lambda x: x['price'])
                structure['lower_low'] = lowest
                pending_points.clear()
            else:
                # 正常的低点更新
                if (not structure.get('lower_low') or
                        new_point['price'] < structure['lower_low']['price']):
                    structure['lower_low'] = new_point

        elif new_point['type'] == 'high':
            if last_type == 'high' or any(p['type'] == 'high' for p in pending_points):
                # 连续高点，选择最低的（lower high）
                all_highs = [new_point] + [p for p in pending_points if p['type'] == 'high']
                if structure.get('lower_high'):
                    all_highs.append({
                        'price': structure['lower_high']['price'],
                        'index': structure['lower_high']['index'],
                        'timestamp': structure['lower_high']['timestamp'],
                        'type': 'high'
                    })

                lowest_high = min(all_highs, key=lambda x: x['price'])
                structure['lower_high'] = lowest_high
                pending_points.clear()
            else:
                # 正常的高点更新
                if (not structure.get('lower_high') or
                        new_point['price'] < structure['lower_high']['price']):
                    structure['lower_high'] = new_point


def read_config(filepath="config.txt"):
    okx_config = {}
    with open(filepath, 'r') as file:
        for line in file:
            if '=' in line:
                key, value = line.strip().split('=', 1)
                config[key.strip()] = value.strip()
    return okx_config



if __name__ == "__main__":
    config = read_config()
    API_KEY = config.get("api_key")
    SECRET_KEY = config.get("secret_key")
    PASSPHRASE = config.get("passphrase")

    strategy = OKXTradingStrategy(
        api_key=API_KEY,
        secret_key=SECRET_KEY,
        passphrase=PASSPHRASE,
        sandbox=True,
        symbol="BTC-USDT-SWAP"
    )

    # 运行策略
    try:
        strategy.run_strategy()
    except KeyboardInterrupt:
        logger.info("策略停止")
        strategy.cancel_orders()
    except Exception as e:
        logger.error(f"策略异常退出: {e}")
        strategy.cancel_orders()