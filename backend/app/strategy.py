from __future__ import annotations

from typing import Any


def _ema(values: list[float], period: int) -> float:
    weight = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = value * weight + result * (1 - weight)
    return result


def _rsi(closes: list[float], period: int = 14) -> float:
    changes = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    gains = [max(change, 0) for change in changes[-period:]]
    losses = [max(-change, 0) for change in changes[-period:]]
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    return 100.0 if average_loss == 0 else 100 - (100 / (1 + average_gain / average_loss))


def _atr(closed: list[dict[str, Any]], period: int = 14) -> float:
    ranges = [float(item["high"]) - float(item["low"]) for item in closed]
    return sum(ranges[-period:]) / period


def _candle_pattern(closed: list[dict[str, Any]]) -> dict[str, Any]:
    current = closed[-1]
    previous = closed[-2]
    mother = closed[-3]
    open_price = float(current["open"])
    close = float(current["close"])
    high = float(current["high"])
    low = float(current["low"])
    previous_open = float(previous["open"])
    previous_close = float(previous["close"])
    body = abs(close - open_price)
    candle_range = max(high - low, 0.00000001)
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low
    bullish = close > open_price
    bearish = close < open_price
    bullish_pin = lower_wick >= body * 2 and close >= low + candle_range * 0.65
    bearish_pin = upper_wick >= body * 2 and close <= high - candle_range * 0.65
    bullish_engulfing = bullish and previous_close < previous_open and close >= previous_open and open_price <= previous_close
    bearish_engulfing = bearish and previous_close > previous_open and close <= previous_open and open_price >= previous_close
    inside_breakout_up = float(previous["high"]) < float(mother["high"]) and float(previous["low"]) > float(mother["low"]) and close > float(mother["high"])
    inside_breakout_down = float(previous["high"]) < float(mother["high"]) and float(previous["low"]) > float(mother["low"]) and close < float(mother["low"])
    direction = "BUY" if bullish_pin or bullish_engulfing or inside_breakout_up else "SELL" if bearish_pin or bearish_engulfing or inside_breakout_down else "FLAT"
    name = "BULLISH_PIN" if bullish_pin else "BEARISH_PIN" if bearish_pin else "BULLISH_ENGULFING" if bullish_engulfing else "BEARISH_ENGULFING" if bearish_engulfing else "INSIDE_BAR_BREAKOUT_BUY" if inside_breakout_up else "INSIDE_BAR_BREAKOUT_SELL" if inside_breakout_down else "NONE"
    return {"name": name, "direction": direction, "qualified": direction != "FLAT", "open": open_price, "close": close, "high": high, "low": low, "range": candle_range, "body_ratio": round(body / candle_range, 3)}


def _zones(closed: list[dict[str, Any]], price: float, atr: float) -> dict[str, Any]:
    tolerance = max(atr * 0.35, price * 0.0005)
    pivots: list[tuple[float, str]] = []
    for index in range(2, len(closed) - 2):
        high = float(closed[index]["high"])
        low = float(closed[index]["low"])
        nearby_highs = [float(closed[offset]["high"]) for offset in range(index - 2, index + 3)]
        nearby_lows = [float(closed[offset]["low"]) for offset in range(index - 2, index + 3)]
        if high == max(nearby_highs):
            pivots.append((high, "resistance"))
        if low == min(nearby_lows):
            pivots.append((low, "support"))
    clusters: list[dict[str, Any]] = []
    for level, kind in sorted(pivots, key=lambda item: item[0]):
        cluster = next((item for item in clusters if item["kind"] == kind and abs(item["level"] - level) <= tolerance), None)
        if cluster is None:
            clusters.append({"kind": kind, "level": level, "touches": 1})
        else:
            cluster["level"] = (cluster["level"] * cluster["touches"] + level) / (cluster["touches"] + 1)
            cluster["touches"] += 1
    supports = [item for item in clusters if item["kind"] == "support" and item["level"] < price]
    resistances = [item for item in clusters if item["kind"] == "resistance" and item["level"] > price]
    support = max(supports, key=lambda item: item["level"], default=None)
    resistance = min(resistances, key=lambda item: item["level"], default=None)
    return {"support": support, "resistance": resistance, "tolerance": tolerance}


def analyze_rates(rates: Any, current_price: float, pip_size: float) -> dict[str, Any]:
    if rates is None or len(rates) < 205:
        return {"ready": False, "reason": "At least 205 candles are required for the 50/200 EMA model"}
    closed = [{key: float(item[key]) for key in ("open", "high", "low", "close", "tick_volume")} for item in rates[:-1]]
    closes = [item["close"] for item in closed]
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    atr = _atr(closed)
    pattern = _candle_pattern(closed)
    zones = _zones(closed[-120:], current_price, atr)
    average_volume = sum(item["tick_volume"] for item in closed[-21:-1]) / 20
    volume_ratio = closed[-1]["tick_volume"] / average_volume if average_volume else 0
    previous_close = closed[-2]["close"]
    support = zones["support"]["level"] if zones["support"] else None
    resistance = zones["resistance"]["level"] if zones["resistance"] else None
    bullish_breakout = resistance is not None and previous_close <= resistance < closed[-1]["close"] and volume_ratio >= 1.2
    bearish_breakout = support is not None and previous_close >= support > closed[-1]["close"] and volume_ratio >= 1.2
    trend = "BUY" if ema50 > ema200 and current_price >= ema50 else "SELL" if ema50 < ema200 and current_price <= ema50 else "RANGE"
    momentum = _rsi(closes)
    high_volatility = atr > sum(float(item["high"]) - float(item["low"]) for item in closed[-42:-14]) / 28 * 2 if len(closed) >= 42 else False
    near_support = support is not None and abs(current_price - support) <= max(atr * 0.75, pip_size * 10)
    near_resistance = resistance is not None and abs(current_price - resistance) <= max(atr * 0.75, pip_size * 10)
    level_confirmed = bullish_breakout or bearish_breakout or (trend == "BUY" and near_support) or (trend == "SELL" and near_resistance)
    direction = "BUY" if bullish_breakout or trend == "BUY" and pattern["direction"] == "BUY" else "SELL" if bearish_breakout or trend == "SELL" and pattern["direction"] == "SELL" else trend
    signal_confirmed = level_confirmed and pattern["qualified"] and pattern["direction"] == direction
    if high_volatility and not (bullish_breakout or bearish_breakout):
        signal_confirmed = False
    stop_reference = support if direction == "BUY" else resistance
    if direction == "BUY":
        stop_price = min(pattern["low"], stop_reference or pattern["low"]) - atr * 0.15
    else:
        stop_price = max(pattern["high"], stop_reference or pattern["high"]) + atr * 0.15
    return {"ready": True, "direction": direction, "trend": trend, "ema50": ema50, "ema200": ema200, "rsi": round(momentum, 2), "atr": atr, "pattern": pattern, "zones": zones, "volume_ratio": round(volume_ratio, 2), "bullish_breakout": bullish_breakout, "bearish_breakout": bearish_breakout, "high_volatility": high_volatility, "near_support": near_support, "near_resistance": near_resistance, "level_confirmed": level_confirmed, "signal_confirmed": signal_confirmed, "stop_price": stop_price}
