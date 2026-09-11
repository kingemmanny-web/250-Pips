from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import Any

from backend.app.strategy import analyze_rates

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
    account_id: str = "primary"

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
            account_id="primary",
        )

    @classmethod
    def profiles_from_environment(cls) -> list[MT5Config]:
        raw = os.getenv("MT5_ACCOUNTS", "").strip()
        if not raw:
            return [cls.from_environment()]
        try:
            profiles = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"MT5_ACCOUNTS must be valid JSON: {error}") from error
        if not isinstance(profiles, list) or not profiles:
            raise RuntimeError("MT5_ACCOUNTS must contain at least one account profile")
        result = []
        for index, profile in enumerate(profiles, start=1):
            if not isinstance(profile, dict):
                raise RuntimeError(f"MT5 account profile {index} must be an object")
            login_value = str(profile.get("login", "")).strip()
            result.append(cls(
                path=str(profile.get("path", "")).strip() or None,
                login=int(login_value) if login_value else None,
                password=str(profile.get("password", "")).strip() or None,
                server=str(profile.get("server", "")).strip() or None,
                symbol_suffix=str(profile.get("symbol_suffix", "")).strip(),
                volume_per_position=float(profile.get("volume_per_position", os.getenv("MT5_VOLUME_PER_POSITION", "0.01"))),
                account_id=str(profile.get("id", f"account-{index}")),
            ))
        return result

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
                "account_id": self.config.account_id,
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

    def pending_orders(self) -> list[dict[str, Any]]:
        self.connect()
        try:
            orders = mt5.orders_get() or []
            pending_types = {mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_SELL_STOP}
            return [{"ticket": order.ticket, "symbol": order.symbol, "type": order.type, "price_open": order.price_open} for order in orders if order.type in pending_types and order.magic == 250250]
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
            rates = mt5.copy_rates_from_pos(symbol, timeframe_value, 0, 260)
            closes = [float(rate["close"]) for rate in rates] if rates is not None else []
            average = sum(closes[:-1]) / len(closes[:-1]) if len(closes) > 1 else float(tick.bid)
            point = symbol_info.point
            pip_size = point * 10 if symbol_info.digits in (3, 5) else point
            strategy = analyze_rates(rates, float(tick.bid), pip_size)
            direction = strategy.get("direction", "BUY")
            candle_signal = strategy.get("pattern", {})
            spread_pips = (tick.ask - tick.bid) / pip_size if pip_size else 0
            return {"instrument": instrument, "symbol": symbol, "price": float(tick.ask if direction == "BUY" else tick.bid), "bid": float(tick.bid), "ask": float(tick.ask), "spread_pips": round(spread_pips, 2), "provider": "exness-mt5", "direction": direction, "trend_average": average, "pip_size": pip_size, "digits": symbol_info.digits, "volume_min": symbol_info.volume_min, "volume_max": symbol_info.volume_max, "volume_step": symbol_info.volume_step, "trade_tick_value": symbol_info.trade_tick_value, "trade_tick_size": symbol_info.trade_tick_size, "stops_level_points": symbol_info.trade_stops_level, "timeframe": timeframe.upper(), "candle_signal": candle_signal, "strategy": strategy}
        finally:
            self.disconnect()

    def _risk_volume(self, symbol: str, direction: str, entry_price: float, stop_loss: float, risk_percent: float, positions: int, symbol_info: Any) -> float:
        account = mt5.account_info()
        if account is None or risk_percent <= 0:
            raise RuntimeError("MT5 account equity is required for risk-based volume sizing")
        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        loss_per_lot = abs(float(mt5.order_calc_profit(order_type, symbol, 1.0, entry_price, stop_loss) or 0))
        if loss_per_lot <= 0:
            raise RuntimeError("MT5 could not calculate the stop-loss value for risk sizing")
        risk_money_per_position = float(account.equity) * (risk_percent / 100) / positions
        raw_volume = risk_money_per_position / loss_per_lot
        step = symbol_info.volume_step or 0.01
        volume = (raw_volume // step) * step
        if volume < symbol_info.volume_min:
            raise RuntimeError(f"Minimum volume {symbol_info.volume_min} would exceed the configured {risk_percent}% account risk")
        return round(min(volume, symbol_info.volume_max), 2)

    def open_market_orders(self, instrument: str, direction: str, positions: int, take_profit_pips: int, stop_loss_pips: int, risk_percent: float = 1.0, stop_loss_price: float | None = None, take_profit_price: float | None = None) -> list[dict[str, Any]]:
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
        take_profit = take_profit_price or (price + take_profit_pips * pip_size if is_buy else price - take_profit_pips * pip_size)
        stop_loss = stop_loss_price or (price - stop_loss_pips * pip_size if is_buy else price + stop_loss_pips * pip_size)
        volume = self._risk_volume(symbol, direction, price, stop_loss, risk_percent, positions, symbol_info)
        order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
        results = []

        try:
            for _ in range(positions):
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": volume,
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

    def open_limit_orders(self, instrument: str, direction: str, positions: int, entry_price: float, take_profit_pips: int, stop_loss_pips: int, risk_percent: float = 1.0, stop_loss_price: float | None = None, take_profit_price: float | None = None) -> list[dict[str, Any]]:
        self.connect()
        if mt5.account_info() is None:
            self.disconnect()
            raise RuntimeError("MT5 is not logged into an active trading account")
        symbol = self._resolve_symbol(instrument)
        symbol_info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if symbol_info is None or tick is None:
            raise RuntimeError(f"MT5 symbol is unavailable: {symbol}")
        point = symbol_info.point
        pip_size = point * 10 if symbol_info.digits in (3, 5) else point
        is_buy = direction == "BUY"
        if is_buy and entry_price >= tick.ask:
            raise RuntimeError("Buy limit entry must be below the current ask")
        if not is_buy and entry_price <= tick.bid:
            raise RuntimeError("Sell limit entry must be above the current bid")
        take_profit = take_profit_price or (entry_price + take_profit_pips * pip_size if is_buy else entry_price - take_profit_pips * pip_size)
        stop_loss = stop_loss_price or (entry_price - stop_loss_pips * pip_size if is_buy else entry_price + stop_loss_pips * pip_size)
        volume = self._risk_volume(symbol, direction, entry_price, stop_loss, risk_percent, positions, symbol_info)
        order_type = mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT
        results = []
        try:
            for _ in range(positions):
                request = {
                    "action": mt5.TRADE_ACTION_PENDING,
                    "symbol": symbol,
                    "volume": volume,
                    "type": order_type,
                    "price": round(entry_price, symbol_info.digits),
                    "sl": round(stop_loss, symbol_info.digits),
                    "tp": round(take_profit, symbol_info.digits),
                    "deviation": 20,
                    "magic": 250250,
                    "comment": "250 Pips pullback limit",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_RETURN,
                }
                check = mt5.order_check(request)
                if check is None or check.retcode != 0:
                    raise RuntimeError(f"MT5 limit order check failed: {check}")
                result = mt5.order_send(request)
                if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                    raise RuntimeError(f"MT5 limit order failed: {result}")
                results.append({"order": result.order, "price": result.price, "entry_type": "LIMIT"})
        finally:
            self.disconnect()
        return results

    @staticmethod
    def _account_payload(info: Any) -> dict[str, Any]:
        return {"login": info.login, "server": info.server, "currency": info.currency, "balance": info.balance, "equity": info.equity, "margin_free": info.margin_free}
