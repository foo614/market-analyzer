import unittest

import pandas as pd

from trading_system.signal_model import ACCUMULATE, BUY, HOLD, STOP_LOSS, TAKE_PROFIT
from trading_system.trend_strategy import analyze_trend_frame


def make_frame(closes, volumes=None):
    volumes = volumes or [1000] * len(closes)
    rows = []
    for close, volume in zip(closes, volumes):
        rows.append({
            "Open": close - 0.2,
            "High": close + 0.6,
            "Low": close - 0.6,
            "Close": close,
            "Volume": volume,
        })
    return pd.DataFrame(rows)


class TrendStrategyTest(unittest.TestCase):
    def test_strong_ema_vwap_momentum_emits_buy(self):
        closes = [100 + (i * 0.55) for i in range(70)]
        volumes = [1000] * 55 + [1300] * 15

        analysis = analyze_trend_frame(make_frame(closes, volumes), symbol="TSLA", timeframe="5m")

        self.assertEqual(analysis["source"], "trend_monitor")
        self.assertEqual(analysis["strategy"], "aggressive_ema_vwap_trend")
        self.assertEqual(analysis["signalCategory"], BUY)
        self.assertEqual(analysis["tradeAction"], "BUY")
        self.assertEqual(analysis["signal"], "TREND BUY")
        self.assertEqual(analysis["trendStatus"], "Bullish")
        self.assertGreater(analysis["ema9"], analysis["ema21"])
        self.assertGreater(analysis["ema21"], analysis["ema50"])
        self.assertGreater(analysis["price"], analysis["vwap"])
        self.assertGreater(analysis["stopPrice"], 0)
        self.assertLess(analysis["stopPrice"], analysis["price"])

    def test_downtrend_does_not_emit_buy(self):
        closes = [150 - (i * 0.45) for i in range(70)]

        analysis = analyze_trend_frame(make_frame(closes), symbol="TQQQ", timeframe="5m")

        self.assertEqual(analysis["signalCategory"], HOLD)
        self.assertIsNone(analysis["tradeAction"])
        self.assertEqual(analysis["signal"], "HOLD")
        self.assertEqual(analysis["trendStatus"], "Bearish")

    def test_trend_pullback_emits_accumulate_without_broker_action(self):
        closes = [100 + (i * 0.4) for i in range(65)]
        closes = closes[:-1] + [closes[-1] - 1.0]
        volumes = [1000] * 55 + [1300] * 10

        analysis = analyze_trend_frame(make_frame(closes, volumes), symbol="TQQQ", timeframe="5m")

        self.assertEqual(analysis["signalCategory"], ACCUMULATE)
        self.assertIsNone(analysis["tradeAction"])
        self.assertEqual(analysis["signal"], "ACCUMULATE WATCH")
        self.assertEqual(analysis["trigger"], "trend_pullback")

    def test_late_trend_break_emits_sell(self):
        closes = [100 + (i * 0.5) for i in range(65)] + [126, 123, 119, 115, 111]
        volumes = [1000] * 65 + [1600, 1700, 1800, 1900, 2000]

        analysis = analyze_trend_frame(make_frame(closes, volumes), symbol="SOXL", timeframe="5m", in_position=True)

        self.assertEqual(analysis["signalCategory"], STOP_LOSS)
        self.assertEqual(analysis["tradeAction"], "SELL")
        self.assertEqual(analysis["signal"], "TREND SELL")
        self.assertIn(analysis["trigger"], {"atr_trailing_stop", "ema_trend_break"})
        self.assertLess(analysis["price"], analysis["ema21"])

    def test_in_position_extended_momentum_emits_take_profit(self):
        closes = [100 + (i * 0.5) for i in range(70)]
        closes[-1] = closes[-2] + 8.0

        analysis = analyze_trend_frame(make_frame(closes), symbol="TSLA", timeframe="5m", in_position=True)

        self.assertEqual(analysis["signalCategory"], TAKE_PROFIT)
        self.assertEqual(analysis["tradeAction"], "SELL")
        self.assertEqual(analysis["signal"], "TAKE PROFIT WATCH")
        self.assertEqual(analysis["trigger"], "overbought_extension")
        self.assertGreaterEqual(analysis["rsi"], 80)


if __name__ == "__main__":
    unittest.main()
