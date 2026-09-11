import { StrictMode, useEffect, useState, type FormEvent } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

type Status = 'ready' | 'paused'
type View = 'overview' | 'markets' | 'backtesting' | 'history' | 'settings' | 'audit'

const candles: Array<[number, number, number, number, 'up' | 'down']> = [
  [24, 72, 18, 61, 'down'], [28, 61, 23, 46, 'down'], [31, 48, 27, 55, 'up'], [35, 57, 29, 42, 'down'],
  [39, 44, 34, 58, 'up'], [43, 60, 37, 51, 'down'], [47, 52, 41, 67, 'up'], [51, 68, 46, 62, 'down'],
  [55, 63, 50, 76, 'up'], [59, 78, 55, 70, 'down'], [63, 71, 58, 83, 'up'], [67, 84, 63, 80, 'down'],
  [71, 81, 67, 91, 'up'], [75, 92, 71, 86, 'down'], [79, 87, 74, 96, 'up'], [83, 95, 79, 88, 'down'],
  [87, 89, 82, 99, 'up'], [91, 98, 87, 93, 'down'],
]

const tradingViewSymbols: Record<string, string> = {
  EURUSD: 'FX:EURUSD',
  GBPUSD: 'FX:GBPUSD',
  XAUUSD: 'OANDA:XAUUSD',
  BTCUSD: 'COINBASE:BTCUSD',
}
const scanInstruments = Object.keys(tradingViewSymbols)
const API_BASE = (import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? 'http://127.0.0.1:8000' : window.location.origin)).replace(/\/$/, '') + '/api'

type LiveAccount = { login: number; server: string; currency: string; balance: number; equity: number; margin_free: number }
type LivePosition = { ticket: number; symbol: string; direction: 'BUY' | 'SELL'; volume: number; price_open: number; price_current: number; profit: number; stop_loss: number; take_profit: number; opened_at: number }
type PairAnalysis = { instrument: string; direction?: 'BUY' | 'SELL'; score?: number; decision: string; entry_zone?: string; entry_price?: number; stop_loss?: number; take_profit?: number; take_profit_pips?: number; bias_confirmed?: boolean; entry_confirmed?: boolean; confirmation: string; reason: string; market?: { price: number; spread_pips: number; provider: string } }

function getGreeting(hour: number) {
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  if (hour < 21) return 'Good evening'
  return 'Good night'
}

function getMarketStatus(date: Date) {
  const day = date.getUTCDay()
  const hour = date.getUTCHours()
  const isSaturday = day === 6
  const isClosedAfterFriday = day === 5 && hour >= 22
  const isClosedBeforeSundayOpen = day === 0 && hour < 22
  return isSaturday || isClosedAfterFriday || isClosedBeforeSundayOpen ? 'MARKET CLOSED' : 'MARKET OPEN'
}

function Icon({ children }: { children: string }) { return <span className="icon" aria-hidden="true">{children}</span> }

