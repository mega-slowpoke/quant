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