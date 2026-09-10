from __future__ import annotations

import os
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

ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(ROOT / "backend" / "data" / "trading.sqlite3")))
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
MAX_POSITIONS_PER_CYCLE = 4
DEFAULT_TP_PIPS = 250
DEFAULT_SL_PIPS = int(os.getenv("DEFAULT_STOP_LOSS_PIPS", "100"))
MAX_SPREAD_PIPS = float(os.getenv("MAX_SPREAD_PIPS", "1.5"))
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
LIVE_TRADING_CONFIRMATION = os.getenv("LIVE_TRADING_CONFIRMATION", "") == "I_UNDERSTAND_REAL_MONEY"
BOT_INTERVAL_SECONDS = int(os.getenv("BOT_INTERVAL_SECONDS", "60"))
BOT_AUTOSTART = os.getenv("BOT_AUTOSTART", "true").lower() == "true"
SCAN_INSTRUMENTS = ("EURUSD", "GBPUSD", "XAUUSD", "BTCUSD")

app = FastAPI(title="250 Pips Trading API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:4173", "http://127.0.0.1:4174", "http://127.0.0.1:5173", "http://127.0.0.1:5174", "http://localhost:4173", "http://localhost:4174", "http://localhost:5173", "http://localhost:5174"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


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
    direction = snapshot.get("direction", "BUY")
    pip_size = float(snapshot.get("pip_size", market_data.pip_sizes[instrument]))
    price = snapshot["price"]
    take_profit_pips = DEFAULT_TP_PIPS
    stop_loss_pips = int(os.getenv("DEFAULT_STOP_LOSS_PIPS", "100"))
    candle_signal = snapshot.get("candle_signal", {})
    strategy = snapshot.get("strategy", {})
    score = 0
    if candle_signal.get("qualified"):
        score += 30
    if strategy.get("direction") == direction:
        score += 20
    rsi = float(strategy.get("rsi", 50))
    momentum_allowed = 50 <= rsi <= 72 if direction == "BUY" else 28 <= rsi <= 50
    if momentum_allowed:
        score += 15
    direction_aligned = candle_signal.get("direction") in (None, direction)
    spread_allowed = snapshot["spread_pips"] <= MAX_SPREAD_PIPS
    aligned_timeframes = [timeframe for timeframe, higher_snapshot in higher_timeframes.items() if higher_snapshot["direction"] == direction]
    trend_confluence = len(aligned_timeframes) >= 3
    bias_confirmed = trend_confluence and direction in ("BUY", "SELL")
    if trend_confluence:
        score += 25
    if spread_allowed:
        score += 10
    minimum_score = int(os.getenv("BOT_MIN_SCORE", "84"))
    can_trade = score >= minimum_score and candle_signal.get("qualified", False) and direction_aligned and spread_allowed and trend_confluence and momentum_allowed
    distance_tp = take_profit_pips * pip_size
    distance_sl = stop_loss_pips * pip_size
    entry_price = price
    entry_type = "MARKET"
    trend_average = float(snapshot.get("trend_average", price))
    pullback_gap_pips = abs(price - trend_average) / pip_size if pip_size else 0
    if can_trade and 3 <= pullback_gap_pips <= 30 and ((direction == "BUY" and trend_average < price) or (direction == "SELL" and trend_average > price)):
        entry_price = trend_average
        entry_type = "LIMIT"
    reason = f"Strategy score {score}/100: trend, momentum, impulse candle, spread, and {len(aligned_timeframes)}/4 timeframe alignment passed"
    if not candle_signal.get("qualified", False):
        reason = candle_signal.get("reason", "Waiting for a qualified M5 candle")
    elif not direction_aligned:
        reason = "M5 candle direction does not match the trend"
    elif not spread_allowed:
        reason = f"Spread {snapshot['spread_pips']} pips exceeds the {MAX_SPREAD_PIPS} pip limit"
    elif not momentum_allowed:
        reason = f"RSI momentum filter is not aligned with {direction} ({rsi:.1f})"
    elif not trend_confluence:
        reason = f"Multi-timeframe trend confirmation is incomplete ({len(aligned_timeframes)}/4 aligned)"
    return {"instrument": instrument, "direction": direction, "score": min(100, score), "decision": "TRADE" if can_trade else "WAIT" if for_execution else "Signal confirmed" if score >= 70 else "Waiting for M5 impulse", "entry_zone": f"{entry_price - pip_size * 6:.{5 if pip_size < 0.01 else 2}f} - {entry_price + pip_size * 6:.{5 if pip_size < 0.01 else 2}f}", "entry_price": round(entry_price, int(snapshot.get("digits", 5))), "entry_type": entry_type, "pullback_gap_pips": round(pullback_gap_pips, 1), "stop_loss": round(entry_price - distance_sl if direction == "BUY" else entry_price + distance_sl, int(snapshot.get("digits", 5))), "take_profit": round(entry_price + distance_tp if direction == "BUY" else entry_price - distance_tp, int(snapshot.get("digits", 5))), "take_profit_pips": take_profit_pips, "stop_loss_pips": stop_loss_pips, "pip_size": pip_size, "bias_confirmed": bias_confirmed, "entry_confirmed": can_trade, "confirmation": "Entry confirmed" if can_trade else "Bias confirmed" if bias_confirmed else "Waiting", "reason": reason, "market": snapshot, "timeframes": {"M5": {"direction": direction, "qualified": candle_signal.get("qualified", False)}, **{timeframe: {"direction": value["direction"], "trend_average": value["trend_average"]} for timeframe, value in higher_timeframes.items()}}, "timeframe_confluence": {"aligned": aligned_timeframes, "aligned_count": len(aligned_timeframes), "required": 3}, "analyzed_at": datetime.now(UTC).isoformat()}


def execute_bot_trade(analysis: dict) -> dict:
    request = CycleRequest(instrument=analysis["instrument"], direction=analysis["direction"], score=analysis["score"], positions=min(MAX_POSITIONS_PER_CYCLE, int(os.getenv("BOT_POSITIONS", "4"))), take_profit_pips=analysis["take_profit_pips"], stop_loss_pips=analysis["stop_loss_pips"])
    if not LIVE_TRADING_ENABLED or not LIVE_TRADING_CONFIRMATION:
        raise RuntimeError("Live execution is disabled by the safety gate")
    positions = mt5_broker.positions()
    if instrument_has_open_position(request.instrument, positions):
        raise RuntimeError(f"{request.instrument} already has an open MT5 position")
    if analysis.get("entry_type") == "LIMIT":
        orders = mt5_broker.open_limit_orders(request.instrument, request.direction, request.positions, analysis["entry_price"], request.take_profit_pips, request.stop_loss_pips)
    else:
        orders = mt5_broker.open_market_orders(request.instrument, request.direction, request.positions, request.take_profit_pips, request.stop_loss_pips)
    return {"mode": "live", "status": "OPEN", "entry_type": analysis.get("entry_type", "MARKET"), "target_pips": DEFAULT_TP_PIPS, "orders": orders, "opened_at": datetime.now(UTC).isoformat()}


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
    return {"status": "ok", "mode": "live", "live_execution_enabled": LIVE_TRADING_ENABLED and LIVE_TRADING_CONFIRMATION, "mt5": mt5_broker.status(), "database": str(DATABASE_PATH)}


@app.get("/api/broker/mt5/status")
def mt5_status() -> dict:
    return mt5_broker.status()


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
