"""
Backtest and gate helpers for the eToro demo paper-trade agent.
"""

import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from signal_model import ACCUMULATE, BUY, HOLD, STOP_LOSS, TAKE_PROFIT, category_trade_action
from trend_strategy import MIN_BARS, add_trend_indicators


DEFAULT_MAX_DRAWDOWN = {
    "TSLA": 25.0,
    "TQQQ": 35.0,
    "SOXL": 35.0,
    "SPCX": 40.0,
}


@dataclass
class BacktestGateConfig:
    min_closed_trades: int = 3
    min_total_return_pct: float = 0.0
    min_win_rate_pct: float = 45.0
    require_beats_buy_hold_or_lower_drawdown: bool = True
    max_drawdown_by_symbol: dict = field(default_factory=lambda: dict(DEFAULT_MAX_DRAWDOWN))


def _normalize_history(df):
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.droplevel(1)
    return out.dropna(how="all")


def generate_trend_signals(df, symbol, timeframe="5m"):
    out = _normalize_history(df)
    if out.empty:
        out["Signal"] = []
        out["SignalLabel"] = []
        out["SignalCategory"] = []
        out["TradeAction"] = []
        out["Trigger"] = []
        return out

    trend = add_trend_indicators(out)
    signals = []
    labels = []
    categories = []
    trade_actions = []
    triggers = []
    in_position = False

    for i in range(len(trend)):
        if i + 1 < MIN_BARS:
            signals.append(0)
            labels.append("HOLD")
            categories.append(HOLD)
            trade_actions.append(None)
            triggers.append("insufficient_data")
            continue

        last = trend.iloc[i]
        prev = trend.iloc[i - 1] if i >= 1 else last
        slope_ref = trend.iloc[i - 5] if i >= 5 else prev

        required = ["EMA_9", "EMA_21", "EMA_50", "ATR", "VWAP_20", "MACD_Hist"]
        if any(pd.isna(last.get(column)) for column in required):
            signals.append(0)
            labels.append("HOLD")
            categories.append(HOLD)
            trade_actions.append(None)
            triggers.append("indicator_warmup")
            continue

        price = float(last["Close"])
        ema9 = float(last["EMA_9"])
        ema21 = float(last["EMA_21"])
        ema50 = float(last["EMA_50"])
        vwap = float(last["VWAP_20"])
        rsi = float(last["RSI"]) if not pd.isna(last["RSI"]) else 50.0
        macd_hist = float(last["MACD_Hist"])
        prev_macd_hist = float(prev["MACD_Hist"]) if not pd.isna(prev["MACD_Hist"]) else macd_hist
        stop_price = float(last["ATR_Trail_Stop"]) if not pd.isna(last["ATR_Trail_Stop"]) else 0.0
        volume_ratio = float(last["Volume_Ratio"]) if not pd.isna(last["Volume_Ratio"]) else 1.0
        obv_fast = float(last["OBV_Fast"]) if not pd.isna(last["OBV_Fast"]) else 0.0
        obv_slow = float(last["OBV_Slow"]) if not pd.isna(last["OBV_Slow"]) else 0.0

        ema_aligned = ema9 > ema21 > ema50
        ema_slope_up = ema21 > float(slope_ref["EMA_21"]) and ema50 >= float(slope_ref["EMA_50"])
        price_above_vwap = price > vwap
        macd_positive = macd_hist > 0
        obv_accumulating = obv_fast > obv_slow
        volume_confirmed = volume_ratio >= 1.05 or obv_accumulating

        label = "HOLD"
        signal_category = HOLD
        trade_action = None
        trigger = "no_trigger"

        if in_position and price < stop_price and stop_price > 0:
            label = "TREND SELL"
            signal_category = STOP_LOSS
            trade_action = category_trade_action(signal_category)
            trigger = "atr_trailing_stop"
        elif in_position and price < ema21 and macd_hist < prev_macd_hist:
            label = "TREND SELL"
            signal_category = STOP_LOSS
            trade_action = category_trade_action(signal_category)
            trigger = "ema_trend_break"
        elif in_position and rsi >= 80 and price > ema9 * 1.02:
            label = "TAKE PROFIT WATCH"
            signal_category = TAKE_PROFIT
            trade_action = category_trade_action(signal_category)
            trigger = "overbought_extension"
        elif ema_aligned and ema_slope_up and price_above_vwap and macd_positive and volume_confirmed:
            label = "TREND BUY"
            signal_category = BUY
            trade_action = category_trade_action(signal_category)
            trigger = "ema_vwap_momentum"
        elif ema_aligned and ema_slope_up and price >= ema21 and price <= ema9 * 1.01 and obv_accumulating:
            label = "ACCUMULATE WATCH"
            signal_category = ACCUMULATE
            trade_action = category_trade_action(signal_category)
            trigger = "trend_pullback"

        if trade_action == "BUY" and not in_position:
            signals.append(1)
            in_position = True
        elif trade_action == "SELL" and in_position:
            signals.append(-1)
            in_position = False
        else:
            signals.append(0)

        labels.append(label)
        categories.append(signal_category)
        trade_actions.append(trade_action)
        triggers.append(trigger)

    out["Signal"] = signals
    out["SignalLabel"] = labels
    out["SignalCategory"] = categories
    out["TradeAction"] = trade_actions
    out["Trigger"] = triggers
    return out


def _drawdown_pct(values):
    series = pd.Series(values).astype(float)
    if series.empty:
        return 0.0
    peak = series.cummax()
    drawdown = (series - peak) / peak.replace(0, pd.NA)
    value = drawdown.min()
    if pd.isna(value):
        return 0.0
    return abs(float(value) * 100.0)


