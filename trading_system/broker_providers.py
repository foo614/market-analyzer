"""
Broker and market-data helpers for monitoring-only workflows.

This module does not place orders. It exposes moomoo market data and eToro
portfolio overlays for Telegram reports.
"""

import os
import socket
import sys
from datetime import datetime
from typing import Dict, Iterable, Optional, Tuple

import pandas as pd
import requests
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (
    ETORO_BASE_URL,
    ETORO_REQUEST_TIMEOUT,
    get_etoro_headers,
    get_futu_default_market,
    get_futu_opend_host,
    get_futu_opend_port,
    etoro_request,
)


MARKET_PREFIXES = {"US", "HK", "SH", "SZ", "SG"}
MAX_INTRADAY_STALENESS_DAYS = 5


def probe_socket(host, port, timeout=1.5):
    sock = None
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass


def to_moomoo_code(symbol, default_market=None):
    if not symbol:
        return None
    raw = str(symbol).strip()
    if not raw:
        return None
    if "." in raw:
        prefix, suffix = raw.split(".", 1)
        prefix = prefix.upper()
        if prefix in MARKET_PREFIXES and suffix:
            return f"{prefix}.{suffix.upper()}"
    market = str(default_market or get_futu_default_market() or "US").strip().upper()
    if market not in MARKET_PREFIXES:
        market = "US"
    return f"{market}.{raw.upper()}"


def _open_quote_context(host=None, port=None):
    from moomoo import OpenQuoteContext

    host = host or get_futu_opend_host()
    port = port or get_futu_opend_port()
    reachable, error = probe_socket(host, port)
    if not reachable:
        raise RuntimeError(f"OpenD not reachable at {host}:{port}: {error}")

    try:
        return OpenQuoteContext(host=host, port=port, ai_type=1)
    except TypeError:
        return OpenQuoteContext(host=host, port=port)


def _moomoo_ktype(interval):
    value = str(interval or "5m").strip().lower()
    if value in {"1m", "k_1m"}:
        return "K_1M"
    if value in {"5m", "k_5m"}:
        return "K_5M"
    if value in {"15m", "k_15m"}:
        return "K_15M"
    if value in {"30m", "k_30m"}:
        return "K_30M"
    if value in {"60m", "1h", "k_60m"}:
        return "K_60M"
    if value in {"1d", "day", "k_day"}:
        return "K_DAY"
    return "K_5M"


def _normalize_moomoo_kline(data):
    if data is None or len(data) == 0:
        return pd.DataFrame()

    def col(*names):
        for name in names:
            if name in data.columns:
                return data[name]
        return None

    frame = pd.DataFrame({
        "Open": col("open", "Open"),
        "High": col("high", "High"),
        "Low": col("low", "Low"),
        "Close": col("close", "Close"),
        "Volume": col("volume", "Volume"),
    })
    frame = frame.apply(pd.to_numeric, errors="coerce")

    time_key = col("time_key", "time", "datetime")
    if time_key is not None:
        frame.index = pd.to_datetime(time_key, errors="coerce")

    return frame.dropna(how="all")


def fetch_moomoo_history(symbol, interval="5m", max_count=200):
    from moomoo import RET_OK

    code = to_moomoo_code(symbol)
    if not code:
        raise ValueError("symbol is required")

    ctx = None
    try:
        ctx = _open_quote_context()
        ret, data, _ = ctx.request_history_kline(
            code,
            ktype=_moomoo_ktype(interval),
            max_count=max_count,
            extended_time=True,
        )
        if ret != RET_OK:
            raise RuntimeError(f"request_history_kline failed for {code}: {ret}")
        frame = _normalize_moomoo_kline(data)
        if frame.empty:
            raise RuntimeError(f"No moomoo kline data returned for {code}")
        return frame
    finally:
        if ctx:
            try:
                ctx.close()
            except Exception:
                pass


def fetch_yfinance_history(symbol, preferred_interval=None):
    default_attempts = [
        ("1d", "1m"),
        ("5d", "5m"),
        ("1mo", "1d"),
    ]
    attempts = []
    preferred = str(preferred_interval or "").strip().lower()
    if preferred == "5m":
        attempts.append(("5d", "5m"))
    elif preferred == "1m":
        attempts.append(("1d", "1m"))
    elif preferred == "1d":
        attempts.append(("1mo", "1d"))

    for attempt in default_attempts:
        if attempt not in attempts:
            attempts.append(attempt)

    last_error = None
    for period, interval in attempts:
        try:
            hist = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=False)
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.droplevel(1)
            hist = hist.dropna(how="all")
            if len(hist) >= 2:
                return hist, period, interval, "yfinance"
        except Exception as exc:
            last_error = exc
    if last_error:
        raise RuntimeError(f"No market data returned for {symbol}: {last_error}")
    raise RuntimeError(f"No market data returned for {symbol}")


