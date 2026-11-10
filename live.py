"""Live US-equity PAPER trading integration for QuantLab.

No live-money broker endpoint exists in this module. Data is fetched from Alpaca's
IEX feed. When PAPER_AUTO_TRADE is enabled, this process may place orders solely
in the Alpaca paper trading environment, subject to conservative risk limits.
"""
from __future__ import annotations

import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

PAPER_HOST = 'https://paper-api.alpaca.markets'
MARKET_DATA_HOST = 'https://data.alpaca.markets'
DEFAULT_SYMBOLS = ('SPY', 'QQQ', 'IWM')
BOT_SYMBOL = 'SPY'
BOT_POLL_SECONDS = 60
MAX_POSITION_FRACTION = 0.10
MAX_ORDER_DOLLARS = 10_000
MIN_BARS = 20
MIN_TRADE_GAP_SECONDS = 3600

_state_lock = threading.RLock()
_bot_state: dict[str, Any] = {'last_scan': None, 'last_action': None, 'signal': 'NOT STARTED', 'detail': 'Automation is disabled until explicitly configured.', 'last_error': None}
_cached: dict[str, Any] = {'time': 0, 'payload': None}
_worker: threading.Thread | None = None
_stop = threading.Event()


def configured() -> bool:
    return bool(os.getenv('ALPACA_PAPER_KEY_ID') and os.getenv('ALPACA_PAPER_SECRET_KEY'))


def auto_enabled() -> bool:
    return configured() and os.getenv('PAPER_AUTO_TRADE', 'false').lower() == 'true'


def _auth() -> dict[str, str]:
    return {'APCA-API-KEY-ID': os.environ['ALPACA_PAPER_KEY_ID'], 'APCA-API-SECRET-KEY': os.environ['ALPACA_PAPER_SECRET_KEY']}


def _request(path: str, *, data: bool = False, params: dict | None = None, method: str = 'GET', body: dict | None = None) -> Any:
    # Enforce the paper endpoint. Credentials never leave the server and no
    # public web endpoint forwards arbitrary order requests.
    host = MARKET_DATA_HOST if data else PAPER_HOST
    with httpx.Client(timeout=8.0, follow_redirects=False) as client:
        response = client.request(method, host + path, headers=_auth(), params=params, json=body)
        response.raise_for_status()
        return response.json()


def _float(value: Any) -> float | None:
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def parse_snapshot(snapshot: dict[str, Any], symbol: str) -> dict[str, Any]:
    trade = snapshot.get('latestTrade') or {}
    quote = snapshot.get('latestQuote') or {}
    price = _float(trade.get('p'))
    observed = trade.get('t')
    if price is None or not observed:
        return {'symbol': symbol, 'price': None, 'observed_at': None, 'bid': None, 'ask': None, 'source': 'IEX / NO TRADE'}
    return {
        'symbol': symbol, 'price': price, 'observed_at': observed,
        'bid': _float(quote.get('bp')), 'ask': _float(quote.get('ap')),
        'source': 'IEX REAL-TIME (LIMITED EXCHANGE COVERAGE)',
    }


def _utc_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def is_fresh(value: str | None, *, max_age_seconds: int = 150) -> bool:
    d = _utc_datetime(value)
    return d is not None and timedelta(seconds=-15) <= datetime.now(timezone.utc)-d <= timedelta(seconds=max_age_seconds)


def _position_summary(obj: dict[str, Any]) -> dict[str, Any]:
    return {key: obj.get(key) for key in ('symbol', 'side', 'qty', 'avg_entry_price', 'current_price', 'market_value', 'unrealized_pl', 'unrealized_plpc')}


def _order_summary(obj: dict[str, Any]) -> dict[str, Any]:
    return {key: obj.get(key) for key in ('symbol', 'side', 'qty', 'filled_qty', 'status', 'filled_avg_price', 'submitted_at', 'filled_at', 'client_order_id')}


