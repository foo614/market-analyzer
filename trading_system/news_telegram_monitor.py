"""
Financial news Telegram monitor.

Standalone alert-only monitor. It reads Yahoo Finance news via yfinance,
dedupes already-sent items, and sends related news digests to Telegram.
It does not import or start ExecutionAgent and does not place orders.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime

import pytz
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import system_path
from telegram_notifier import send_telegram_message


DEFAULT_SYMBOLS = ["SPCX", "TSLA", "TQQQ", "SOXL", "SPY", "QQQ", "SMH"]
DEFAULT_CORE_SYMBOLS = ["SPCX", "TSLA", "TQQQ", "SOXL"]
DEFAULT_KEYWORDS = [
    "spcx",
    "spacex",
    "tesla",
    "tqqq",
    "soxl",
    "ipo",
    "fed",
    "rate",
    "inflation",
    "cpi",
    "ppi",
    "nasdaq",
    "s&p",
    "s&p 500",
    "market",
    "ai",
    "semiconductor",
    "semiconductors",
    "chips",
    "tech",
]
STATE_FILE = system_path("news_monitor_state.json")
LOG_FILE = system_path("logs", "news_monitor.log")
ET = pytz.timezone("US/Eastern")


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
                data.setdefault("seen_ids", [])
                return data
    except Exception:
        pass
    return {"seen_ids": []}


def _save_state(state):
    tmp_path = f"{STATE_FILE}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp_path, STATE_FILE)


def _nested_url(value):
    if isinstance(value, dict):
        return value.get("url") or value.get("href") or ""
    if isinstance(value, str):
        return value
    return ""


def _provider_name(value):
    if isinstance(value, dict):
        return value.get("displayName") or value.get("name") or "Yahoo Finance"
    if isinstance(value, str):
        return value
    return "Yahoo Finance"


def _stable_id(symbol, title, url):
    raw = f"{symbol}|{title}|{url}".encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()


def _normalize_news_item(symbol, item):
    content = item.get("content", item) if isinstance(item, dict) else {}
    title = (content.get("title") or item.get("title") or "").strip()
    summary = (content.get("summary") or content.get("description") or item.get("summary") or "").strip()
    url = (
        _nested_url(content.get("canonicalUrl"))
        or _nested_url(content.get("clickThroughUrl"))
        or _nested_url(item.get("link"))
        or _nested_url(item.get("url"))
    )
    publisher = (
        _provider_name(content.get("provider"))
        or item.get("publisher")
        or item.get("publisherName")
        or "Yahoo Finance"
    )
    published_at = (
        content.get("pubDate")
        or content.get("displayTime")
        or item.get("providerPublishTime")
        or item.get("pubDate")
        or ""
    )
    if isinstance(published_at, (int, float)):
        published_at = datetime.fromtimestamp(published_at, tz=ET).isoformat()

    news_id = str(content.get("id") or item.get("id") or _stable_id(symbol, title, url))
    return {
        "id": news_id,
        "symbol": str(symbol).upper(),
        "title": title,
        "summary": summary,
        "publisher": publisher,
        "url": url,
        "published_at": str(published_at),
    }


def _is_related(item, core_symbols=None, keywords=None):
    core_symbols = [s.upper() for s in (core_symbols or DEFAULT_CORE_SYMBOLS)]
    keywords = [k.lower() for k in (keywords or DEFAULT_KEYWORDS)]
    symbol = str(item.get("symbol", "")).upper()
    if symbol in core_symbols:
        return True

    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    return any(keyword in text for keyword in keywords)


def _select_new_items(items, state, limit=5):
    seen = set(state.get("seen_ids", []))
    selected = []
    for item in items:
        if not item.get("id") or item["id"] in seen:
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _trading_read(item):
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    if any(word in text for word in ["jump", "surge", "rally", "gain", "soar", "record high"]):
        return "Momentum positive. Watch TP zones and avoid chasing extended candles."
    if any(word in text for word in ["drop", "fall", "selloff", "lawsuit", "probe", "miss", "cut"]):
        return "Risk negative. Watch SL/VWAP breakdown and reduce size if price confirms."
    if any(word in text for word in ["fed", "rate", "inflation", "cpi", "ppi"]):
        return "Macro-sensitive. Expect volatility around rates, yields, and index futures."
    if any(word in text for word in ["ipo", "debut", "retail investors", "spacex"]):
        return "SPCX catalyst watch. Treat as high-volatility IPO/momentum flow."
    return "Monitor price reaction before acting. News alone is not a trade trigger."


def _format_digest(items):
    generated = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        "**FINANCIAL NEWS WATCH**",
        f"Generated: `{generated}`",
        "",
    ]
    for index, item in enumerate(items, 1):
        lines.extend([
            f"{index}. **{item['symbol']}** - {item['title']}",
            f"Source: `{item.get('publisher') or 'Yahoo Finance'}`",
        ])
        if item.get("published_at"):
            lines.append(f"Time: `{item['published_at']}`")
        if item.get("summary"):
            lines.append(f"Summary: `{item['summary'][:240]}`")
        lines.append(f"Trading read: `{_trading_read(item)}`")
        if item.get("url"):
            lines.append(item["url"])
        lines.append("")
    lines.append("No order was placed. Manual confirmation only.")
    return "\n".join(lines).strip()


def _fetch_news(symbols):
    items = []
    for symbol in symbols:
        try:
            news = yf.Ticker(symbol).news or []
            for item in news:
                normalized = _normalize_news_item(symbol, item)
                if normalized["title"]:
                    items.append(normalized)
            time.sleep(0.5)
        except Exception as exc:
            _log(f"ERROR fetching {symbol} news: {exc}")
    return items


def run_check(symbols=None, core_symbols=None, keywords=None, limit=5, force_send=False):
    symbols = [s.strip().upper() for s in (symbols or DEFAULT_SYMBOLS) if s.strip()]
    core_symbols = [s.strip().upper() for s in (core_symbols or DEFAULT_CORE_SYMBOLS) if s.strip()]
    keywords = [k.strip().lower() for k in (keywords or DEFAULT_KEYWORDS) if k.strip()]

    state = _load_state()
    all_items = _fetch_news(symbols)
    related_items = [
        item for item in all_items
        if _is_related(item, core_symbols=core_symbols, keywords=keywords)
    ]
    new_items = _select_new_items(related_items, state, limit=limit)
    sent = False

    if new_items or (force_send and related_items):
        digest_items = new_items if new_items else related_items[:limit]
        sent = send_telegram_message(_format_digest(digest_items), direct_send=True)
        if sent:
            seen = list(dict.fromkeys(state.get("seen_ids", []) + [item["id"] for item in digest_items]))
            state["seen_ids"] = seen[-500:]
            state["last_sent_ts"] = time.time()
            state["last_sent_count"] = len(digest_items)

    state["last_check_ts"] = time.time()
    state["last_related_count"] = len(related_items)
    _save_state(state)
    _log(f"news symbols={','.join(symbols)} related={len(related_items)} new={len(new_items)} sent={sent}")
    return sent


def _split_arg(value):
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def main():
    parser = argparse.ArgumentParser(description="Push related financial news to Telegram.")
    parser.add_argument("--interval", type=int, default=300, help="Polling interval in seconds.")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="Comma-separated Yahoo Finance symbols.")
    parser.add_argument("--core-symbols", default=",".join(DEFAULT_CORE_SYMBOLS), help="Symbols whose news is always relevant.")
    parser.add_argument("--keywords", default=",".join(DEFAULT_KEYWORDS), help="Comma-separated related-news keywords.")
    parser.add_argument("--limit", type=int, default=5, help="Max news items per Telegram digest.")
    parser.add_argument("--once", action="store_true", help="Run one check then exit.")
    parser.add_argument("--force-send", action="store_true", help="Send latest related digest even if all items were seen.")
    args = parser.parse_args()

    while True:
        try:
            run_check(
                symbols=_split_arg(args.symbols),
                core_symbols=_split_arg(args.core_symbols),
                keywords=_split_arg(args.keywords),
                limit=args.limit,
                force_send=args.force_send,
            )
        except Exception as exc:
            _log(f"ERROR {exc}")

        if args.once:
            return
        time.sleep(max(args.interval, 60))


if __name__ == "__main__":
    main()
