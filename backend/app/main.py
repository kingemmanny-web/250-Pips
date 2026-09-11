from __future__ import annotations

import os
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.app.bot_controller import BotController
from backend.app.mt5_adapter import MT5Adapter
from backend.app.news_calendar import EconomicCalendar

ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(ROOT / "backend" / "data" / "trading.sqlite3")))
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
MAX_POSITIONS_PER_CYCLE = 4
DEFAULT_TP_PIPS = 250
DEFAULT_SL_PIPS = int(os.getenv("DEFAULT_STOP_LOSS_PIPS", "100"))
RISK_PERCENT = min(2.0, max(1.0, float(os.getenv("RISK_PERCENT", "1"))))
RISK_REWARD_RATIO = float(os.getenv("RISK_REWARD_RATIO", "2"))
MAX_SPREAD_PIPS = float(os.getenv("MAX_SPREAD_PIPS", "1.5"))
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
LIVE_TRADING_CONFIRMATION = os.getenv("LIVE_TRADING_CONFIRMATION", "") == "I_UNDERSTAND_REAL_MONEY"
BOT_INTERVAL_SECONDS = int(os.getenv("BOT_INTERVAL_SECONDS", "60"))
BOT_AUTOSTART = os.getenv("BOT_AUTOSTART", "true").lower() == "true"
SCAN_INSTRUMENTS = ("EURUSD", "GBPUSD", "XAUUSD", "BTCUSD")
FRONTEND_ORIGINS = [origin.strip() for origin in os.getenv("FRONTEND_ORIGINS", "").split(",") if origin.strip()]
DEFAULT_FRONTEND_ORIGINS = ["https://250pips.vercel.app", "http://127.0.0.1:4173", "http://127.0.0.1:4174", "http://127.0.0.1:5173", "http://127.0.0.1:5174", "http://localhost:4173", "http://localhost:4174", "http://localhost:5173", "http://localhost:5174"]