def get_public_status() -> dict[str, Any]:
    """Read-only public dashboard. Disconnected means no fabricated live prices."""
    now = datetime.now(timezone.utc).isoformat()
    with _state_lock:
        bot = dict(_bot_state)
    if not configured():
        return {
            'mode':'NOT CONNECTED', 'connected':False, 'configured':False,
            'auto_trading':False,'capital_type':'PAPER ONLY', 'currency':'USD',
            'updated_at':now, 'market':None, 'account':None, 'quotes':[],
            'positions':[], 'orders':[], 'equity_history':[], 'bot':bot,
            'message':'Connect Alpaca Paper Trading credentials on the server to display real prices and account activity. No simulated quotes are shown here.'
        }
    try:
        with _state_lock:
            if _cached['payload'] is not None and time.monotonic()-_cached['time']<10:
                return {**_cached['payload'], 'bot':bot, 'auto_trading':auto_enabled()}
        account = _request('/v2/account')
        clock = _request('/v2/clock')
        positions = _request('/v2/positions')
        orders = _request('/v2/orders', params={'status':'all', 'limit':12, 'direction':'desc'})
        snapshots = _request('/v2/stocks/snapshots',data=True,params={'symbols':','.join(DEFAULT_SYMBOLS),'feed':'iex'})
        try:
            hist = _request('/v2/account/portfolio/history', params={'period':'1M','timeframe':'1D','extended_hours':'false'})
            equity_history = [{'date':datetime.fromtimestamp(t,tz=timezone.utc).date().isoformat(),'equity':float(v)}
                for t,v in zip(hist.get('timestamp',[]),hist.get('equity',[])) if v is not None and v>0]
        except (httpx.HTTPError, ValueError, KeyError):
            equity_history=[]
        quotes = [parse_snapshot(snapshots.get(s) or {},s) for s in DEFAULT_SYMBOLS]
        for quote in quotes:
            quote['fresh'] = is_fresh(quote['observed_at']) if clock.get('is_open') else False
        payload = {
            'mode':'LIVE PAPER', 'connected':True, 'configured':True,
            'auto_trading':auto_enabled(), 'capital_type':'PAPER ONLY', 'currency':'USD',
            'updated_at':datetime.now(timezone.utc).isoformat(),
            'market':{'is_open':clock.get('is_open',False),'timestamp':clock.get('timestamp'),'next_open':clock.get('next_open'),'next_close':clock.get('next_close')},
            'account':{k:_float(account.get(k)) for k in ('equity','cash','buying_power','portfolio_value','last_equity')},
            'quotes':quotes, 'positions':[_position_summary(p) for p in positions],
            'orders':[_order_summary(o) for o in orders], 'equity_history':equity_history,
            'bot':bot, 'message':'Real Alpaca paper account and IEX exchange market data. Paper executions are simulated, not exchange fills.'
        }
        with _state_lock:
            _cached.update(time=time.monotonic(),payload=payload)
        return payload
    except httpx.HTTPStatusError as ex:
        msg=f'Alpaca API returned HTTP {ex.response.status_code}. Check paper credentials, account permissions and IEX entitlements.'
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as ex:
        msg=f'Live connection temporarily unavailable ({type(ex).__name__}). No demo values substituted.'
    return {'mode':'CONNECTION ERROR','connected':False, 'configured':True,
            'auto_trading':auto_enabled(),'updated_at':now,'capital_type':'PAPER ONLY',
            'market':None,'account':None,'quotes':[],'positions':[],'orders':[],
            'equity_history':[],'bot':bot,'message':msg}


def compute_momentum(prices: list[float]) -> str:
    """Long-only, 20-bar SMA with 0.1% dead band; this is a toy model, not alpha."""
    if len(prices)<MIN_BARS+1 or any(x<=0 or not math.isfinite(x) for x in prices[-(MIN_BARS+1):]):
        return 'INSUFFICIENT DATA'
    baseline=sum(prices[-(MIN_BARS+1):-1])/MIN_BARS
    latest=prices[-1]
    if latest>baseline*1.001:
        return 'LONG'
    if latest<baseline*.999:
        return 'FLAT'
    return 'HOLD'


def _bar_data() -> list[dict[str, Any]]:
    start=(datetime.now(timezone.utc)-timedelta(hours=7)).isoformat()
    answer=_request(f'/v2/stocks/{BOT_SYMBOL}/bars',data=True,params={'timeframe':'1Min','start':start,'limit':600,'feed':'iex','sort':'asc'})
    return answer.get('bars',[])