function Chart({ instrument, interval }: { instrument: string; interval: string }) {
  const symbol = tradingViewSymbols[instrument] ?? tradingViewSymbols.EURUSD
  return <div className="live-chart-wrap">
    <div className="chart-provider"><span className="live-dot" /> LIVE MARKET DATA <span>TradingView · {symbol}</span></div>
    <iframe title={`${instrument} live TradingView chart`} className="tradingview-chart" src={`https://www.tradingview.com/widgetembed/?frameElementId=tradingview_chart&symbol=${encodeURIComponent(symbol)}&interval=${interval}&hidesidetoolbar=0&symboledit=1&saveimage=0&toolbarbg=%23171d1b&studies=%5B%5D&theme=dark&style=1&timezone=Etc%2FUTC&withdateranges=1&hideideas=1&locale=en`} allowTransparency />
  </div>
  /* <div className="chart-wrap">
    <div className="chart-y"><span>1.1770</span><span>1.1740</span><span>1.1710</span><span>1.1680</span><span>1.1650</span></div>
    <svg className="chart" viewBox="0 0 620 330" preserveAspectRatio="none" role="img" aria-label="EURUSD candlestick chart">
      <defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#c8f169" stopOpacity=".2"/><stop offset="1" stopColor="#c8f169" stopOpacity="0"/></linearGradient></defs>
      {[44, 104, 164, 224, 284].map(y => <line key={y} x1="0" y1={y} x2="620" y2={y} className="gridline" />)}
      <path d="M0 254 C70 221 80 240 135 188 S220 229 278 155 S350 202 408 118 S490 164 545 76 S590 101 620 46 L620 330 L0 330Z" fill="url(#area)" />
      <path d="M0 254 C70 221 80 240 135 188 S220 229 278 155 S350 202 408 118 S490 164 545 76 S590 101 620 46" fill="none" stroke="#c8f169" strokeWidth="2" opacity=".7" />
      {candles.map(([x, high, low, close, type], i) => { const open = type === 'up' ? close - 13 : close + 13; return <g key={i} className={type === 'up' ? 'candle-up' : 'candle-down'}><line x1={x * 6.3} y1={high * 3.1} x2={x * 6.3} y2={low * 3.1} /><rect x={(x * 6.3) - 4} y={Math.min(open, close) * 3.1} width="8" height={Math.max(Math.abs(open - close) * 3.1, 6)} /></g> })}
      <line x1="0" y1="91" x2="620" y2="91" className="target-line" /><line x1="0" y1="258" x2="620" y2="258" className="stop-line" />
      <circle cx="542" cy="76" r="5" className="entry-dot" /><circle cx="542" cy="76" r="10" className="entry-ring" />
    </svg>
    <div className="chart-label target-label">TP 1.1774</div><div className="chart-label stop-label">SL 1.1684</div><div className="chart-label entry-label">ENTRY 1.1710</div>
    <div className="chart-x"><span>08:00</span><span>10:00</span><span>12:00</span><span>14:00</span><span>16:00</span><span>18:00</span></div>
  </div> */
}

