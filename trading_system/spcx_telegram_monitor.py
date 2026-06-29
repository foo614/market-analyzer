"""
SPCX Telegram monitor.

Standalone alert-only monitor. It does not import or start ExecutionAgent and
does not place orders.
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
from indicators import calculate_atr_scalar, calculate_obv_from_lists, calculate_rsi_scalar
from telegram_notifier import send_telegram_message
from config import system_path
from signal_model import category_trade_action, normalize_signal_category


SYMBOL = "SPCX"
STATE_FILE = system_path("spcx_monitor_state.json")
LOG_FILE = system_path("logs", "spcx_monitor.log")
ET = pytz.timezone("US/Eastern")
DEFAULT_COOLDOWN_MINUTES = 45


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
                return json.load(f)
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


def _download_history():
    attempts = [
        ("1d", "1m"),
        ("5d", "5m"),
        ("1mo", "1d"),
    ]
    for period, interval in attempts:
        hist = yf.download(SYMBOL, period=period, interval=interval, progress=False, auto_adjust=False)
        if not hist.empty:
            hist = _normalize_history(hist).dropna(how="all")
            if len(hist) >= 2:
                return hist, period, interval
    raise RuntimeError(f"No market data returned for {SYMBOL}")


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


def _build_intraday_analysis(hist, period="1d", interval="1m"):
    hist = _normalize_history(hist).dropna(how="all")
    quotes = _quote_rows(hist)

    if not quotes:
        raise RuntimeError(f"No usable price data returned for {SYMBOL}")

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
    has_obv_signal = len(obv) >= 10 and nonzero_volume_count >= 10
    obv_status = "Accumulating" if has_obv_signal and recent_obv > prev_obv else (
        "Distributing" if has_obv_signal else "Unavailable"
    )
    trend50 = "Bullish" if sma50 and current_price > sma50 else ("Bearish" if sma50 else "Unknown")

    stop_watch = current_price - (atr * 2) if atr else None
    take_profit_watch = current_price + (atr * 3) if atr else None

    has_enough_signal_data = len(quotes) >= 5

    volume_rebound = volume_ratio >= 3.0 and current_price > prev_price and current_price >= vwap and rsi < 70
    breakout = current_price >= prior_high and current_price >= vwap
    vwap_breakdown = current_price < vwap and current_price <= prev_price
    support_break = current_price <= prior_low

    if not has_enough_signal_data:
        signal = "HOLD / WATCH"
        trigger = "insufficient_data"
        rationale = f"Insufficient intraday history from Yahoo Finance ({len(quotes)} bars available). Monitoring continues."
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
        rationale = "No strong TP, SL, or accumulate trigger from daily RSI/OBV/SMA."
        actionable = False

    signal_category = normalize_signal_category(signal)
    return {
        "symbol": SYMBOL,
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
        "latest_bar_ts": latest_bar_ts,
    }


def _analyze():
    hist, period, interval = _download_history()
    return _build_intraday_analysis(hist, period=period, interval=interval)


def _format_message(analysis, reason):
    lines = [
        "**CLAWDBOT SPCX MONITOR**",
        f"Reason: `{reason}`",
        f"Generated: `{datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S %Z')}`",
        "",
        f"ACTION: `{analysis['signal']} {SYMBOL}`",
        f"TRIGGER: `{analysis['trigger']}`",
        f"TIMEFRAME: `{analysis['period']}/{analysis['interval']}`",
        f"PRICE: `${analysis['price']:.2f}` ({analysis['change_pct']:+.2f}% from session open)",
        f"RANGE: `${analysis['session_low']:.2f} - ${analysis['session_high']:.2f}`",
        f"VWAP: `${analysis['vwap']:.2f}`",
        f"RSI(14): `{analysis['rsi']:.1f}`",
        f"VOLUME SPIKE: `{analysis['volume_ratio']:.1f}x recent average`",
        f"OBV TREND: `{analysis['obv_status']}`",
        f"SMA20: `${analysis['sma20']:.2f}`" if analysis["sma20"] else "SMA20: `N/A`",
        f"SMA50: `${analysis['sma50']:.2f}` ({analysis['trend50']})" if analysis["sma50"] else "SMA50: `N/A`",
        f"ATR(14): `${analysis['atr']:.2f}`",
        f"DATA: `{analysis['bars']} bars, {analysis['nonzero_volume_count']} non-zero volume bars`",
    ]
    if analysis["stop_watch"] is not None:
        lines.append(f"SL WATCH: `${analysis['stop_watch']:.2f}`")
    if analysis["take_profit_watch"] is not None:
        lines.append(f"TP WATCH: `${analysis['take_profit_watch']:.2f}`")
    lines.extend([
        "",
        "Rationale:",
        f"`{analysis['rationale']}`",
        "",
        "No order was placed. Manual confirmation only.",
    ])
    return "\n".join(lines)


def _should_send_alert(analysis, state, cooldown_minutes=DEFAULT_COOLDOWN_MINUTES, force_send=False, heartbeat_hours=4):
    now = time.time()
    alert_key = f"{analysis['symbol']}:{analysis['trigger']}"
    last_alert_key = state.get("last_alert_key")
    last_alert_ts = float(state.get("last_alert_ts", 0) or 0)
    last_sent = float(state.get("last_sent_ts", 0) or 0)
    heartbeat_due = (now - last_sent) >= heartbeat_hours * 3600

    if force_send:
        return True, "manual/startup check"
    if analysis["actionable"]:
        latest_bar_ts = analysis.get("latest_bar_ts")
        if latest_bar_ts and last_alert_key == alert_key and state.get("last_alert_bar_ts") == latest_bar_ts:
            return False, "same market bar"
        if last_alert_key == alert_key and (now - last_alert_ts) < cooldown_minutes * 60:
            return False, "cooldown active"
        return True, f"actionable {analysis['trigger']}"
    if heartbeat_due:
        return True, "monitor heartbeat"
    return False, "quiet"


def run_check(force_send=False, heartbeat_hours=4, cooldown_minutes=DEFAULT_COOLDOWN_MINUTES):
    state = _load_state()
    analysis = _analyze()
    now = time.time()
    should_send, send_reason = _should_send_alert(
        analysis,
        state,
        cooldown_minutes=cooldown_minutes,
        force_send=force_send,
        heartbeat_hours=heartbeat_hours,
    )

    state.update({
        "last_check_ts": now,
        "last_signal": analysis["signal"],
        "last_trigger": analysis["trigger"],
        "last_price": analysis["price"],
        "last_rsi": analysis["rsi"],
        "last_vwap": analysis["vwap"],
    })

    sent = False
    if should_send:
        sent = send_telegram_message(_format_message(analysis, send_reason), direct_send=True)
        if sent:
            state["last_sent_ts"] = now
            state["last_alert_key"] = f"{analysis['symbol']}:{analysis['trigger']}"
            state["last_alert_ts"] = now
            state["last_alert_bar_ts"] = analysis.get("latest_bar_ts")
    _save_state(state)
    _log(
        f"{SYMBOL} {analysis['signal']} trigger={analysis['trigger']} "
        f"price={analysis['price']:.2f} vwap={analysis['vwap']:.2f} "
        f"rsi={analysis['rsi']:.1f} vol={analysis['volume_ratio']:.1f}x sent={sent}"
    )
    return sent


def main():
    parser = argparse.ArgumentParser(description="Monitor SPCX and send Telegram alerts.")
    parser.add_argument("--interval", type=int, default=900, help="Polling interval in seconds.")
    parser.add_argument("--once", action="store_true", help="Run one check then exit.")
    parser.add_argument("--force-send", action="store_true", help="Send Telegram on this check.")
    parser.add_argument("--cooldown-minutes", type=int, default=DEFAULT_COOLDOWN_MINUTES, help="Cooldown for repeated same trigger.")
    args = parser.parse_args()

    while True:
        try:
            run_check(force_send=args.force_send, cooldown_minutes=args.cooldown_minutes)
        except Exception as exc:
            _log(f"ERROR {exc}")

        if args.once:
            return
        time.sleep(max(args.interval, 60))


if __name__ == "__main__":
    main()
