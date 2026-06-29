"""
Canonical signal categories for trading alerts and paper routing.
"""

BUY = "BUY"
ACCUMULATE = "ACCUMULATE"
STOP_LOSS = "STOP_LOSS"
TAKE_PROFIT = "TAKE_PROFIT"
HOLD = "HOLD"


_ALIASES = {
    "BUY": BUY,
    "TREND_BUY": BUY,
    "ACCUMULATE": ACCUMULATE,
    "ACCUMULATE_WATCH": ACCUMULATE,
    "STOP_LOSS": STOP_LOSS,
    "STOP_LOSS_WATCH": STOP_LOSS,
    "SELL_STOP_LOSS": STOP_LOSS,
    "TREND_SELL": STOP_LOSS,
    "TAKE_PROFIT": TAKE_PROFIT,
    "TAKE_PROFIT_WATCH": TAKE_PROFIT,
    "SELL_TAKE_PROFIT": TAKE_PROFIT,
    "HOLD": HOLD,
    "HOLD_WATCH": HOLD,
    "HOLD__WATCH": HOLD,
}

_TITLES = {
    BUY: "BUY",
    ACCUMULATE: "ACCUMULATE",
    STOP_LOSS: "STOP LOSS",
    TAKE_PROFIT: "TAKE PROFIT",
    HOLD: "HOLD",
}

_TRADE_ACTIONS = {
    BUY: "BUY",
    STOP_LOSS: "SELL",
    TAKE_PROFIT: "SELL",
}


def _key(value):
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_").replace("/", "_")


def normalize_signal_category(value):
    key = _key(value)
    if key in _ALIASES:
        return _ALIASES[key]
    if key.startswith("BUY_"):
        return BUY
    if key.startswith("ACCUMULATE"):
        return ACCUMULATE
    if key.startswith("STOP_LOSS"):
        return STOP_LOSS
    if key.startswith("TAKE_PROFIT"):
        return TAKE_PROFIT
    if key.startswith("HOLD"):
        return HOLD
    return HOLD


def category_title(category):
    return _TITLES.get(normalize_signal_category(category), "HOLD")


def category_trade_action(category):
    return _TRADE_ACTIONS.get(normalize_signal_category(category))


def payload_signal_category(payload):
    payload = payload or {}
    explicit = payload.get("signalCategory") or payload.get("signal_category")
    if explicit:
        return normalize_signal_category(explicit)
    signal = payload.get("signal")
    if signal:
        return normalize_signal_category(signal)
    return normalize_signal_category(payload.get("tradeAction") or payload.get("action"))
