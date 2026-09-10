from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


@dataclass(frozen=True)
class MT5Config:
    path: str | None
    login: int | None
    password: str | None
    server: str | None
    symbol_suffix: str
    volume_per_position: float

    @classmethod
    def from_environment(cls) -> MT5Config:
        login_value = os.getenv("MT5_LOGIN", "").strip()
        return cls(
            path=os.getenv("MT5_PATH", "").strip() or None,
            login=int(login_value) if login_value else None,
            password=os.getenv("MT5_PASSWORD", "").strip() or None,
            server=os.getenv("MT5_SERVER", "").strip() or None,
            symbol_suffix=os.getenv("MT5_SYMBOL_SUFFIX", "").strip(),
            volume_per_position=float(os.getenv("MT5_VOLUME_PER_POSITION", "0.01")),
        )

    @property
    def configured(self) -> bool:
        return self.login is not None and bool(self.password) and bool(self.server)


class MT5Adapter:
    def __init__(self, config: MT5Config | None = None):
        self.config = config or MT5Config.from_environment()

    def _require_package(self) -> None:
        if mt5 is None:
            raise RuntimeError("The MetaTrader5 Python package is not installed")

    def connect(self) -> None:
        self._require_package()
        initialized = mt5.initialize(path=self.config.path) if self.config.path else mt5.initialize()
        if not initialized:
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        if self.config.configured and not mt5.login(self.config.login, password=self.config.password, server=self.config.server):
            error = mt5.last_error()
            mt5.shutdown()
            raise RuntimeError(f"MT5 login failed: {error}")

    def disconnect(self) -> None:
        if mt5 is not None:
            mt5.shutdown()

    def _resolve_symbol(self, instrument: str) -> str:
        symbol = f"{instrument}{self.config.symbol_suffix}"
        if mt5.symbol_info(symbol) is not None:
            return symbol
        matches = mt5.symbols_get(group=f"{instrument}*") or []
        if matches:
            return next((item.name for item in matches if item.visible), matches[0].name)
        return symbol

    def status(self) -> dict[str, Any]:
        if mt5 is None:
            return {"package_installed": False, "configured": self.config.configured, "connected": False}
        try:
            self.connect()
            info = mt5.account_info()
            return {
                "package_installed": True,
                "configured": self.config.configured,
                "connected": info is not None,
                "account": self._account_payload(info) if info is not None else None,
            }
        except RuntimeError as error:
            return {"package_installed": True, "configured": self.config.configured, "connected": False, "error": str(error)}
        finally:
            self.disconnect()

    def positions(self) -> list[dict[str, Any]]:
        self.connect()
        try:
            open_positions = mt5.positions_get() or []
            return [
                {
                    "ticket": position.ticket,
                    "symbol": position.symbol,
                    "direction": "BUY" if position.type == mt5.POSITION_TYPE_BUY else "SELL",
                    "volume": position.volume,
                    "price_open": position.price_open,
                    "price_current": position.price_current,
                    "profit": position.profit,
                    "stop_loss": position.sl,
                    "take_profit": position.tp,
                    "opened_at": position.time,
                }
                for position in open_positions
            ]
        finally:
            self.disconnect()

    def market_snapshot(self, instrument: str, timeframe: str = "M5") -> dict[str, Any]:
        self.connect()
        try:
            symbol = self._resolve_symbol(instrument)
            symbol_info = mt5.symbol_info(symbol)
            tick = mt5.symbol_info_tick(symbol)
            if symbol_info is None or tick is None:
                raise RuntimeError(f"MT5 symbol is unavailable: {symbol}")
            if not symbol_info.visible and not mt5.symbol_select(symbol, True):
                raise RuntimeError(f"MT5 could not select symbol: {symbol}")
            timeframe_value = {
                "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15,
                "H1": mt5.TIMEFRAME_H1,
                "H4": mt5.TIMEFRAME_H4,
                "D1": mt5.TIMEFRAME_D1,
            }.get(timeframe.upper())
            if timeframe_value is None:
                raise RuntimeError(f"Unsupported MT5 timeframe: {timeframe}")
            rates = mt5.copy_rates_from_pos(symbol, timeframe_value, 0, 32)
            closes = [float(rate["close"]) for rate in rates] if rates is not None else []
            average = sum(closes[:-1]) / len(closes[:-1]) if len(closes) > 1 else float(tick.bid)
            direction = "BUY" if float(tick.bid) >= average else "SELL"
            candle_signal = self._candle_signal(rates)
            point = symbol_info.point
            pip_size = point * 10 if symbol_info.digits in (3, 5) else point
            spread_pips = (tick.ask - tick.bid) / pip_size if pip_size else 0
            return {"instrument": instrument, "symbol": symbol, "price": float(tick.ask if direction == "BUY" else tick.bid), "bid": float(tick.bid), "ask": float(tick.ask), "spread_pips": round(spread_pips, 2), "provider": "exness-mt5", "direction": direction, "trend_average": average, "timeframe": timeframe.upper(), "candle_signal": candle_signal}
        finally:
            self.disconnect()

    def open_market_orders(self, instrument: str, direction: str, positions: int, take_profit_pips: int, stop_loss_pips: int) -> list[dict[str, Any]]:
        self.connect()
        if mt5.account_info() is None:
            self.disconnect()
            raise RuntimeError("MT5 is not logged into an active trading account")
        symbol = self._resolve_symbol(instrument)
        symbol_info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if symbol_info is None or tick is None:
            raise RuntimeError(f"MT5 symbol is unavailable: {symbol}")
        if not symbol_info.visible and not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"MT5 could not select symbol: {symbol}")

        is_buy = direction == "BUY"
        price = tick.ask if is_buy else tick.bid
        point = symbol_info.point
        pip_size = point * 10 if symbol_info.digits in (3, 5) else point
        take_profit = price + take_profit_pips * pip_size if is_buy else price - take_profit_pips * pip_size
        stop_loss = price - stop_loss_pips * pip_size if is_buy else price + stop_loss_pips * pip_size
        order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
        results = []

        try:
            for _ in range(positions):
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": self.config.volume_per_position,
                    "type": order_type,
                    "price": price,
                    "sl": round(stop_loss, symbol_info.digits),
                    "tp": round(take_profit, symbol_info.digits),
                    "deviation": 20,
                    "magic": 250250,
                    "comment": "250 Pips MT5",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                check = mt5.order_check(request)
                if check is None or check.retcode != 0:
                    raise RuntimeError(f"MT5 order check failed: {check}")
                result = mt5.order_send(request)
                if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                    raise RuntimeError(f"MT5 order failed: {result}")
                results.append({"order": result.order, "deal": result.deal, "volume": result.volume, "price": result.price})
        finally:
            self.disconnect()
        return results

    @staticmethod
    def _candle_signal(rates: Any) -> dict[str, Any]:
        if rates is None or len(rates) < 8:
            return {"qualified": False, "reason": "Not enough closed M5 candles"}
        closed = rates[-2]
        recent = rates[-9:-2]
        body = abs(float(closed["close"]) - float(closed["open"]))
        candle_range = float(closed["high"]) - float(closed["low"])
        average_body = sum(abs(float(item["close"]) - float(item["open"])) for item in recent) / len(recent)
        direction = "BUY" if float(closed["close"]) > float(closed["open"]) else "SELL" if float(closed["close"]) < float(closed["open"]) else "FLAT"
        body_ratio = body / candle_range if candle_range else 0
        impulse_ratio = body / average_body if average_body else 0
        qualified = direction != "FLAT" and body_ratio >= 0.6 and impulse_ratio >= 1.5
        return {"qualified": qualified, "direction": direction, "body": body, "range": candle_range, "body_ratio": round(body_ratio, 3), "impulse_ratio": round(impulse_ratio, 2), "reason": "Closed M5 impulse candle confirmed" if qualified else "Waiting for a long M5 impulse candle"}

    @staticmethod
    def _account_payload(info: Any) -> dict[str, Any]:
        return {"login": info.login, "server": info.server, "currency": info.currency, "balance": info.balance, "equity": info.equity, "margin_free": info.margin_free}