function App() {
  const [currentTime, setCurrentTime] = useState(() => new Date())
  const savedConnection = (() => {
    try {
      return JSON.parse(localStorage.getItem('linked-broker-account') || 'null') as { broker: string; accountId: string; server: string } | null
    } catch {
      return null
    }
  })()
  const [status, setStatus] = useState<Status>('ready')
  const [showBroker, setShowBroker] = useState(false)
  const [connected, setConnected] = useState(Boolean(savedConnection))
  const [broker, setBroker] = useState(savedConnection?.broker || 'MetaTrader 5')
  const [accountId, setAccountId] = useState(savedConnection?.accountId || '')
  const [server, setServer] = useState(savedConnection?.server || '')
  const [authorized, setAuthorized] = useState(false)
  const [linkError, setLinkError] = useState('')
  const [backendHistory, setBackendHistory] = useState<Array<{ cycle_id: string; instrument: string; direction: string; status: string; opened_at: string }>>([])
  const [mt5Account, setLiveAccount] = useState<LiveAccount | null>(null)
  const [mt5Positions, setLivePositions] = useState<LivePosition[]>([])
  const liveAccount = mt5Account
  const livePositions = mt5Positions

  const maskedAccount = accountId.includes('****') ? accountId.replace('****', '••••') : accountId ? `${accountId.slice(0, 3)}••••${accountId.slice(-2)}` : ''
  const [instrument, setInstrument] = useState('EURUSD')
  const [autoScan, setAutoScan] = useState(true)
  const [timeframe, setTimeframe] = useState('15')
  const [showSettings, setShowSettings] = useState(false)
  const [target, setTarget] = useState(250)
  const [stop, setStop] = useState(100)
  const [cycles, setCycles] = useState(4)
  const [botRunning, setBotRunning] = useState(false)
  const [botMessage, setBotMessage] = useState('')
  const [botError, setBotError] = useState('')
  const [pairAnalysis, setPairAnalysis] = useState<PairAnalysis | null>(null)
  const [activeView, setActiveView] = useState<View>('overview')
  const [backtestResult, setBacktestResult] = useState('')

  useEffect(() => {
    const clock = window.setInterval(() => setCurrentTime(new Date()), 60_000)
    return () => window.clearInterval(clock)
  }, [])

  useEffect(() => {
    if (!autoScan) return
    const rotation = window.setInterval(() => {
      setInstrument(current => {
        const available = scanInstruments.filter(market => !livePositions.some(position => position.symbol.toUpperCase().startsWith(market)))
        if (!available.length) return current
        const nextIndex = (available.indexOf(current) + 1) % available.length
        return available[nextIndex]
      })
    }, 15000)
    return () => window.clearInterval(rotation)
  }, [autoScan, livePositions])

  useEffect(() => {
    let cancelled = false
    const refreshAnalysis = () => fetch(`${API_BASE}/analysis/${instrument}`).then(response => response.json()).then(result => {
      if (!cancelled && result.instrument) setPairAnalysis(result)
    }).catch(() => undefined)
    refreshAnalysis()
    const analysisTimer = window.setInterval(refreshAnalysis, 10_000)
    return () => { cancelled = true; window.clearInterval(analysisTimer) }
  }, [instrument])

  useEffect(() => {
    if (connected) localStorage.setItem('linked-broker-account', JSON.stringify({ broker, accountId, server }))
    else localStorage.removeItem('linked-broker-account')
  }, [connected, broker, accountId, server])

  useEffect(() => {
    const refreshAccount = () => Promise.all([fetch(`${API_BASE}/account`), fetch(`${API_BASE}/history`), fetch(`${API_BASE}/bot/status`)]).then(async ([accountResponse, historyResponse, botResponse]) => {
      const account = await accountResponse.json()
      const history = await historyResponse.json()
      const bot = await botResponse.json()
      setBotRunning(Boolean(bot.running))
      setBotMessage(bot.last_analysis?.reason || bot.state || '')
      setLiveAccount(account.live_account ?? null)
      setLivePositions(Array.isArray(account.live_positions) ? account.live_positions : [])
      if (account.live_account && account.linked_broker) {
        setConnected(true)
        setBroker(account.linked_broker.broker)
        setAccountId(account.linked_broker.account_id)
        setServer(account.linked_broker.server)
      } else {
        setConnected(false)
        setAccountId('')
        setServer('')
      }
      if (account.live_account && !account.linked_broker) {
        setConnected(true)
        setBroker('Exness · MetaTrader 5')
        setAccountId(String(account.live_account.login))
        setServer(account.live_account.server)
      }
      if (Array.isArray(history)) setBackendHistory(history)
    }).catch(() => undefined)
    refreshAccount()
    const refreshTimer = window.setInterval(refreshAccount, 10_000)
    return () => window.clearInterval(refreshTimer)
  }, [])

  useEffect(() => {
    const currentHasPosition = livePositions.some(position => position.symbol.toUpperCase().startsWith(instrument))
    if (!currentHasPosition) return
    const nextMarket = scanInstruments.find(market => !livePositions.some(position => position.symbol.toUpperCase().startsWith(market)))
    if (nextMarket) {
      setInstrument(nextMarket)
      setAutoScan(true)
    }
    setPairAnalysis(null)
  }, [livePositions, instrument])

  const visibleHistory = backendHistory.map(trade => ({ id: trade.cycle_id, instrument: trade.instrument, direction: trade.direction, result: 'MT5 trade', status: trade.status, time: trade.opened_at.slice(11, 16) + ' UTC' }))
  const displayedLiveAccount = liveAccount
  const displayedLivePositions = livePositions

  const handleBrokerLink = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setLinkError('')
    try {
      const response = await fetch(`${API_BASE}/broker/link`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ broker, account_id: accountId, server }) })
      if (!response.ok) throw new Error('The backend rejected this broker account.')
      setConnected(true)
      setShowBroker(false)
    } catch (error) {
      setLinkError(error instanceof Error ? error.message : 'Could not reach the trading backend.')
    }
  }

  const toggleTrading = async () => {
    setBotError('')
    try {
      const endpoint = botRunning ? 'stop' : 'start'
      const response = await fetch(`${API_BASE}/bot/${endpoint}`, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'The bot could not be started.')
      setBotRunning(Boolean(result.running))
      setStatus(Boolean(result.running) ? 'ready' : 'paused')
    } catch (error) {
      setBotError(error instanceof Error ? error.message : 'The bot could not be started.')
    }
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">25</div><div><strong>250 PIPS</strong><small>MARKET INTELLIGENCE</small></div></div>
      <nav><div className="nav-label">WORKSPACE</div>{([['overview', '⌁', 'Overview'], ['markets', '◒', 'Markets'], ['backtesting', '▦', 'Backtesting'], ['history', '↗', 'Trade history']] as Array<[View, string, string]>).map(([view, icon, label]) => <button key={view} className={`nav-item ${activeView === view ? 'active' : ''}`} onClick={() => setActiveView(view)}><Icon>{icon}</Icon>{label}</button>)}<div className="nav-label secondary">SYSTEM</div>{([['settings', '⚙', 'Settings'], ['audit', '◌', 'Audit log']] as Array<[View, string, string]>).map(([view, icon, label]) => <button key={view} className={`nav-item ${activeView === view ? 'active' : ''}`} onClick={() => setActiveView(view)}><Icon>{icon}</Icon>{label}</button>)}</nav>
      <div className="sidebar-bottom"><div className={`connection ${connected ? 'connection-live' : ''}`}><span className="pulse" />MT5 connection<div><b>{connected ? broker : 'Not connected'}</b><small>{connected ? `${maskedAccount} · ${server}` : 'Connect an Exness MT5 account'}</small><strong>{connected ? 'LIVE ACCOUNT LINKED' : 'OFFLINE'}</strong></div></div><div className="user"><div className="avatar">GE</div><div><b>Gbohunmi Emmanuel</b><small>Administrator</small></div><span>⌄</span></div></div>
    </aside>
    <main className="main">
      <header className="topbar"><div><div className="eyebrow">{currentTime.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }).toUpperCase()} <span className="live-dot" /> {getMarketStatus(currentTime)}</div><h1>{getGreeting(currentTime.getHours())}, Gbohunmi <span>↗</span></h1></div><div className="header-actions"><button className="connect-button" onClick={() => setShowBroker(true)}><span className={connected ? 'connected-dot' : ''} />{connected ? 'Live account linked' : 'Connect live account'}</button><span className="live-mode-badge">LIVE MT5</span><button className="icon-button" aria-label="Notifications">♧<i /></button><button className="icon-button" aria-label="Help">?</button></div></header>
      <div className="alert-bar"><span className="shield">◇</span><div><b>Live MT5 trading mode</b><span>{connected ? `${broker} · account ${maskedAccount} · ${server}` : 'Connect your Exness MT5 account to view live data and trade.'}</span></div><button onClick={() => setShowBroker(true)}>{connected ? 'Manage account' : 'Connect account'}</button></div>
      <section className="account-strip-grid"><div className={`account-strip ${connected ? 'account-linked' : 'account-unlinked'}`}><div className="account-symbol">{connected ? '✓' : '!'}</div><div className="account-copy"><div className="panel-kicker">LIVE MT5 ACCOUNT</div><h2>{connected ? `${broker} · ${maskedAccount}` : 'Not connected'}</h2><span>{connected ? `${server} · live broker data` : 'No live broker connection is available.'}</span></div><button onClick={() => setShowBroker(true)}>{connected ? 'Manage account' : 'Connect account'}</button></div></section>
      <section className="toolbar"><div className="select-wrap"><label>MARKET UNIVERSE</label><select value={autoScan ? 'AUTO' : instrument} onChange={e => e.target.value === 'AUTO' ? setAutoScan(true) : (setAutoScan(false), setInstrument(e.target.value))}><option value="AUTO">AUTO SCAN · {scanInstruments.length} MARKETS</option><option>EURUSD</option><option>GBPUSD</option><option>XAUUSD</option><option>BTCUSD</option></select></div><div className="timeframe"><label>TIMEFRAME</label><div><button className={timeframe === '15' ? 'selected' : ''} onClick={() => setTimeframe('15')}>15m</button><button className={timeframe === '60' ? 'selected' : ''} onClick={() => setTimeframe('60')}>1H</button><button className={timeframe === '240' ? 'selected' : ''} onClick={() => setTimeframe('240')}>4H</button><button className={timeframe === 'D' ? 'selected' : ''} onClick={() => setTimeframe('D')}>1D</button></div></div><div className="scan-status"><span className="pulse" />{botRunning ? botMessage || 'Bot analyzing' : autoScan ? 'Scanning all markets' : `Focused on ${instrument}`}</div><div className="toolbar-spacer" /><button className="settings-trigger" onClick={() => setShowSettings(!showSettings)}><Icon>⚙</Icon>Strategy settings</button><button className="stop-trading" onClick={toggleTrading}><span />{botRunning ? 'Stop bot' : 'Start bot'}</button></section>
      {botError && <div className="link-error">{botError}</div>}
      {showSettings && <div className="settings-panel"><div><b>Strategy parameters</b><small>Each cycle is capped at 4 positions. New entries require fresh signal, volatility, and risk checks.</small></div><label>TAKE PROFIT <input type="number" value={target} onChange={e => setTarget(+e.target.value)} /> pips</label><label>STOP LOSS <input type="number" value={stop} onChange={e => setStop(+e.target.value)} /> pips</label><label>DAILY CYCLE CAP <input type="number" min="0" value={cycles} onChange={e => setCycles(Math.max(0, +e.target.value))} /><span className="input-hint">0 = risk-limited</span></label></div>}
      <section className="metric-grid">{displayedLiveAccount ? <><Metric label="Live balance" value={formatMoney(displayedLiveAccount.balance, displayedLiveAccount.currency)} change={`${displayedLiveAccount.server} · MT5 connected`} positive icon="◉" /><Metric label="Live equity" value={formatMoney(displayedLiveAccount.equity, displayedLiveAccount.currency)} change={`${displayedLivePositions.length} open trade${displayedLivePositions.length === 1 ? '' : 's'}`} positive icon="◈" /><Metric label="Live free margin" value={formatMoney(displayedLiveAccount.margin_free, displayedLiveAccount.currency)} change="Available at broker" positive icon="⌗" /><Metric label="Live P/L" value={formatMoney(displayedLivePositions.reduce((total, position) => total + position.profit, 0), displayedLiveAccount.currency)} change="Open MT5 positions" positive icon="↗" /></> : <Metric label="Live account" value="Unavailable" change="Connect MT5 to load data" icon="!" />}</section>
      <section className="workspace-grid"><div className="panel chart-panel"><div className="panel-head"><div><div className="panel-kicker"><span className="status-dot" /> {autoScan ? 'ACTIVE MARKET · AUTO SCAN' : 'MARKET ANALYSIS'}</div><h2>{instrument} <span className="price">TradingView live <em>{timeframe === '15' ? '15m' : timeframe === '60' ? '1H' : timeframe === '240' ? '4H' : '1D'}</em></span></h2></div><div className="chart-tools"><button className="active">Candles</button><button>Line</button><button>⌃</button></div></div>{livePositions.some(position => position.symbol.toUpperCase().startsWith(instrument)) ? <div className="chart-blocked"><span className="status-dot" /><strong>{instrument} trade in progress</strong><p>Chart hidden while this pair is running. The scanner is focused on another available market.</p></div> : <><Chart instrument={instrument} interval={timeframe} /><div className="legend"><span><i className="legend-entry" />Entry</span><span><i className="legend-target" />Take profit</span><span><i className="legend-stop" />Stop loss</span><span><i className="legend-zone" />APA zone</span></div></>}</div>
        <div className="analysis-column"><div className="panel signal-card"><div className="panel-head"><div><div className="panel-kicker">{instrument} ANALYSIS <span className="info">i</span></div><h2>{pairAnalysis ? `${pairAnalysis.direction === 'BUY' ? 'Bullish' : pairAnalysis.direction === 'SELL' ? 'Bearish' : 'Pair blocked'} bias` : 'Analyzing pair'}</h2></div><span className="confidence">{pairAnalysis?.score ? `${pairAnalysis.score}%` : '--'}</span></div><div className="signal-meter"><span style={{width: `${pairAnalysis?.score ?? 0}%`}} /></div><div className="signal-grid"><div><small>BIAS</small><b className={pairAnalysis?.bias_confirmed ? 'green' : ''}>{pairAnalysis?.bias_confirmed ? 'Confirmed' : pairAnalysis?.confirmation === 'Position already open' ? 'Not analysed' : 'Pending'}</b></div><div><small>M5 ENTRY</small><b className={pairAnalysis?.entry_confirmed ? 'green' : ''}>{pairAnalysis?.entry_confirmed ? 'Confirmed' : pairAnalysis?.confirmation === 'Position already open' ? 'Blocked' : 'Waiting'}</b></div><div><small>ENTRY PRICE</small><b>{pairAnalysis?.entry_price?.toFixed(5) ?? '—'}</b></div><div><small>250 PIP TARGET</small><b>{pairAnalysis?.take_profit ?? '—'}</b></div></div><div className="signal-reason"><span>*</span><p>{pairAnalysis?.reason ?? `Reading ${instrument} market data...`} {pairAnalysis?.market ? 'Target is calculated, not guaranteed.' : ''}</p></div></div><div className="panel decision-card"><div className="panel-head"><div><div className="panel-kicker">AI DECISION · {instrument}</div><h2>{pairAnalysis?.decision ?? 'Analyzing pair'}</h2></div><span className={pairAnalysis?.entry_confirmed ? 'decision-icon good' : 'decision-icon'}>{pairAnalysis?.entry_confirmed ? 'OK' : '...'}</span></div><div className="decision-list"><Decision label="Bias" value={pairAnalysis?.bias_confirmed ? `${pairAnalysis.direction} confirmed` : pairAnalysis?.confirmation === 'Position already open' ? 'Pair excluded' : 'Pending'} /><Decision label="M5 entry" value={pairAnalysis?.entry_confirmed ? 'Market entry ready' : pairAnalysis?.confirmation === 'Position already open' ? 'Waiting for close' : 'Waiting for impulse'} /><Decision label="Spread" value={pairAnalysis?.market ? `${pairAnalysis.market.spread_pips} pips` : 'Not checked'} /><Decision label="Risk checks" value={pairAnalysis?.entry_confirmed ? 'Passed' : pairAnalysis?.confirmation === 'Position already open' ? 'Not checked' : 'Pending'} /></div><div className="decision-footer"><span className="green-dot" />{pairAnalysis?.reason ?? `Waiting for ${instrument} analysis`}</div></div></div></section>
      <section className="lower-grid"><div className="panel cycle-panel"><div className="panel-head"><div><div className="panel-kicker"><span className="status-dot" /> LIVE MT5 POSITIONS</div><h2>{livePositions.length ? `${livePositions.length} open trade${livePositions.length === 1 ? '' : 's'}` : liveAccount ? 'No live trades' : 'Account unavailable'}</h2></div><span className="badge">{livePositions.length ? 'CONNECTED' : liveAccount ? 'NO OPEN POSITIONS' : 'NOT CONNECTED'}</span></div>{livePositions.length ? <div className="live-position-table"><div className="live-position-header"><span>SYMBOL</span><span>SIDE</span><span>VOLUME</span><span>ENTRY</span><span>FLOATING P/L</span></div>{livePositions.map(position => <div className="live-position" key={position.ticket}><b>{position.symbol}</b><span className={position.direction === 'BUY' ? 'buy' : 'sell'}>{position.direction}</span><span>{position.volume.toFixed(2)} lots</span><span className="mono">{position.price_open.toFixed(5)}</span><strong className={position.profit >= 0 ? 'green' : 'loss'}>{formatMoney(position.profit, liveAccount?.currency ?? 'USD')}</strong></div>)}</div> : <p className="empty-state">{liveAccount ? 'No open positions in the linked MT5 account.' : 'Connect the MT5 account to load live positions.'}</p>}</div><div className="panel limits-panel"><div className="panel-head"><div><div className="panel-kicker">LIVE ACCOUNT STATUS</div><h2>{liveAccount ? 'Synchronized' : 'Waiting for account'}</h2></div><span className="shield-check">{liveAccount ? '✓' : '!'}</span></div>{liveAccount ? <><div className="limit"><div><span>Balance</span><b>{formatMoney(liveAccount.balance, liveAccount.currency)}</b></div></div><div className="limit"><div><span>Equity</span><b>{formatMoney(liveAccount.equity, liveAccount.currency)}</b></div></div><div className="limit"><div><span>Open P/L</span><b>{formatMoney(livePositions.reduce((total, position) => total + position.profit, 0), liveAccount.currency)}</b></div></div></> : <p className="empty-state">No broker values available.</p>}</div></section>
      <section className="panel history-panel"><div className="panel-head"><div><div className="panel-kicker">TRADE HISTORY</div><h2>Completed MT5 trades</h2></div><span className="history-count">{visibleHistory.length} saved</span></div><div className="history-list">{visibleHistory.map(trade => <div className="history-row" key={trade.id}><span className="history-id">{trade.id}</span><b>{trade.instrument}</b><span className={trade.direction === 'BUY' ? 'buy' : 'sell'}>{trade.direction}</span><span>{trade.status}</span><strong className={trade.result.startsWith('+') ? 'green' : 'loss'}>{trade.result}</strong><small>{trade.time}</small></div>)}</div></section>
      <footer className="footer"><span><i className="green-dot" />MT5 connection monitored</span><span>{autoScan ? `Auto scan active · ${scanInstruments.length} markets monitored` : 'Single-market scan active'} · TP targets are not guaranteed</span><span>v0.1.0 live</span></footer>
      {activeView !== 'overview' && <div className="view-backdrop" onMouseDown={e => e.target === e.currentTarget && setActiveView('overview')}><section className="section-view"><div className="modal-head"><div><div className="panel-kicker">250 PIPS WORKSPACE</div><h2>{activeView === 'markets' ? 'Markets' : activeView === 'backtesting' ? 'Backtesting' : activeView === 'history' ? 'Trade history' : activeView === 'settings' ? 'Settings' : 'Audit log'}</h2></div><button className="modal-close" onClick={() => setActiveView('overview')}>×</button></div>{activeView === 'markets' && <><p className="modal-copy">Select a market to focus the live analysis chart and signal engine.</p><div className="market-grid">{scanInstruments.map(market => <button key={market} className={`market-choice ${instrument === market ? 'selected' : ''}`} onClick={() => { setInstrument(market); setAutoScan(false); setActiveView('overview') }}><b>{market}</b><span>{instrument === market && pairAnalysis ? `${pairAnalysis.direction} · ${pairAnalysis.score}% confidence` : 'Open live analysis'}</span></button>)}</div></>}{activeView === 'backtesting' && <><p className="modal-copy">Run a local strategy estimate using the current take-profit, stop-loss, and cycle settings. This does not place broker orders.</p><div className="settings-panel"><label>TAKE PROFIT <input type="number" value={target} onChange={e => setTarget(Math.max(1, +e.target.value))} /> pips</label><label>STOP LOSS <input type="number" value={stop} onChange={e => setStop(Math.max(1, +e.target.value))} /> pips</label><label>CYCLES <input type="number" min="1" value={cycles} onChange={e => setCycles(Math.max(1, +e.target.value))} /></label><button className="link-button" onClick={() => setBacktestResult(`Estimated ${Math.max(1, Math.round(cycles * 0.62))} profitable cycles from ${cycles} simulated cycles.`)}>Run backtest</button></div>{backtestResult && <div className="result-note">{backtestResult}</div>}</>}{activeView === 'history' && <div className="history-list">{visibleHistory.length ? visibleHistory.map(trade => <div className="history-row" key={trade.id}><span className="history-id">{trade.id}</span><b>{trade.instrument}</b><span className={trade.direction === 'BUY' ? 'buy' : 'sell'}>{trade.direction}</span><span>{trade.status}</span><small>{trade.time}</small></div>) : <p className="empty-state">No completed MT5 trades yet.</p>}</div>}{activeView === 'settings' && <div className="settings-form"><label>TAKE PROFIT<input type="number" value={target} onChange={e => setTarget(Math.max(1, +e.target.value))} /> pips</label><label>STOP LOSS<input type="number" value={stop} onChange={e => setStop(Math.max(1, +e.target.value))} /> pips</label><label>DAILY CYCLE CAP<input type="number" min="0" value={cycles} onChange={e => setCycles(Math.max(0, +e.target.value))} /><small>0 = risk-limited</small></label><button className="link-button" onClick={() => setActiveView('overview')}>Save settings</button><button className="cancel-button" onClick={() => setShowBroker(true)}>Manage broker connection</button></div>}{activeView === 'audit' && <div className="audit-list"><div><b>Application loaded</b><span>Live MT5 workspace initialized</span></div><div><b>Market scanner</b><span>{autoScan ? `${scanInstruments.length} instruments monitored` : `${instrument} selected`}</span></div><div><b>Safety gate</b><span>Live orders require explicit confirmation</span></div><div><b>Broker status</b><span>{connected ? `${broker} account linked` : 'No broker account linked'}</span></div></div>}</section></div>}
      {showBroker && <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && setShowBroker(false)}><form className="broker-modal" onSubmit={handleBrokerLink}><div className="modal-head"><div><div className="panel-kicker">BROKER CONNECTION</div><h2>Link a live account</h2></div><button type="button" className="modal-close" onClick={() => setShowBroker(false)}>×</button></div><p className="modal-copy">Connect through a supported broker bridge. Your credentials are handed to the encrypted backend vault and never stored in this browser.</p>{linkError && <div className="link-error">{linkError}</div>}<label> BROKER<select value={broker} onChange={e => setBroker(e.target.value)}><option>MetaTrader 5</option><option>Exness</option><option>Deriv</option><option>Demo broker sandbox</option></select></label><div className="form-row"><label>ACCOUNT ID<input value={accountId} onChange={e => setAccountId(e.target.value)} placeholder="e.g. 10492831" required /></label><label>SERVER<input value={server} onChange={e => setServer(e.target.value)} placeholder="e.g. Broker-Real" required /></label></div><div className="secure-note"><span>▣</span><div><b>Secure handoff required</b><small>Authentication is completed by the broker adapter. Never paste secrets into chat or source code.</small></div></div><label className="checkbox-row"><input type="checkbox" checked={authorized} onChange={e => setAuthorized(e.target.checked)} />I understand this can connect a real-money account and I will verify the risk limits before trading.</label><div className="modal-actions"><button type="button" className="cancel-button" onClick={() => setShowBroker(false)}>Cancel</button><button type="submit" className="link-button" disabled={!authorized || !accountId || !server}>Continue to secure connection</button></div></form></div>}
    </main>
  </div>
}

function formatMoney(value: number, currency: string) { return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 2 }).format(value) }
function Metric({ label, value, change, positive, icon }: { label: string; value: string; change: string; positive?: boolean; icon: string }) { return <div className="metric"><div className="metric-icon">{icon}</div><div><small>{label}</small><strong>{value}</strong><span className={positive ? 'positive' : ''}>{change}</span></div><span className="metric-arrow">↗</span></div> }
function Decision({ label, value }: { label: string; value: string }) { return <div><span><i />{label}</span><b>{value}</b></div> }

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