def _latest_bar_age_days(frame, now=None):
    if frame is None or frame.empty or len(frame.index) == 0:
        return None

    latest = pd.to_datetime(frame.index[-1], errors="coerce")
    if pd.isna(latest):
        return None

    if getattr(latest, "tzinfo", None):
        current = pd.Timestamp.now(tz=latest.tzinfo) if now is None else pd.Timestamp(now)
        if getattr(current, "tzinfo", None) is None:
            current = current.tz_localize(latest.tzinfo)
    else:
        current = pd.Timestamp(datetime.now()) if now is None else pd.Timestamp(now)
        if getattr(current, "tzinfo", None):
            current = current.tz_convert(None)

    return max(0.0, (current - latest).total_seconds() / 86400.0)


def is_history_stale(frame, max_age_days=MAX_INTRADAY_STALENESS_DAYS, now=None):
    age_days = _latest_bar_age_days(frame, now=now)
    if age_days is None:
        return True
    return age_days > float(max_age_days)


def fetch_history(symbol, provider="auto", interval=None):
    selected = str(provider or "auto").strip().lower()
    interval = str(interval or "5m").strip().lower()
    if selected in {"auto", "moomoo"}:
        try:
            hist = fetch_moomoo_history(symbol, interval=interval)
            if is_history_stale(hist):
                raise RuntimeError(f"Stale moomoo history for {symbol}")
            return hist, "latest", interval, "moomoo"
        except Exception:
            if selected == "moomoo":
                raise
    return fetch_yfinance_history(symbol, preferred_interval=interval)


class EtoroPortfolioProvider:
    def __init__(self, is_real=True):
        self.is_real = is_real
        self.headers = get_etoro_headers(is_real=is_real)
        self._instrument_cache: Dict[str, str] = {}

    def _resolve_symbol(self, instrument_id):
        if instrument_id is None:
            return None
        key = str(instrument_id)
        if key in self._instrument_cache:
            return self._instrument_cache[key]

        try:
            url = (
                f"{ETORO_BASE_URL}/market-data/search"
                f"?instrumentId={instrument_id}&fields=instrumentId,internalSymbolFull,displayname"
            )
            response = requests.get(url, headers=self.headers, timeout=ETORO_REQUEST_TIMEOUT)
            if response.status_code == 200:
                items = response.json().get("items", [])
                if items:
                    raw = items[0].get("internalSymbolFull") or ""
                    symbol = raw.split(".", 1)[0].upper() if raw else None
                    if symbol:
                        self._instrument_cache[key] = symbol
                        return symbol
        except Exception:
            return None
        return None

    def _position_symbol(self, position):
        for key in ("symbol", "Symbol", "internalSymbolFull", "InternalSymbolFull", "instrumentSymbol"):
            raw = position.get(key)
            if raw:
                return str(raw).split(".", 1)[0].upper()
        instrument_id = position.get("instrumentID", position.get("InstrumentID"))
        return self._resolve_symbol(instrument_id)

    def positions(self, symbols: Optional[Iterable[str]] = None):
        wanted = {str(symbol).upper() for symbol in symbols} if symbols else None
        data = etoro_request("/trading/info/portfolio", headers=self.headers)
        if not data:
            return {}

        portfolio = data.get("clientPortfolio", data)
        raw_positions = portfolio.get("positions", portfolio.get("Positions", []))
        result = {}
        for position in raw_positions:
            if not isinstance(position, dict):
                continue
            symbol = self._position_symbol(position)
            if not symbol or (wanted and symbol not in wanted):
                continue

            amount = position.get("amount", position.get("Amount"))
            pnl = (
                position.get("pnl")
                or position.get("PnL")
                or position.get("netProfit")
                or position.get("NetProfit")
                or position.get("profitAndLoss")
            )
            result[symbol] = {
                "has_position": True,
                "amount": _to_float(amount),
                "pnl": _to_float(pnl),
                "is_buy": position.get("isBuy", position.get("IsBuy")),
                "source": "etoro_real" if self.is_real else "etoro_demo",
            }
        return result


def _to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None
