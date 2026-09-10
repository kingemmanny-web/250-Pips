# 250 Pips backend

The backend is a FastAPI MT5 live-trading service with SQLite trade-history persistence.

## Run

From the project root:

```powershell
.\run-backend.ps1
```

The API runs at `http://127.0.0.1:8000`. Interactive API docs are available at `http://127.0.0.1:8000/docs`.

## Endpoints

- `GET /api/health` - service status and live-execution flag
- `GET /api/account` - live MT5 account and linked broker metadata
- `GET /api/broker/mt5/status` - MT5 package, configuration, connection, and account diagnostics
- `GET /api/bot/status` - analysis/trading worker state and latest result
- `POST /api/bot/start` - start scheduled live MT5 bot work
- `POST /api/bot/stop` - stop scheduled bot work
- `POST /api/broker/link` - save live broker metadata
- `GET /api/market/{instrument}` - market snapshot from MT5
- `POST /api/cycles` - submit a guarded MT5 live trade
- `POST /api/cycles/{cycle_id}/close` - close all positions in a cycle and record the exit reason/P&L
- `GET /api/history` - persisted trading cycles

Example cycle request:

```json
{
  "instrument": "EURUSD",
  "direction": "BUY",
  "positions": 4,
  "take_profit_pips": 250,
  "stop_loss_pips": 100,
  "score": 84
}
```

For an Exness account, the integration uses the installed MetaTrader 5 Python bridge plus a locally running MT5 terminal. Set `MT5_PATH`, `MT5_LOGIN`, `MT5_PASSWORD`, and `MT5_SERVER` outside source control. The broker adapter validates live orders before submission and attaches TP/SL to each order.

The MT5 adapter remains fail-closed. Live orders require `TRADING_MODE=live`, `LIVE_TRADING_ENABLED=true`, and `LIVE_TRADING_CONFIRMATION=I_UNDERSTAND_REAL_MONEY`. Start with an Exness demo account, verify `/api/broker/mt5/status`, and validate symbols and order volume before changing those flags.

Bot scheduling uses `BOT_INTERVAL_SECONDS`, `BOT_MIN_SCORE`, `BOT_INSTRUMENT`, and `BOT_AUTOSTART`. The bot starts only when live execution, explicit confirmation, and MT5 credentials are all present.

Entries require agreement between the EMA trend, RSI momentum, the latest closed M5 impulse candle, spread, and at least three higher-timeframe directions. The bot uses the broker symbol's actual pip size, so the target is exactly 250 pips (not a raw MT5 point count). When a validated pullback to the trend average is 3-30 pips away, it submits a buy/sell limit order; otherwise it enters at market. Existing positions and 250 Pips pending orders are excluded from rescans. These filters are measurable conditions, not a guarantee of profit or of a 250-pip move.
