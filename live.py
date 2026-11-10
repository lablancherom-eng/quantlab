"""QuantLab V4: multi-asset Alpaca PAPER market observer and optional executor.

WARNING: Research prototype. No live-money trading endpoint. Paper orders are
OFF by default. Do not use with live-money credentials or production capital.

SPY, QQQ, IWM are equity ETFs; USO provides WTI oil-futures-linked exposure.
"""
from __future__ import annotations

import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

PAPER_HOST = "https://paper-api.alpaca.markets"
MARKET_DATA_HOST = "https://data.alpaca.markets"
SYMBOLS = ("SPY", "QQQ", "IWM", "USO")
DEFAULT_SYMBOLS = SYMBOLS  # compatibility with earlier versions
BOT_SYMBOL = "SPY"  # compatibility only; strategy now evaluates SYMBOLS
BOT_POLL_SECONDS = 60
MIN_BARS = 20
MAX_POSITION_DOLLARS = 1000.0
MAX_TOTAL_EXPOSURE_DOLLARS = 15000.0
MAX_POSITION_FRACTION = 0.01
MAX_ORDER_DOLLARS = MAX_POSITION_DOLLARS
MAX_ORDERS_PER_DAY = 3
CLIENT_PREFIX = "q4-"

_state_lock = threading.RLock()
_scan_lock = threading.Lock()
_stop = threading.Event()
_worker: threading.Thread | None = None
_cached: dict[str, Any] = {"time": 0.0, "payload": None}
_bot_state: dict[str, Any] = {
    "last_scan": None, "last_action": None, "signal": "NOT STARTED",
    "detail": "Waiting for the multi-asset observer.", "last_error": None,
    "signals": {s: "NOT STARTED" for s in SYMBOLS},
}


def configured() -> bool:
    return bool(os.getenv("ALPACA_PAPER_KEY_ID") and os.getenv("ALPACA_PAPER_SECRET_KEY"))


def auto_enabled() -> bool:
    return configured() and os.getenv("PAPER_AUTO_TRADE", "false").lower() == "true"


def _auth() -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": os.environ["ALPACA_PAPER_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["ALPACA_PAPER_SECRET_KEY"],
    }


def _request(path: str, *, data: bool = False, params: dict | None = None,
             method: str = "GET", body: dict | None = None) -> Any:
    if not path.startswith("/v2/"):
        raise ValueError("Unexpected Alpaca path")
    if method != "GET" and not (method == "POST" and not data and path == "/v2/orders"):
        raise ValueError("Unsupported API action")
    host = MARKET_DATA_HOST if data else PAPER_HOST
    with httpx.Client(timeout=10.0, follow_redirects=False) as client:
        response = client.request(method, host + path, headers=_auth(), params=params, json=body)
        response.raise_for_status()
        return response.json()


def _float(value: Any) -> float | None:
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _utc_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def is_fresh(value: str | None, *, max_age_seconds: int = 180) -> bool:
    d = _utc_datetime(value)
    return d is not None and timedelta(seconds=-15) <= datetime.now(timezone.utc) - d <= timedelta(seconds=max_age_seconds)


def parse_snapshot(snapshot: dict[str, Any], symbol: str) -> dict[str, Any]:
    trade, quote = snapshot.get("latestTrade") or {}, snapshot.get("latestQuote") or {}
    price, observed = _float(trade.get("p")), trade.get("t")
    return {
        "symbol": symbol, "price": price if observed else None,
        "observed_at": observed if price is not None else None,
        "bid": _float(quote.get("bp")), "ask": _float(quote.get("ap")),
        "source": "IEX REAL-TIME (LIMITED EXCHANGE COVERAGE)" if price is not None and observed else "IEX / NO TRADE",
    }


def _position_summary(obj: dict[str, Any]) -> dict[str, Any]:
    return {k: obj.get(k) for k in (
        "symbol", "side", "qty", "avg_entry_price", "current_price", "market_value", "unrealized_pl", "unrealized_plpc"
    )}


def _order_summary(obj: dict[str, Any]) -> dict[str, Any]:
    return {k: obj.get(k) for k in (
        "symbol", "side", "qty", "filled_qty", "status", "filled_avg_price", "submitted_at", "filled_at", "client_order_id"
    )}


