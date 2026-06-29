"""
Aggressive intraday trend-following strategy.

The strategy is designed for 5-minute US equity bars. It favors early trend
continuation over RSI mean reversion and uses ATR for sell/stop watch signals.
"""

import pandas as pd

try:
    from .indicators import calculate_atr, calculate_macd, calculate_obv, calculate_rsi
    from .signal_model import ACCUMULATE, BUY, HOLD, STOP_LOSS, TAKE_PROFIT
except ImportError:  # Support direct execution from trading_system/ on sys.path.
    from indicators import calculate_atr, calculate_macd, calculate_obv, calculate_rsi
    from signal_model import ACCUMULATE, BUY, HOLD, STOP_LOSS, TAKE_PROFIT


STRATEGY_NAME = "aggressive_ema_vwap_trend"
MIN_BARS = 55


def _as_float(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _round_price(value):
    return round(_as_float(value), 4)


def add_trend_indicators(df):
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns: {sorted(missing)}")

    out = df.copy()
    out["EMA_9"] = out["Close"].ewm(span=9, adjust=False).mean()
    out["EMA_21"] = out["Close"].ewm(span=21, adjust=False).mean()
    out["EMA_50"] = out["Close"].ewm(span=50, adjust=False).mean()
    out["RSI"] = calculate_rsi(out["Close"], 14)
    out["ATR"] = calculate_atr(out, 14)
    out["MACD"], out["MACD_Signal"] = calculate_macd(out["Close"])
    out["MACD_Hist"] = out["MACD"] - out["MACD_Signal"]
    out["OBV"] = calculate_obv(out)
    out["OBV_Fast"] = pd.Series(out["OBV"], index=out.index).rolling(5).mean()
    out["OBV_Slow"] = pd.Series(out["OBV"], index=out.index).rolling(10).mean()

    typical_price = (out["High"] + out["Low"] + out["Close"]) / 3
    volume_sum = out["Volume"].rolling(20, min_periods=1).sum()
    out["VWAP_20"] = (typical_price * out["Volume"]).rolling(20, min_periods=1).sum() / volume_sum.replace(0, pd.NA)
    out["Volume_Avg_20"] = out["Volume"].rolling(20, min_periods=1).mean()
    out["Volume_Ratio"] = out["Volume"] / out["Volume_Avg_20"].replace(0, pd.NA)

    rolling_high = out["High"].rolling(20, min_periods=1).max()
    out["ATR_Trail_Stop"] = rolling_high - (2.5 * out["ATR"])
    return out


def analyze_trend_frame(df, symbol, timeframe="5m", in_position=False):
    if df is None or len(df) < MIN_BARS:
        return {
            "source": "trend_monitor",
            "strategy": STRATEGY_NAME,
            "symbol": str(symbol).upper(),
            "timeframe": timeframe,
            "signal": "HOLD",
            "signalCategory": HOLD,
            "tradeAction": None,
            "trigger": "insufficient_data",
            "reason": f"Need at least {MIN_BARS} bars for EMA/VWAP trend analysis.",
            "trendStatus": "Unknown",
            "inPosition": bool(in_position),
        }

    trend = add_trend_indicators(df).dropna(subset=["EMA_9", "EMA_21", "EMA_50", "ATR", "VWAP_20", "MACD_Hist"])
    if trend.empty:
        return {
            "source": "trend_monitor",
            "strategy": STRATEGY_NAME,
            "symbol": str(symbol).upper(),
            "timeframe": timeframe,
            "signal": "HOLD",
            "signalCategory": HOLD,
            "tradeAction": None,
            "trigger": "indicator_warmup",
            "reason": "Trend indicators are still warming up.",
            "trendStatus": "Unknown",
            "inPosition": bool(in_position),
        }

    last = trend.iloc[-1]
    prev = trend.iloc[-2] if len(trend) >= 2 else last
    slope_ref = trend.iloc[-6] if len(trend) >= 6 else prev

    price = _as_float(last["Close"])
    ema9 = _as_float(last["EMA_9"])
    ema21 = _as_float(last["EMA_21"])
    ema50 = _as_float(last["EMA_50"])
    vwap = _as_float(last["VWAP_20"])
    atr = _as_float(last["ATR"])
    rsi = _as_float(last["RSI"], 50.0)
    macd_hist = _as_float(last["MACD_Hist"])
    prev_macd_hist = _as_float(prev["MACD_Hist"])
    volume_ratio = _as_float(last["Volume_Ratio"], 1.0)
    stop_price = _as_float(last["ATR_Trail_Stop"])

    ema_aligned = ema9 > ema21 > ema50
    ema_slope_up = ema21 > _as_float(slope_ref["EMA_21"]) and ema50 >= _as_float(slope_ref["EMA_50"])
    price_above_vwap = price > vwap
    macd_positive = macd_hist > 0
    obv_accumulating = _as_float(last["OBV_Fast"]) > _as_float(last["OBV_Slow"])
    volume_confirmed = volume_ratio >= 1.05 or obv_accumulating

    trend_status = "Bullish" if ema_aligned and ema_slope_up else ("Bearish" if ema9 < ema21 < ema50 else "Neutral")
    trigger = "no_trigger"
    signal = "HOLD"
    signal_category = HOLD
    trade_action = None
    reason = "No aggressive trend-following trigger."

    if in_position and price < stop_price and stop_price > 0:
        signal = "TREND SELL"
        signal_category = STOP_LOSS
        trade_action = "SELL"
        trigger = "atr_trailing_stop"
        reason = f"Price broke the ATR trailing stop at ${stop_price:.2f}."
    elif in_position and price < ema21 and macd_hist < prev_macd_hist:
        signal = "TREND SELL"
        signal_category = STOP_LOSS
        trade_action = "SELL"
        trigger = "ema_trend_break"
        reason = "Price lost EMA21 while MACD momentum weakened."
    elif in_position and rsi >= 80 and price > ema9 * 1.02:
        signal = "TAKE PROFIT WATCH"
        signal_category = TAKE_PROFIT
        trade_action = "SELL"
        trigger = "overbought_extension"
        reason = "Position is extended above EMA9 with overbought RSI; consider taking profit."
    elif ema_aligned and ema_slope_up and price_above_vwap and macd_positive and volume_confirmed:
        signal = "TREND BUY"
        signal_category = BUY
        trade_action = "BUY"
        trigger = "ema_vwap_momentum"
        reason = "EMA9/21/50 alignment, VWAP strength, and expanding MACD confirm trend continuation."
    elif ema_aligned and ema_slope_up and price >= ema21 and price <= ema9 * 1.01 and obv_accumulating:
        signal = "ACCUMULATE WATCH"
        signal_category = ACCUMULATE
        trigger = "trend_pullback"
        reason = "Uptrend pullback is holding EMA21 with OBV accumulation."

    return {
        "source": "trend_monitor",
        "strategy": STRATEGY_NAME,
        "symbol": str(symbol).upper(),
        "timeframe": timeframe,
        "price": _round_price(price),
        "sma50": _round_price(ema50),
        "ema9": _round_price(ema9),
        "ema21": _round_price(ema21),
        "ema50": _round_price(ema50),
        "vwap": _round_price(vwap),
        "rsi": round(rsi, 2),
        "atr": _round_price(atr),
        "macdHist": round(macd_hist, 6),
        "volumeRatio": round(volume_ratio, 4),
        "stopPrice": _round_price(stop_price),
        "obvStatus": "Accumulating" if obv_accumulating else "Distributing",
        "isBullish": trend_status == "Bullish",
        "trendStatus": trend_status,
        "inPosition": bool(in_position),
        "signal": signal,
        "signalCategory": signal_category,
        "tradeAction": trade_action,
        "trigger": trigger,
        "reason": reason,
    }