app = FastAPI(title="250 Pips Trading API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=DEFAULT_FRONTEND_ORIGINS + FRONTEND_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class CycleRequest(BaseModel):
    instrument: Literal["EURUSD", "GBPUSD", "XAUUSD", "BTCUSD"]
    direction: Literal["BUY", "SELL"]
    positions: int = Field(default=4, ge=1, le=4)
    take_profit_pips: int = Field(default=DEFAULT_TP_PIPS, ge=1, le=10000)
    stop_loss_pips: int = Field(default=DEFAULT_SL_PIPS, ge=1, le=10000)
    score: int = Field(default=84, ge=0, le=100)


class BrokerLinkRequest(BaseModel):
    broker: str = Field(min_length=2, max_length=80)
    account_id: str = Field(min_length=3, max_length=80)
    server: str = Field(min_length=2, max_length=120)


class CloseCycleRequest(BaseModel):
    exit_reason: Literal["TARGET_REACHED", "STOP_LOSS", "MANUAL"] = "MANUAL"
    profit_loss: float = 0


class MarketConfig:
    prices = {"EURUSD": 1.1710, "GBPUSD": 1.3532, "XAUUSD": 3342.60, "BTCUSD": 108420.00}
    pip_sizes = {"EURUSD": 0.0001, "GBPUSD": 0.0001, "XAUUSD": 0.01, "BTCUSD": 1.0}

    def snapshot(self, instrument: str) -> dict:
        raise RuntimeError(f"MT5 market data is required for {instrument}")

market_data = MarketConfig()
mt5_broker = MT5Adapter()
economic_calendar = EconomicCalendar()
try:
    CENTRAL_BANK_RATES = {key.upper(): float(value) for key, value in json.loads(os.getenv("CENTRAL_BANK_RATES", "{} ")).items()}
except (TypeError, ValueError, json.JSONDecodeError):
    CENTRAL_BANK_RATES = {}
scan_lock = threading.Lock()
scan_index = 0


def instrument_has_open_position(instrument: str, positions: list[dict] | None = None) -> bool:
    open_positions = positions if positions is not None else mt5_broker.positions()
    normalized = instrument.upper()
    if any(position["symbol"].upper().startswith(normalized) for position in open_positions):
        return True
    pending_orders = mt5_broker.pending_orders()
    return any(order["symbol"].upper().startswith(normalized) for order in pending_orders)


def analyze_market() -> dict:
    global scan_index
    positions = mt5_broker.positions()
    running_instruments = {
        instrument for instrument in SCAN_INSTRUMENTS
        if instrument_has_open_position(instrument, positions)
    }
    with scan_lock:
        available = [instrument for instrument in SCAN_INSTRUMENTS if instrument not in running_instruments]
        if not available:
            return {"decision": "WAIT", "confirmation": "All markets have open positions", "reason": "No market will be analysed until an existing trade reaches TP or SL.", "running_instruments": sorted(running_instruments), "analyzed_at": datetime.now(UTC).isoformat()}
        instrument = next((candidate for candidate in SCAN_INSTRUMENTS[scan_index:] + SCAN_INSTRUMENTS[:scan_index] if candidate in available), available[0])
        scan_index = (SCAN_INSTRUMENTS.index(instrument) + 1) % len(SCAN_INSTRUMENTS)
    analysis = analyze_instrument(instrument, for_execution=True)
    analysis["scan_order"] = {"instrument": instrument, "next": next((candidate for candidate in SCAN_INSTRUMENTS[scan_index:] + SCAN_INSTRUMENTS[:scan_index] if candidate not in running_instruments), None), "running_instruments": sorted(running_instruments)}
    return analysis


def manage_open_trade(_: str) -> dict | None:
    return None


def analyze_instrument(instrument: str, for_execution: bool = False) -> dict:
    instrument = instrument.upper()
    if instrument not in market_data.prices:
        raise HTTPException(status_code=404, detail="Instrument is not supported")
    try:
        snapshot = mt5_broker.market_snapshot(instrument, "M5")
        higher_timeframes = {}
        for timeframe in ("M15", "H1", "H4", "D1"):
            higher_timeframes[timeframe] = mt5_broker.market_snapshot(instrument, timeframe)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=f"MT5 market data unavailable: {error}") from error
    strategy = snapshot.get("strategy", {})
    direction = strategy.get("direction", snapshot.get("direction", "BUY"))
    pip_size = float(snapshot.get("pip_size", market_data.pip_sizes[instrument]))
    price = snapshot["price"]
    take_profit_pips = DEFAULT_TP_PIPS
    candle_signal = strategy.get("pattern", {})
    stop_loss_price = float(strategy.get("stop_price", price))
    take_profit_price = price + take_profit_pips * pip_size if direction == "BUY" else price - take_profit_pips * pip_size
    risk_distance = abs(price - stop_loss_price)
    risk_reward = (take_profit_pips * pip_size / risk_distance) if risk_distance else 0
    news = economic_calendar.blocked(instrument)
    score = 0
    if strategy.get("trend") == direction:
        score += 20
    if strategy.get("signal_confirmed"):
        score += 25
    if strategy.get("level_confirmed"):
        score += 20
    if strategy.get("volume_ratio", 0) >= 1.2:
        score += 10
    rsi = float(strategy.get("rsi", 50))
    momentum_allowed = 45 <= rsi <= 70 if direction == "BUY" else 30 <= rsi <= 55
    if momentum_allowed:
        score += 10
    direction_aligned = candle_signal.get("direction") == direction
    spread_allowed = snapshot["spread_pips"] <= MAX_SPREAD_PIPS
    aligned_timeframes = [timeframe for timeframe, higher_snapshot in higher_timeframes.items() if higher_snapshot.get("strategy", {}).get("trend") == direction]
    trend_confluence = len(aligned_timeframes) >= 3 and all(higher_timeframes[timeframe].get("strategy", {}).get("ready", False) for timeframe in ("H1", "H4"))
    bias_confirmed = trend_confluence and direction in ("BUY", "SELL")
    if spread_allowed:
        score += 5
    policy_differential = None
    if len(instrument) >= 6 and instrument[:3] in CENTRAL_BANK_RATES and instrument[3:6] in CENTRAL_BANK_RATES:
        policy_differential = CENTRAL_BANK_RATES[instrument[:3]] - CENTRAL_BANK_RATES[instrument[3:6]]
    policy_aligned = policy_differential is None or (policy_differential > 0 if direction == "BUY" else policy_differential < 0)
    if policy_aligned and policy_differential is not None:
        score += 5
    minimum_score = int(os.getenv("BOT_MIN_SCORE", "84"))
    can_trade = score >= minimum_score and direction_aligned and spread_allowed and trend_confluence and momentum_allowed and strategy.get("level_confirmed", False) and not strategy.get("high_volatility", False) and news["blocked"] is False and policy_aligned and risk_reward >= RISK_REWARD_RATIO
    entry_price = price
    entry_type = "MARKET"
    pattern = strategy.get("pattern", {})
    if can_trade and pattern.get("range"):
        entry_price = pattern["close"] - pattern["range"] * 0.5 if direction == "BUY" else pattern["close"] + pattern["range"] * 0.5
        entry_price = round(entry_price, int(snapshot.get("digits", 5)))
        if (direction == "BUY" and entry_price < snapshot["ask"] and entry_price > stop_loss_price) or (direction == "SELL" and entry_price > snapshot["bid"] and entry_price < stop_loss_price):
            entry_type = "LIMIT_50_PERCENT"
        else:
            entry_price = price
    entry_risk_distance = abs(entry_price - stop_loss_price)
    take_profit_price = entry_price + take_profit_pips * pip_size if direction == "BUY" else entry_price - take_profit_pips * pip_size
    risk_reward = (take_profit_pips * pip_size / entry_risk_distance) if entry_risk_distance else 0
    if can_trade and risk_reward < RISK_REWARD_RATIO:
        can_trade = False
    stop_loss_pips = round(entry_risk_distance / pip_size, 1) if pip_size else 0
    reason = f"50/200 EMA trend, level, {candle_signal.get('name', 'pattern')}, volume, and {len(aligned_timeframes)}/4 timeframe confluence passed"
    if news["blocked"]:
        reason = news["reason"]
    elif not strategy.get("ready", False):
        reason = strategy.get("reason", "Waiting for 205 candles for EMA200")
    elif strategy.get("high_volatility") and not (strategy.get("bullish_breakout") or strategy.get("bearish_breakout")):
        reason = "High-volatility move is not a confirmed level breakout"
    elif not strategy.get("level_confirmed"):
        reason = "Waiting for price action at support/resistance or a confirmed close beyond the level"
    elif not direction_aligned:
        reason = "Candlestick direction does not confirm the 50/200 EMA trend"
    elif not trend_confluence:
        reason = f"Higher-timeframe EMA trend confirmation is incomplete ({len(aligned_timeframes)}/4 aligned)"
    elif not momentum_allowed:
        reason = f"Momentum filter rejects trading against strong RSI momentum ({rsi:.1f})"
    elif risk_reward < RISK_REWARD_RATIO:
        reason = f"Risk/reward is {risk_reward:.2f}:1, below configured {RISK_REWARD_RATIO:.2f}:1 minimum"
    return {"instrument": instrument, "direction": direction, "score": min(100, score), "decision": "TRADE" if can_trade else "WAIT" if for_execution else "Signal confirmed" if score >= 70 else "Waiting for confluence", "entry_zone": f"{entry_price - pip_size * 6:.{5 if pip_size < 0.01 else 2}f} - {entry_price + pip_size * 6:.{5 if pip_size < 0.01 else 2}f}", "entry_price": round(entry_price, int(snapshot.get("digits", 5))), "entry_type": entry_type, "stop_loss": round(stop_loss_price, int(snapshot.get("digits", 5))), "take_profit": round(take_profit_price, int(snapshot.get("digits", 5))), "take_profit_pips": take_profit_pips, "stop_loss_pips": stop_loss_pips, "risk_percent": RISK_PERCENT, "risk_reward": round(risk_reward, 2), "risk_reward_required": RISK_REWARD_RATIO, "pip_size": pip_size, "bias_confirmed": bias_confirmed, "entry_confirmed": can_trade, "confirmation": "Entry confirmed" if can_trade else "Bias confirmed" if bias_confirmed else "Waiting", "reason": reason, "news": news, "policy_differential": policy_differential, "market": snapshot, "timeframes": {"M5": {"direction": direction, "trend": strategy.get("trend"), "pattern": candle_signal.get("name")}, **{timeframe: {"direction": value.get("direction"), "trend": value.get("strategy", {}).get("trend"), "ema50": value.get("strategy", {}).get("ema50"), "ema200": value.get("strategy", {}).get("ema200")} for timeframe, value in higher_timeframes.items()}}, "timeframe_confluence": {"aligned": aligned_timeframes, "aligned_count": len(aligned_timeframes), "required": 3}, "analyzed_at": datetime.now(UTC).isoformat()}