def simulate_trades(df, initial_capital=10000.0):
    out = _normalize_history(df)
    capital = float(initial_capital)
    quantity = 0.0
    trades = []
    values = []

    for index, row in out.iterrows():
        price = float(row["Close"])
        signal = int(row.get("Signal", 0) or 0)

        if signal == 1 and quantity == 0 and capital > 0:
            quantity = capital / price
            trades.append({"type": "BUY", "price": price, "date": str(index)})
            capital = 0.0
        elif signal == -1 and quantity > 0:
            capital = quantity * price
            trades.append({"type": "SELL", "price": price, "date": str(index)})
            quantity = 0.0

        values.append(capital + (quantity * price))

    if quantity > 0 and len(out) > 0:
        price = float(out["Close"].iloc[-1])
        capital = quantity * price
        trades.append({"type": "SELL", "price": price, "date": str(out.index[-1]), "forced_exit": True})
        quantity = 0.0
        values[-1] = capital

    out["Portfolio_Value"] = values
    return out, trades


def calculate_metrics(df, trades, initial_capital=10000.0):
    if df.empty:
        return {
            "total_return_pct": 0.0,
            "buy_hold_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "buy_hold_max_drawdown_pct": 0.0,
            "win_rate_pct": 0.0,
            "closed_trades": 0,
        }

    final_value = float(df["Portfolio_Value"].iloc[-1])
    total_return_pct = ((final_value - initial_capital) / initial_capital) * 100.0
    first_close = float(df["Close"].iloc[0])
    last_close = float(df["Close"].iloc[-1])
    buy_hold_return_pct = ((last_close - first_close) / first_close) * 100.0 if first_close else 0.0

    wins = 0
    losses = 0
    open_buy = None
    for trade in trades:
        if trade["type"] == "BUY":
            open_buy = float(trade["price"])
        elif trade["type"] == "SELL" and open_buy is not None:
            if float(trade["price"]) > open_buy:
                wins += 1
            else:
                losses += 1
            open_buy = None

    closed_trades = wins + losses
    win_rate_pct = (wins / closed_trades * 100.0) if closed_trades else 0.0
    buy_hold_values = (df["Close"] / first_close) * initial_capital if first_close else df["Close"] * 0

    return {
        "total_return_pct": round(total_return_pct, 4),
        "buy_hold_return_pct": round(buy_hold_return_pct, 4),
        "max_drawdown_pct": round(_drawdown_pct(df["Portfolio_Value"]), 4),
        "buy_hold_max_drawdown_pct": round(_drawdown_pct(buy_hold_values), 4),
        "win_rate_pct": round(win_rate_pct, 4),
        "closed_trades": closed_trades,
    }


def run_backtest_for_frame(symbol, df, initial_capital=10000.0, use_existing_signals=False):
    if use_existing_signals:
        signal_frame = _normalize_history(df)
    else:
        signal_frame = generate_trend_signals(df, symbol)

    if signal_frame.empty:
        return {"symbol": str(symbol).upper(), "metrics": None, "trades": [], "error": "empty_history"}

    portfolio_frame, trades = simulate_trades(signal_frame, initial_capital=initial_capital)
    metrics = calculate_metrics(portfolio_frame, trades, initial_capital=initial_capital)
    return {
        "symbol": str(symbol).upper(),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "metrics": metrics,
        "trades": trades,
    }


def fetch_backtest_history(symbol, period="60d", interval="5m"):
    hist = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=False)
    hist = _normalize_history(hist)
    if hist.empty:
        raise RuntimeError(f"No backtest data returned for {symbol}")
    return hist


def run_symbol_backtest(symbol, history_fetcher=None):
    fetcher = history_fetcher or fetch_backtest_history
    return run_backtest_for_frame(symbol, fetcher(symbol))


def apply_backtest_gate(result, symbol, config=None):
    config = config or BacktestGateConfig()
    symbol = str(symbol).upper()
    metrics = (result or {}).get("metrics")
    reasons = []

    if not metrics:
        return {"symbol": symbol, "passed": False, "reasons": ["metrics_unavailable"], "metrics": metrics}

    if int(metrics.get("closed_trades", 0) or 0) < config.min_closed_trades:
        reasons.append(f"closed_trades<{config.min_closed_trades}")
    if float(metrics.get("total_return_pct", 0) or 0) <= config.min_total_return_pct:
        reasons.append(f"total_return<={config.min_total_return_pct}")
    if float(metrics.get("win_rate_pct", 0) or 0) < config.min_win_rate_pct:
        reasons.append(f"win_rate<{config.min_win_rate_pct}")

    max_allowed = float(config.max_drawdown_by_symbol.get(symbol, 35.0))
    if float(metrics.get("max_drawdown_pct", 0) or 0) > max_allowed:
        reasons.append(f"max_drawdown>{max_allowed}")

    if config.require_beats_buy_hold_or_lower_drawdown:
        total_return = float(metrics.get("total_return_pct", 0) or 0)
        buy_hold_return = float(metrics.get("buy_hold_return_pct", 0) or 0)
        max_drawdown = float(metrics.get("max_drawdown_pct", 0) or 0)
        buy_hold_drawdown = float(metrics.get("buy_hold_max_drawdown_pct", 0) or 0)
        if total_return < buy_hold_return and max_drawdown >= buy_hold_drawdown:
            reasons.append("does_not_beat_buy_hold_or_lower_drawdown")

    return {
        "symbol": symbol,
        "passed": not reasons,
        "reasons": reasons,
        "metrics": metrics,
    }