def get_public_status() -> dict[str, Any]:
    """Maintain the exact shape expected by the existing QuantLab dashboard."""
    now = datetime.now(timezone.utc).isoformat()
    with _state_lock:
        bot = {**_bot_state, "signals": dict(_bot_state["signals"])}
        cached = _cached["payload"]
        if configured() and cached is not None and time.monotonic() - _cached["time"] < 10:
            return {**cached, "bot": bot, "auto_trading": auto_enabled()}
    empty = {"updated_at": now, "capital_type": "PAPER ONLY", "currency": "USD", "market": None,
             "account": None, "quotes": [], "positions": [], "orders": [], "equity_history": [], "bot": bot}
    if not configured():
        return {**empty, "mode": "NOT CONNECTED", "connected": False, "configured": False,
                "auto_trading": False, "message": "Configure Alpaca PAPER keys on the server."}
    try:
        account = _request("/v2/account")
        clock = _request("/v2/clock")
        positions = _request("/v2/positions")
        orders = _request("/v2/orders", params={"status": "all", "limit": 12, "direction": "desc"})
        snapshots = _request("/v2/stocks/snapshots", data=True,
                             params={"symbols": ",".join(SYMBOLS), "feed": "iex"})
        try:
            hist = _request("/v2/account/portfolio/history", params={"period": "1M", "timeframe": "1D", "extended_hours": "false"})
            equity_history = [
                {"date": datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat(), "equity": float(v)}
                for t, v in zip(hist.get("timestamp", []), hist.get("equity", []))
                if v is not None and _float(v) is not None and float(v) > 0
            ]
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            equity_history = []
        quotes = [parse_snapshot(snapshots.get(s) or {}, s) for s in SYMBOLS]
        for q in quotes:
            q["fresh"] = is_fresh(q["observed_at"]) if clock.get("is_open") else False
        payload = {
            **empty, "mode": "LIVE PAPER", "connected": True, "configured": True,
            "auto_trading": auto_enabled(), "updated_at": datetime.now(timezone.utc).isoformat(),
            "market": {k: clock.get(k) for k in ("is_open", "timestamp", "next_open", "next_close")},
            "account": {k: _float(account.get(k)) for k in ("equity", "cash", "buying_power", "portfolio_value", "last_equity")},
            "quotes": quotes, "positions": [_position_summary(p) for p in positions],
            "orders": [_order_summary(o) for o in orders], "equity_history": equity_history,
            "message": "Alpaca PAPER account and IEX trade data; paper fills are simulated.",
        }
        with _state_lock:
            _cached.update(time=time.monotonic(), payload=payload)
        return payload
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as ex:
        return {**empty, "mode": "CONNECTION ERROR", "connected": False, "configured": True,
                "auto_trading": auto_enabled(), "message": f"Alpaca temporarily unavailable ({type(ex).__name__})."}


def compute_momentum(prices: list[float]) -> str:
    """20 preceding minute-bar SMA with 0.1% no-trade band; demo, not alpha."""
    if len(prices) < MIN_BARS + 1 or any(not math.isfinite(p) or p <= 0 for p in prices[-(MIN_BARS + 1):]):
        return "INSUFFICIENT DATA"
    baseline = sum(prices[-(MIN_BARS + 1):-1]) / MIN_BARS
    if prices[-1] > baseline * 1.001:
        return "LONG"
    if prices[-1] < baseline * .999:
        return "FLAT"
    return "HOLD"


def _bar_data(symbol: str) -> list[dict[str, Any]]:
    start = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    response = _request(f"/v2/stocks/{symbol}/bars", data=True,
                        params={"timeframe": "1Min", "start": start, "limit": 600, "feed": "iex", "sort": "asc"})
    return response.get("bars", [])


def _bot_orders() -> list[dict[str, Any]]:
    """Broker orders are the durable audit; fail closed if a full page might be missing."""
    orders = _request("/v2/orders", params={"status": "all", "limit": 500, "direction": "desc"})
    if len(orders) >= 500:
        raise RuntimeError("Order history full; pagination required before trading")
    return orders


def _net_filled_bot_qty(symbol: str, orders: list[dict[str, Any]]) -> float:
    qty = 0.0
    for order in orders:
        if order.get("symbol") != symbol or not str(order.get("client_order_id") or "").startswith(CLIENT_PREFIX):
            continue
        filled = _float(order.get("filled_qty")) or 0.0
        qty += filled if order.get("side") == "buy" else -filled if order.get("side") == "sell" else 0
    return qty


def _check_order_safe(symbol: str, signal: str, positions: list[dict[str, Any]],
                      orders: list[dict[str, Any]], acct: dict[str, Any], price: float) -> tuple[str, int] | None:
    """Fail closed for unknown inventory or order history; return (side, qty)."""
    if signal not in ("LONG", "FLAT"):
        return None
    if acct.get("trading_blocked") or acct.get("account_blocked"):
        return None
    today = datetime.now(timezone.utc).date()
    v4 = [o for o in orders if str(o.get("client_order_id") or "").startswith(CLIENT_PREFIX)]
    active_status = {"new", "accepted", "pending_new", "partially_filled", "accepted_for_bidding", "pending_cancel", "pending_replace"}
    if any(o.get("symbol") == symbol and o.get("status") in active_status for o in orders):
        return None
    todays = [o for o in v4 if (_utc_datetime(o.get("submitted_at")) or datetime(1970, 1, 1, tzinfo=timezone.utc)).date() == today]
    if len(todays) >= MAX_ORDERS_PER_DAY:
        return None
    # At most one order (any status) per symbol per UTC calendar day.
    if any(o.get("symbol") == symbol for o in todays):
        return None
    last = [_utc_datetime(o.get("submitted_at")) for o in v4 if o.get("symbol") == symbol]
    if any(dt is not None and (datetime.now(timezone.utc) - dt).total_seconds() < 3600 for dt in last):
        return None
    position = next((p for p in positions if p.get("symbol") == symbol), None)
    net_bot_qty = _net_filled_bot_qty(symbol, v4)
    if position:
        if position.get("side") != "long":
            return None
        owned_qty = _float(position.get("qty")) or 0.0
        # Avoid touching manually opened SPY or legacy V3 inventory.
        if abs(net_bot_qty - owned_qty) > 1e-6:
            return None
        if signal == "FLAT":
            quantity = math.floor(owned_qty)
            return ("sell", quantity) if quantity >= 1 else None
        return None
    if net_bot_qty > 1e-6:
        return None  # inconsistent broker inventory
    if signal != "LONG":
        return None
    equity, cash = _float(acct.get("equity")), _float(acct.get("cash"))
    if not (equity and equity > 0 and cash and cash > 0 and price > 0):
        return None
    # Exposure cap counts *all* long positions, even manual ones.
    used_exposure = sum(max(0.0, _float(p.get("market_value")) or 0) for p in positions)
    budget = min(MAX_POSITION_DOLLARS, equity * MAX_POSITION_FRACTION,
                 MAX_TOTAL_EXPOSURE_DOLLARS - used_exposure, cash)
    quantity = math.floor(max(0, budget) / price)
    return ("buy", quantity) if quantity >= 1 else None


