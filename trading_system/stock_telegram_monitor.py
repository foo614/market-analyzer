"""
Multi-stock Telegram analysis monitor.

Standalone alert-only monitor. It prefers moomoo market data when OpenD is
reachable, falls back to yfinance, overlays eToro real portfolio context, and
does not import or start ExecutionAgent.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

import pandas as pd
import pytz
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from broker_providers import EtoroPortfolioProvider, fetch_history
from config import system_path
from indicators import calculate_atr_scalar, calculate_obv_from_lists, calculate_rsi_scalar
from signal_model import category_trade_action, normalize_signal_category
from telegram_notifier import send_telegram_message


DEFAULT_SYMBOLS = ["SPCX", "TSLA", "TQQQ", "SOXL"]
STATE_FILE = system_path("stock_monitor_state.json")
LOG_FILE = system_path("logs", "stock_monitor.log")
ET = pytz.timezone("US/Eastern")

POSITIVE_WORDS = {
    "beat",
    "beats",
    "jump",
    "jumps",
    "surge",
    "surges",
    "rally",
    "rallies",
    "gain",
    "gains",
    "record",
    "upgrade",
    "upgrades",
    "raise",
    "raises",
    "bullish",
    "growth",
    "approval",
    "delivery",
    "momentum",
}
NEGATIVE_WORDS = {
    "miss",
    "misses",
    "fall",
    "falls",
    "drop",
    "drops",
    "cut",
    "cuts",
    "lawsuit",
    "probe",
    "investigation",
    "downgrade",
    "downgrades",
    "selloff",
    "weak",
    "risk",
    "loss",
    "losses",
    "yield",
    "yields",
}


def _log(message):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_state(state):
    tmp_path = f"{STATE_FILE}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp_path, STATE_FILE)


def _normalize_history(hist):
    if isinstance(hist.columns, pd.MultiIndex):
        hist.columns = hist.columns.droplevel(1)
    return hist


def _quote_rows(hist):
    quotes = []
    for _, row in hist.iterrows():
        try:
            quotes.append({
                "close": float(row["Close"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "volume": float(row["Volume"]),
            })
        except Exception:
            continue
    return quotes


def _safe_rsi(prices):
    if len(prices) < 15:
        return 50.0
    rsi = calculate_rsi_scalar(prices, 14)
    return float(rsi) if rsi is not None else 50.0


def _calculate_vwap(quotes):
    total_volume = sum(max(q["volume"], 0) for q in quotes)
    if total_volume <= 0:
        return sum(q["close"] for q in quotes) / len(quotes)
    return sum(q["close"] * max(q["volume"], 0) for q in quotes) / total_volume


def _volume_ratio(quotes, lookback=5):
    if len(quotes) < 2:
        return 0.0
    previous = [max(q["volume"], 0) for q in quotes[-(lookback + 1):-1]]
    previous = [v for v in previous if v > 0]
    latest = max(quotes[-1]["volume"], 0)
    if not previous or latest <= 0:
        return 0.0
    return latest / (sum(previous) / len(previous))


def _extract_headline(item):
    content = item.get("content", item) if isinstance(item, dict) else {}
    return (content.get("title") or item.get("title") or "").strip()


def _fetch_headlines(symbol, limit=5):
    try:
        items = yf.Ticker(symbol).news or []
        return [headline for headline in (_extract_headline(item) for item in items[:limit]) if headline]
    except Exception:
        return []


def _classify_headline_sentiment(symbol, headlines):
    cleaned = [str(headline).strip() for headline in headlines if str(headline).strip()]
    if not cleaned:
        return {"sentiment": "Neutral", "reason": "No recent headlines found."}

    score = 0
    text = " ".join(cleaned).lower()
    words = text.replace("-", " ").replace("/", " ").split()
    for word in words:
        token = word.strip(".,:;!?()[]{}'\"")
        if token in POSITIVE_WORDS:
            score += 1
        if token in NEGATIVE_WORDS:
            score -= 1

    if score > 0:
        return {"sentiment": "Bullish", "reason": f"{symbol} headlines lean bullish from recent keyword flow."}
    if score < 0:
        return {"sentiment": "Bearish", "reason": f"{symbol} headlines lean bearish from recent keyword flow."}
    return {"sentiment": "Neutral", "reason": "Headlines are mixed or not directional."}


def _fetch_sentiments(symbols):
    result = {}
    for symbol in symbols:
        result[symbol] = _classify_headline_sentiment(symbol, _fetch_headlines(symbol))
        time.sleep(0.2)
    return result


def _fetch_positions(symbols):
    try:
        provider = EtoroPortfolioProvider(is_real=True)
        return provider.positions(symbols)
    except Exception as exc:
        _log(f"eToro position overlay unavailable: {exc}")
        return {}


def _empty_position():
    return {"has_position": False}


def _build_symbol_analysis(
    symbol,
    hist,
    period="1d",
    interval="1m",
    source="yfinance",
    sentiment=None,
    position=None,
):
    symbol = str(symbol).upper()
    hist = _normalize_history(hist).dropna(how="all")
    quotes = _quote_rows(hist)

    if not quotes:
        raise RuntimeError(f"No usable price data returned for {symbol}")

    latest_bar_ts = str(hist.index[-1]) if len(hist.index) else ""
    prices = [q["close"] for q in quotes]
    volumes = [q["volume"] for q in quotes]
    current_price = prices[-1]
    open_price = quotes[0]["close"]
    prev_price = prices[-2] if len(prices) > 1 else current_price
    change_pct = ((current_price - open_price) / open_price) * 100 if open_price else 0.0
    sma20 = sum(prices[-20:]) / 20 if len(prices) >= 20 else None
    sma50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else None
    rsi = _safe_rsi(prices)
    atr = calculate_atr_scalar(quotes, 14)
    vwap = _calculate_vwap(quotes)
    volume_ratio = _volume_ratio(quotes)
    session_high = max(q["high"] for q in quotes)
    session_low = min(q["low"] for q in quotes)
    prior_high = max(q["high"] for q in quotes[:-1]) if len(quotes) > 1 else session_high
    prior_low = min(q["low"] for q in quotes[:-1]) if len(quotes) > 1 else session_low

    obv = calculate_obv_from_lists(prices, volumes)
    recent_obv = sum(obv[-5:]) / 5 if len(obv) >= 10 else 0
    prev_obv = sum(obv[-10:-5]) / 5 if len(obv) >= 10 else 0
    nonzero_volume_count = len([v for v in volumes if v > 0])
    required_volume_bars = min(10, max(2, len(volumes) // 3))
    volume_data_ok = nonzero_volume_count >= required_volume_bars
    data_confidence = "high" if source == "moomoo" else "medium"
    if not volume_data_ok:
        data_confidence = "low"
    has_obv_signal = len(obv) >= 10 and nonzero_volume_count >= 10
    obv_status = "Accumulating" if has_obv_signal and recent_obv > prev_obv else (
        "Distributing" if has_obv_signal else "Unavailable"
    )
    trend50 = "Bullish" if sma50 and current_price > sma50 else ("Bearish" if sma50 else "Unknown")

    stop_watch = current_price - (atr * 2) if atr else None
    take_profit_watch = current_price + (atr * 3) if atr else None

    has_enough_signal_data = len(quotes) >= 5
    sentiment = sentiment or {"sentiment": "Neutral", "reason": "Sentiment unavailable."}
    sentiment_value = sentiment.get("sentiment", "Neutral")

    volume_rebound = volume_ratio >= 3.0 and current_price > prev_price and current_price >= vwap and rsi < 70
    breakout = current_price >= prior_high and current_price >= vwap
    vwap_breakdown = volume_data_ok and current_price < vwap and current_price <= prev_price
    support_break = current_price <= prior_low

    if not has_enough_signal_data:
        signal = "HOLD / WATCH"
        trigger = "insufficient_data"
        rationale = f"Insufficient intraday history ({len(quotes)} bars available). Monitoring continues."
        actionable = False
    elif volume_rebound:
        signal = "ACCUMULATE WATCH"
        trigger = "volume_rebound"
        rationale = f"Volume rebound detected ({volume_ratio:.1f}x recent average) while price holds above VWAP."
        actionable = True
    elif breakout:
        signal = "TAKE PROFIT WATCH"
        trigger = "breakout"
        rationale = f"Price is testing or breaking the prior intraday high (${prior_high:.2f}). Consider trimming or tightening stops."
        actionable = True
    elif support_break or vwap_breakdown:
        signal = "STOP LOSS WATCH"
        trigger = "vwap_breakdown" if vwap_breakdown else "support_break"
        rationale = f"Price is below VWAP (${vwap:.2f}) and momentum is weakening."
        actionable = True
    elif rsi > 80:
        signal = "TAKE PROFIT"
        trigger = "rsi_overbought"
        rationale = "Extreme overbought RSI. Lock gains or tighten stop."
        actionable = True
    elif rsi > 70 and obv_status == "Distributing":
        signal = "TAKE PROFIT"
        trigger = "rsi_distribution"
        rationale = "Overbought RSI with distribution pressure."
        actionable = True
    elif trend50 == "Bearish" and obv_status == "Distributing":
        signal = "STOP LOSS WATCH"
        trigger = "daily_trend_break"
        rationale = "Price is below SMA50 and OBV shows distribution."
        actionable = True
    elif rsi < 30 and obv_status == "Accumulating":
        signal = "BUY"
        trigger = "oversold_accumulation"
        rationale = "Oversold RSI with accumulation support."
        actionable = True
    elif rsi < 40 and obv_status == "Accumulating" and trend50 != "Bearish":
        signal = "ACCUMULATE"
        trigger = "rsi_accumulation"
        rationale = "RSI cooled while OBV still shows accumulation."
        actionable = True
    else:
        signal = "HOLD / WATCH"
        trigger = "hold_watch"
        rationale = "No strong TP, SL, or accumulate trigger from RSI/OBV/SMA/VWAP."
        actionable = False

    if signal in {"BUY", "ACCUMULATE", "ACCUMULATE WATCH"} and sentiment_value == "Bearish":
        signal = "HOLD / WATCH"
        trigger = "bearish_sentiment_veto"
        rationale = "Technical buy/accumulate setup is paused because headline sentiment is bearish."
        actionable = False

    signal_category = normalize_signal_category(signal)
    return {
        "symbol": symbol,
        "signal": signal,
        "signalCategory": signal_category,
        "tradeAction": category_trade_action(signal_category),
        "actionable": actionable,
        "price": current_price,
        "change_pct": change_pct,
        "rsi": rsi,
        "vwap": vwap,
        "volume_ratio": volume_ratio,
        "session_high": session_high,
        "session_low": session_low,
        "prior_high": prior_high,
        "prior_low": prior_low,
        "obv_status": obv_status,
        "sma20": sma20,
        "sma50": sma50,
        "trend50": trend50,
        "atr": atr,
        "stop_watch": stop_watch,
        "take_profit_watch": take_profit_watch,
        "rationale": rationale,
        "trigger": trigger,
        "bars": len(quotes),
        "nonzero_volume_count": nonzero_volume_count,
        "period": period,
        "interval": interval,
        "source": source,
        "data_confidence": data_confidence,
        "volume_data_ok": volume_data_ok,
        "latest_bar_ts": latest_bar_ts,
        "sentiment": sentiment_value,
        "sentiment_reason": sentiment.get("reason", "Sentiment unavailable."),
        "position": position or _empty_position(),
    }


def _build_error_analysis(symbol, error):
    signal_category = normalize_signal_category("HOLD")
    return {
        "symbol": str(symbol).upper(),
        "signal": "DATA ERROR",
        "signalCategory": signal_category,
        "tradeAction": category_trade_action(signal_category),
        "trigger": "data_error",
        "period": "N/A",
        "interval": "N/A",
        "source": "N/A",
        "price": 0.0,
        "change_pct": 0.0,
        "vwap": 0.0,
        "rsi": 0.0,
        "volume_ratio": 0.0,
        "obv_status": "Unavailable",
        "data_confidence": "low",
        "volume_data_ok": False,
        "sentiment": "Neutral",
        "sentiment_reason": "Skipped because market data failed.",
        "position": _empty_position(),
        "rationale": str(error),
    }


def _position_line(position):
    if not position or not position.get("has_position"):
        return "ETORO: `No real position detected or portfolio unavailable`"

    parts = ["ETORO: `Position detected`"]
    amount = position.get("amount")
    pnl = position.get("pnl")
    if amount is not None:
        parts.append(f"amount `${amount:.2f}`")
    if pnl is not None:
        parts.append(f"pnl `${pnl:+.2f}`")
    return " | ".join(parts)


def _format_report(analyses, reason="scheduled report"):
    generated = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        "**MULTI-STOCK ANALYZE REPORT**",
        f"Reason: `{reason}`",
        f"Generated: `{generated}`",
        "",
    ]

    for analysis in analyses:
        lines.extend([
            f"**{analysis['symbol']}**",
            f"ACTION: `{analysis['signal']} {analysis['symbol']}`",
            f"TRIGGER: `{analysis['trigger']}`",
            f"DATA: `{analysis['source']} {analysis['period']}/{analysis['interval']}` | CONFIDENCE: `{analysis.get('data_confidence', 'medium')}`",
            f"PRICE: `${analysis['price']:.2f}` ({analysis['change_pct']:+.2f}% from session open)",
            f"VWAP: `${analysis['vwap']:.2f}`",
            f"RSI(14): `{analysis['rsi']:.1f}`",
            f"VOLUME: `{analysis['volume_ratio']:.1f}x recent average`",
            f"OBV: `{analysis['obv_status']}`",
            f"SENTIMENT: `{analysis['sentiment']}` - {analysis['sentiment_reason']}",
            _position_line(analysis.get("position")),
            f"READ: `{analysis['rationale']}`",
        ])
        if analysis.get("stop_watch") is not None:
            lines.append(f"SL WATCH: `${analysis['stop_watch']:.2f}`")
        if analysis.get("take_profit_watch") is not None:
            lines.append(f"TP WATCH: `${analysis['take_profit_watch']:.2f}`")
        lines.append("")

    lines.append("No order was placed. Manual confirmation only.")
    return "\n".join(lines).strip()


def _is_actionable_signal(signal):
    return str(signal or "").upper() not in {"", "HOLD", "HOLD / WATCH", "DATA ERROR"}


def _position_flag(analysis):
    position = analysis.get("position") or {}
    return bool(position.get("has_position"))


def _should_send_report(analyses, state, force_send=False, heartbeat_hours=4, now=None):
    now = time.time() if now is None else float(now)
    if force_send:
        return True, "manual/startup report"

    last_sent = float(state.get("last_sent_ts", 0) or 0)
    if (now - last_sent) >= heartbeat_hours * 3600:
        return True, "monitor heartbeat"

    last_signals = state.get("last_signals", {}) or {}
    last_triggers = state.get("last_triggers", {}) or {}
    last_positions = state.get("last_positions", {}) or {}

    for analysis in analyses:
        symbol = analysis.get("symbol")
        signal = analysis.get("signal")
        trigger = analysis.get("trigger")
        has_position = _position_flag(analysis)

        if symbol in last_positions and bool(last_positions.get(symbol)) != has_position:
            return True, f"position change {symbol}"

        signal_changed = last_signals.get(symbol) != signal
        trigger_changed = last_triggers.get(symbol) != trigger
        if _is_actionable_signal(signal) and (signal_changed or trigger_changed):
            return True, f"signal change {symbol}"

    return False, "quiet"


def _analyze_symbols(symbols, provider="auto"):
    symbols = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
    sentiments = _fetch_sentiments(symbols)
    positions = _fetch_positions(symbols)
    analyses = []

    for symbol in symbols:
        try:
            hist, period, interval, source = fetch_history(symbol, provider=provider)
            analyses.append(_build_symbol_analysis(
                symbol,
                hist,
                period=period,
                interval=interval,
                source=source,
                sentiment=sentiments.get(symbol),
                position=positions.get(symbol, _empty_position()),
            ))
        except Exception as exc:
            analyses.append(_build_error_analysis(symbol, exc))
    return analyses


def run_check(symbols=None, provider="auto", reason="scheduled report", force_send=False):
    symbols = symbols or DEFAULT_SYMBOLS
    analyses = _analyze_symbols(symbols, provider=provider)
    state = _load_state()
    should_send, send_reason = _should_send_report(analyses, state, force_send=force_send)
    sent = False

    if should_send:
        message = _format_report(analyses, reason=send_reason if reason == "scheduled report" else reason)
        sent = send_telegram_message(message, direct_send=True)

    state["last_check_ts"] = time.time()
    if sent:
        state["last_sent_ts"] = time.time()
    if sent or not should_send:
        state["last_symbols"] = [analysis["symbol"] for analysis in analyses]
        state["last_signals"] = {analysis["symbol"]: analysis["signal"] for analysis in analyses}
        state["last_triggers"] = {analysis["symbol"]: analysis["trigger"] for analysis in analyses}
        state["last_positions"] = {analysis["symbol"]: _position_flag(analysis) for analysis in analyses}
    _save_state(state)

    summary = ", ".join(f"{a['symbol']}={a['signal']}" for a in analyses)
    _log(f"report provider={provider} sent={sent} reason={send_reason} {summary}")
    return sent


def _split_arg(value):
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def main():
    parser = argparse.ArgumentParser(description="Send multi-stock analysis reports to Telegram.")
    parser.add_argument("--interval", type=int, default=300, help="Polling interval in seconds.")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="Comma-separated symbols.")
    parser.add_argument("--provider", default="auto", choices=["auto", "moomoo", "yfinance"], help="Market data provider.")
    parser.add_argument("--once", action="store_true", help="Run one check then exit.")
    parser.add_argument("--force-send", action="store_true", help="Alias for one immediate scheduled report.")
    args = parser.parse_args()

    reason = "manual/startup report" if args.force_send else "scheduled report"
    while True:
        try:
            run_check(symbols=_split_arg(args.symbols), provider=args.provider, reason=reason, force_send=args.force_send)
        except Exception as exc:
            _log(f"ERROR {exc}")

        if args.once:
            return
        reason = "scheduled report"
        time.sleep(max(args.interval, 60))


if __name__ == "__main__":
    main()
