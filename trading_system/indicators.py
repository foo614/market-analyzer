"""
Unified technical indicator library for the ClawdBot Trading System.
All agents import from here — no more duplicate RSI/OBV/ATR implementations.
"""

import pandas as pd
import numpy as np


def calculate_rsi(prices, period=14):
    """
    Relative Strength Index.
    Accepts a pandas Series of closing prices.
    Returns a pandas Series of RSI values.
    """
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def calculate_rsi_scalar(prices_list, period=14):
    """
    RSI from a plain Python list of prices. Returns a single float.
    Used by agents that don't work with DataFrames.
    """
    if len(prices_list) <= period:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        diff = prices_list[-i] - prices_list[-i - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100.0 - (100.0 / (1 + rs))


def calculate_obv(df):
    """
    On-Balance Volume.
    Accepts a DataFrame with 'Close' and 'Volume' columns.
    Returns a list of OBV values (same length as df).
    """
    obv = [0]
    for i in range(1, len(df)):
        if df['Close'].iloc[i] > df['Close'].iloc[i - 1]:
            obv.append(obv[-1] + df['Volume'].iloc[i])
        elif df['Close'].iloc[i] < df['Close'].iloc[i - 1]:
            obv.append(obv[-1] - df['Volume'].iloc[i])
        else:
            obv.append(obv[-1])
    return obv


def calculate_obv_from_lists(close_prices, volumes):
    """OBV from plain Python lists. Returns a list."""
    obv = [0]
    for i in range(1, len(close_prices)):
        if close_prices[i] > close_prices[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif close_prices[i] < close_prices[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    return obv


def calculate_atr(df, period=14):
    """
    Average True Range.
    Accepts a DataFrame with 'High', 'Low', 'Close' columns.
    Returns a pandas Series.
    """
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    return true_range.rolling(period).mean()


def calculate_atr_scalar(quotes, period=14):
    """
    ATR from a list of dicts with 'high', 'low', 'close' keys.
    Returns a single float.
    """
    if len(quotes) <= period + 1:
        return 0.0
    tr_values = []
    for i in range(1, len(quotes)):
        h, l = quotes[i]['high'], quotes[i]['low']
        pc = quotes[i - 1]['close']
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_values.append(tr)
    return sum(tr_values[-period:]) / period


def calculate_macd(close_prices, fast=12, slow=26, signal=9):
    """
    MACD (Moving Average Convergence Divergence).
    Accepts a pandas Series of close prices.
    Returns (macd_line, signal_line) as pandas Series.
    """
    exp_fast = close_prices.ewm(span=fast, adjust=False).mean()
    exp_slow = close_prices.ewm(span=slow, adjust=False).mean()
    macd = exp_fast - exp_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line


def calculate_sma(prices, window):
    """Simple Moving Average. Returns a pandas Series."""
    return prices.rolling(window=window).mean()


def calculate_vwap(high, low, close, volume):
    """
    Volume-Weighted Average Price.
    Accepts pandas Series for each input.
    Returns a single float (cumulative VWAP).
    """
    typical_price = (high + low + close) / 3
    total_vol = volume.sum()
    if total_vol == 0:
        return close.iloc[-1]
    return (typical_price * volume).sum() / total_vol