def scan_once() -> None:
    """Observe every configured symbol; POST only if explicitly enabled."""
    if not _scan_lock.acquire(blocking=False):
        return
    try:
        with _state_lock:
            _bot_state["last_scan"] = datetime.now(timezone.utc).isoformat()
        if not configured():
            with _state_lock:
                _bot_state.update(signal="DISCONNECTED", detail="Paper credentials missing", last_error=None)
            return
        clock = _request("/v2/clock")
        if not clock.get("is_open"):
            with _state_lock:
                _bot_state.update(signal="MARKET CLOSED", detail="Regular session closed; no orders sent", last_error=None)
            return
        signals: dict[str, str] = {}
        prices: dict[str, float] = {}
        for symbol in SYMBOLS:
            try:
                bars = _bar_data(symbol)
                if not bars or not is_fresh(bars[-1].get("t"), max_age_seconds=180):
                    signals[symbol] = "STALE DATA"
                else:
                    values = [float(b["c"]) for b in bars]
                    signals[symbol] = compute_momentum(values)
                    prices[symbol] = values[-1]
            except (ValueError, KeyError, TypeError, httpx.HTTPError):
                signals[symbol] = "DATA ERROR"
        with _state_lock:
            _bot_state.update(signals=signals, signal=" / ".join(f"{s}:{signals[s]}" for s in SYMBOLS),
                              detail="4-symbol equity + oil ETF momentum scan. Orders disabled." if not auto_enabled() else "3-ETF momentum scan; PAPER orders enabled.",
                              last_error=None)
        if not auto_enabled():
            return
        # Broker account/order state loaded once per scan. Do not trade on partial reads.
        acct = _request("/v2/account")
        positions = _request("/v2/positions")
        orders = _bot_orders()
        for symbol in SYMBOLS:
            if not auto_enabled():
                return
            signal, price = signals[symbol], prices.get(symbol)
            if price is None:
                continue
            decision = _check_order_safe(symbol, signal, positions, orders, acct, price)
            if decision is None:
                continue
            side, qty = decision
            # Fixed idempotency ID, one order per symbol/day across worker restarts.
            today = datetime.now(timezone.utc).strftime("%Y%m%d")
            order_id = f"{CLIENT_PREFIX}{today}-{symbol.lower()}"
            order = {"symbol": symbol, "qty": str(qty), "side": side, "type": "market",
                     "time_in_force": "day", "client_order_id": order_id}
            # Intentionally limit to ONE paper order per scan; recheck broker next minute.
            _request("/v2/orders", method="POST", body=order)
            with _state_lock:
                _bot_state.update(last_action=datetime.now(timezone.utc).isoformat(),
                                  detail=f"PAPER {side.upper()} {qty} {symbol} submitted; verify broker status.")
                _cached.update(time=0.0, payload=None)
            return
    except httpx.HTTPStatusError as ex:
        with _state_lock:
            _bot_state.update(last_error=f"Alpaca HTTP {ex.response.status_code}", detail="Scan stopped safely")
    except Exception as ex:
        with _state_lock:
            _bot_state.update(last_error=f"{type(ex).__name__}: {str(ex)[:140]}", detail="Scan stopped safely")
    finally:
        _scan_lock.release()


def _loop() -> None:
    while not _stop.is_set():
        scan_once()
        _stop.wait(BOT_POLL_SECONDS)


def start_worker() -> None:
    global _worker
    if configured() and (_worker is None or not _worker.is_alive()):
        _stop.clear()
        _worker = threading.Thread(target=_loop, name="quantlab-paper-multiasset", daemon=True)
        _worker.start()


def stop_worker() -> None:
    _stop.set()
    if _worker is not None:
        _worker.join(timeout=2)