def execute_bot_trade(analysis: dict) -> dict:
    request = CycleRequest(instrument=analysis["instrument"], direction=analysis["direction"], score=analysis["score"], positions=min(MAX_POSITIONS_PER_CYCLE, int(os.getenv("BOT_POSITIONS", "4"))), take_profit_pips=analysis["take_profit_pips"], stop_loss_pips=analysis["stop_loss_pips"])
    if not LIVE_TRADING_ENABLED or not LIVE_TRADING_CONFIRMATION:
        raise RuntimeError("Live execution is disabled by the safety gate")
    positions = mt5_broker.positions()
    if instrument_has_open_position(request.instrument, positions):
        raise RuntimeError(f"{request.instrument} already has an open MT5 position")
    if analysis.get("entry_type") == "LIMIT_50_PERCENT":
        orders = mt5_broker.open_limit_orders(request.instrument, request.direction, request.positions, analysis["entry_price"], request.take_profit_pips, request.stop_loss_pips, analysis["risk_percent"], analysis["stop_loss"], analysis["take_profit"])
    else:
        orders = mt5_broker.open_market_orders(request.instrument, request.direction, request.positions, request.take_profit_pips, request.stop_loss_pips, analysis["risk_percent"], analysis["stop_loss"], analysis["take_profit"])
    return {"mode": "live", "status": "OPEN", "entry_type": analysis.get("entry_type", "MARKET"), "target_pips": DEFAULT_TP_PIPS, "risk_percent": analysis["risk_percent"], "risk_reward": analysis["risk_reward"], "orders": orders, "opened_at": datetime.now(UTC).isoformat()}