def _open_order_exists() -> bool:
    orders=_request('/v2/orders',params={'status':'open','limit':100})
    return any(o.get('symbol')==BOT_SYMBOL for o in orders)


def scan_once() -> None:
    """Safe paper-only, minute-frequency bot. Never triggered via public HTTP."""
    with _state_lock:
        _bot_state['last_scan']=datetime.now(timezone.utc).isoformat()
    if not auto_enabled():
        with _state_lock:
            _bot_state.update(signal='DISABLED', detail='PAPER_AUTO_TRADE is not enabled.')
        return
    try:
        clock=_request('/v2/clock')
        if not clock.get('is_open'):
            with _state_lock:
                _bot_state.update(signal='MARKET CLOSED',detail='US regular session is closed. No orders sent.',last_error=None)
            return
        bars=_bar_data()
        # Do not act on stale or incomplete IEX price data.
        if not bars or not is_fresh(bars[-1].get('t'), max_age_seconds=180):
            with _state_lock:
                _bot_state.update(signal='STALE DATA',detail='No recent IEX bar; skipped order.',last_error=None)
            return
        signal=compute_momentum([float(b['c']) for b in bars])
        with _state_lock:
            _bot_state.update(signal=signal, detail='Real IEX 1-minute bars; 20-bar simple moving average.', last_error=None)
        if signal not in ('LONG','FLAT') or _open_order_exists():
            return
        with _state_lock:
            last=_utc_datetime(_bot_state.get('last_action'))
        if last and (datetime.now(timezone.utc)-last).total_seconds()<MIN_TRADE_GAP_SECONDS:
            return
        acct=_request('/v2/account')
        if acct.get('trading_blocked') or acct.get('account_blocked'):
            raise RuntimeError('Paper account blocked trading')
        positions=_request('/v2/positions')
        owned=next((p for p in positions if p.get('symbol')==BOT_SYMBOL),None)
        # Never add to an existing position or short securities. If there is a
        # position we did not open, do not make assumptions about its owner.
        if owned and owned.get('side')!='long':
            raise RuntimeError('Unexpected short position: bot stopped for safety')
        if signal=='LONG' and owned:
            return
        if signal=='FLAT' and not owned:
            return
        side='buy' if signal=='LONG' else 'sell'
        equity=_float(acct.get('equity')) or 0
        price=_float(bars[-1].get('c')) or 0
        if not (equity>0 and price>0):
            return
        if side=='buy':
            notional=min(equity*MAX_POSITION_FRACTION,MAX_ORDER_DOLLARS)
            quantity=math.floor(notional/price)
        else:
            qty=_float(owned.get('qty')) or 0
            quantity=math.floor(qty)
        if quantity<1:
            return
        timestamp=datetime.now(timezone.utc)
        order_id=f'ql-{timestamp:%Y%m%d%H}-{BOT_SYMBOL.lower()}-{side}'
        order={'symbol':BOT_SYMBOL,'qty':str(quantity),'side':side,'type':'market','time_in_force':'day','client_order_id':order_id}
        _request('/v2/orders',method='POST',body=order)
        with _state_lock:
            _bot_state.update(last_action=timestamp.isoformat(),detail=f'PAPER order: {side.upper()} {quantity} {BOT_SYMBOL}. Check order status for fills.',last_error=None)
            _cached.update(time=0,payload=None)
    except httpx.HTTPStatusError as ex:
        with _state_lock:
            _bot_state.update(last_error=f'Paper API HTTP {ex.response.status_code}; scan skipped.',detail='No further order attempted on this scan.')
    except Exception as ex:
        with _state_lock:
            _bot_state.update(last_error=f'{type(ex).__name__}: {str(ex)[:150]}',detail='Scan halted due to a broker, data or safety issue.')


def _loop() -> None:
    while not _stop.is_set():
        scan_once()
        _stop.wait(BOT_POLL_SECONDS)


def start_worker() -> None:
    global _worker
    if auto_enabled() and (_worker is None or not _worker.is_alive()):
        _stop.clear()
        _worker=threading.Thread(target=_loop,name='quantlab-paper-worker',daemon=True)
        _worker.start()


def stop_worker() -> None:
    _stop.set()
    if _worker is not None:
        _worker.join(timeout=2)