def bot_analyze() -> dict:
    return analyze_market()


def bot_manage(mode: str) -> dict | None:
    return manage_open_trade(mode)


bot = BotController(BOT_INTERVAL_SECONDS, analyze_market, execute_bot_trade, bot_manage)


def initialize_database() -> None:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS cycles (
            cycle_id TEXT PRIMARY KEY, instrument TEXT NOT NULL, direction TEXT NOT NULL,
            entry REAL NOT NULL, take_profit REAL NOT NULL, stop_loss REAL NOT NULL,
            positions INTEGER NOT NULL, score INTEGER NOT NULL, status TEXT NOT NULL, opened_at TEXT NOT NULL, closed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, cycle_id TEXT NOT NULL, position_number INTEGER NOT NULL,
            status TEXT NOT NULL, opened_at TEXT NOT NULL, closed_at TEXT, profit_loss REAL DEFAULT 0,
            FOREIGN KEY(cycle_id) REFERENCES cycles(cycle_id)
        );
        CREATE TABLE IF NOT EXISTS broker_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, broker TEXT NOT NULL, account_id TEXT NOT NULL,
            server TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'live', created_at TEXT NOT NULL
        );
    """)
    connection.commit()
    connection.close()


@app.on_event("startup")
def startup() -> None:
    initialize_database()
    if BOT_AUTOSTART and LIVE_TRADING_ENABLED and LIVE_TRADING_CONFIRMATION and mt5_broker.status().get("connected"):
        bot.start("live")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "mode": "live", "live_execution_enabled": LIVE_TRADING_ENABLED and LIVE_TRADING_CONFIRMATION, "risk_percent": RISK_PERCENT, "risk_reward_ratio": RISK_REWARD_RATIO, "economic_calendar": economic_calendar.status(), "mt5": mt5_broker.status(), "database": str(DATABASE_PATH)}


@app.get("/api/broker/mt5/status")
def mt5_status() -> dict:
    return mt5_broker.status()


@app.get("/api/strategy/config")
def strategy_config() -> dict:
    return {"target_pips": DEFAULT_TP_PIPS, "risk_percent": RISK_PERCENT, "risk_reward_ratio": RISK_REWARD_RATIO, "ema_fast": 50, "ema_slow": 200, "news_blackout_before_minutes": economic_calendar.before_minutes, "news_blackout_after_minutes": economic_calendar.after_minutes, "news_fail_closed": economic_calendar.fail_closed, "central_bank_rates_configured": bool(CENTRAL_BANK_RATES)}


@app.get("/api/analysis/{instrument}")
def instrument_analysis(instrument: str) -> dict:
    if instrument_has_open_position(instrument):
        return {
            "instrument": instrument.upper(),
            "decision": "WAIT",
            "entry_confirmed": False,
            "bias_confirmed": False,
            "confirmation": "Position already open",
            "reason": f"{instrument.upper()} is excluded from analysis until its current MT5 position closes.",
            "analyzed_at": datetime.now(UTC).isoformat(),
        }
    return analyze_instrument(instrument)


@app.get("/api/bot/status")
def bot_status() -> dict:
    return {**bot.snapshot(), "interval_seconds": BOT_INTERVAL_SECONDS, "autostart": BOT_AUTOSTART, "live_execution_enabled": LIVE_TRADING_ENABLED and LIVE_TRADING_CONFIRMATION}


@app.post("/api/bot/start")
def start_bot() -> dict:
    if not LIVE_TRADING_ENABLED or not LIVE_TRADING_CONFIRMATION:
        raise HTTPException(status_code=403, detail="Live bot execution requires LIVE_TRADING_ENABLED=true and LIVE_TRADING_CONFIRMATION=I_UNDERSTAND_REAL_MONEY")
    if not mt5_broker.status().get("connected"):
        raise HTTPException(status_code=503, detail="Live bot execution requires an active MT5 terminal account")
    return bot.start("live")


@app.post("/api/bot/stop")
def stop_bot() -> dict:
    return bot.stop()


@app.get("/api/account")
def account() -> dict:
    connection = sqlite3.connect(DATABASE_PATH)
    row = connection.execute("SELECT broker, account_id, server, mode FROM broker_accounts ORDER BY id DESC LIMIT 1").fetchone()
    connection.close()
    mt5_snapshot = mt5_broker.status()
    live_positions = []
    positions_error = None
    if mt5_snapshot.get("connected"):
        try:
            live_positions = mt5_broker.positions()
        except RuntimeError as error:
            positions_error = str(error)
    live_account = mt5_snapshot.get("account")
    active_link = None
    if live_account is not None:
        active_login = str(live_account["login"])
        active_server = live_account["server"]
        active_link = {
            "broker": row[0] if row is not None else "MetaTrader 5",
            "account_id": f"{active_login[:3]}****{active_login[-2:]}",
            "server": active_server,
            "mode": "live",
            "verified": True,
        }
    return {"mode": "live", "live_account": live_account, "live_positions": live_positions, "positions_error": positions_error, "linked_broker": active_link, "live_execution_enabled": LIVE_TRADING_ENABLED and LIVE_TRADING_CONFIRMATION}


@app.post("/api/broker/link")
def link_broker(request: BrokerLinkRequest) -> dict:
    current = mt5_broker.status()
    account_info = current.get("account")
    if not current.get("connected") or account_info is None:
        raise HTTPException(status_code=503, detail="The linked MT5 terminal is not connected to an account.")
    if str(account_info["login"]) != request.account_id or account_info["server"] != request.server:
        raise HTTPException(status_code=409, detail=f"Connected MT5 account is {account_info['login']} on {account_info['server']}. Link that account instead.")
    now = datetime.now(UTC).isoformat()
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("INSERT INTO broker_accounts (broker, account_id, server, mode, created_at) VALUES (?, ?, ?, 'live', ?)", (request.broker, request.account_id, request.server, now))
    connection.commit()
    connection.close()
    return {"status": "linked_for_live", "broker": request.broker, "account_id": f"{request.account_id[:3]}****{request.account_id[-2:]}", "server": request.server, "live_verified": True}


@app.get("/api/market/{instrument}")
def market(instrument: str) -> dict:
    instrument = instrument.upper()
    if instrument not in market_data.prices:
        raise HTTPException(status_code=404, detail="Instrument is not supported")
    try:
        return mt5_broker.market_snapshot(instrument)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=f"MT5 market data unavailable: {error}") from error


@app.post("/api/cycles")
def create_cycle(request: CycleRequest) -> dict:
    if not LIVE_TRADING_ENABLED or not LIVE_TRADING_CONFIRMATION:
        raise HTTPException(status_code=403, detail="Live execution requires LIVE_TRADING_ENABLED=true and LIVE_TRADING_CONFIRMATION=I_UNDERSTAND_REAL_MONEY")
    try:
        orders = mt5_broker.open_market_orders(request.instrument, request.direction, request.positions, request.take_profit_pips, request.stop_loss_pips)
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"instrument": request.instrument, "direction": request.direction, "positions": len(orders), "orders": orders, "mode": "live", "status": "OPEN"}


@app.get("/api/history")
def history() -> list[dict]:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    rows = connection.execute("SELECT cycle_id, instrument, direction, positions, score, status, opened_at, closed_at FROM cycles ORDER BY opened_at DESC").fetchall()
    connection.close()
    return [dict(row) for row in rows]


@app.post("/api/cycles/{cycle_id}/close")
def close_cycle(cycle_id: str, request: CloseCycleRequest) -> dict:
    closed_at = datetime.now(UTC).isoformat()
    connection = sqlite3.connect(DATABASE_PATH)
    cycle = connection.execute("SELECT cycle_id, positions FROM cycles WHERE cycle_id = ? AND status = 'OPEN'", (cycle_id,)).fetchone()
    if cycle is None:
        connection.close()
        raise HTTPException(status_code=404, detail="Open cycle was not found")
    connection.execute("UPDATE cycles SET status = ?, closed_at = ? WHERE cycle_id = ?", (request.exit_reason, closed_at, cycle_id))
    per_position = request.profit_loss / cycle[1]
    connection.execute("UPDATE positions SET status = ?, closed_at = ?, profit_loss = ? WHERE cycle_id = ?", (request.exit_reason, closed_at, per_position, cycle_id))
    connection.commit()
    connection.close()
    return {"cycle_id": cycle_id, "status": request.exit_reason, "profit_loss": request.profit_loss, "positions_closed": cycle[1], "closed_at": closed_at}
