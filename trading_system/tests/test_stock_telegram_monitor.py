import unittest

import pandas as pd

from trading_system.signal_model import TAKE_PROFIT
from trading_system.stock_telegram_monitor import (
    _build_symbol_analysis,
    _classify_headline_sentiment,
    _format_report,
    _should_send_report,
)


def make_frame(closes, volumes=None):
    volumes = volumes or [1000] * len(closes)
    rows = []
    for close, volume in zip(closes, volumes):
        rows.append({
            "Open": close,
            "High": close + 0.5,
            "Low": close - 0.5,
            "Close": close,
            "Volume": volume,
        })
    return pd.DataFrame(rows)


class StockTelegramMonitorTest(unittest.TestCase):
    def test_build_symbol_analysis_keeps_symbol_and_overlays_sentiment_position(self):
        hist = make_frame([150, 152, 154, 156, 158, 160, 162, 164, 166, 169])

        analysis = _build_symbol_analysis(
            "TSLA",
            hist,
            period="1d",
            interval="1m",
            source="yfinance",
            sentiment={"sentiment": "Bullish", "reason": "Positive delivery headlines."},
            position={"has_position": True, "amount": 500.0, "pnl": 12.5},
        )

        self.assertEqual(analysis["symbol"], "TSLA")
        self.assertEqual(analysis["signal"], "TAKE PROFIT WATCH")
        self.assertEqual(analysis["signalCategory"], TAKE_PROFIT)
        self.assertEqual(analysis["tradeAction"], "SELL")
        self.assertEqual(analysis["trigger"], "breakout")
        self.assertEqual(analysis["sentiment"], "Bullish")
        self.assertEqual(analysis["position"]["pnl"], 12.5)
        self.assertGreater(analysis["volume_ratio"], 0)

    def test_classify_headline_sentiment_scores_bearish_headlines(self):
        result = _classify_headline_sentiment(
            "SOXL",
            [
                "Semiconductor stocks fall after guidance cut",
                "Chip ETFs drop as yields rise",
            ],
        )

        self.assertEqual(result["sentiment"], "Bearish")
        self.assertIn("bearish", result["reason"].lower())

    def test_format_report_contains_multiple_symbols_and_no_order_notice(self):
        analyses = [
            {
                "symbol": "SPCX",
                "signal": "HOLD / WATCH",
                "trigger": "hold_watch",
                "period": "1d",
                "interval": "1m",
                "source": "yfinance",
                "price": 100.0,
                "change_pct": 1.0,
                "vwap": 99.0,
                "rsi": 55.0,
                "volume_ratio": 1.2,
                "obv_status": "Accumulating",
                "sentiment": "Neutral",
                "sentiment_reason": "No strong headlines.",
                "position": {"has_position": False},
                "rationale": "No strong trigger.",
            },
            {
                "symbol": "TQQQ",
                "signal": "ACCUMULATE WATCH",
                "trigger": "volume_rebound",
                "period": "1d",
                "interval": "1m",
                "source": "moomoo",
                "price": 90.0,
                "change_pct": 2.0,
                "vwap": 88.0,
                "rsi": 61.0,
                "volume_ratio": 3.5,
                "obv_status": "Accumulating",
                "sentiment": "Bullish",
                "sentiment_reason": "Nasdaq momentum positive.",
                "position": {"has_position": True, "amount": 250.0, "pnl": 18.0},
                "rationale": "Volume rebound detected.",
            },
        ]

        message = _format_report(analyses, reason="scheduled report")

        self.assertIn("MULTI-STOCK ANALYZE REPORT", message)
        self.assertIn("SPCX", message)
        self.assertIn("TQQQ", message)
        self.assertIn("VOLUME", message)
        self.assertIn("SENTIMENT", message)
        self.assertIn("ETORO", message)
        self.assertIn("No order was placed", message)

    def test_should_not_send_unchanged_quiet_report_before_heartbeat(self):
        analyses = [{
            "symbol": "TSLA",
            "signal": "HOLD / WATCH",
            "trigger": "hold_watch",
            "position": {"has_position": False},
        }]
        state = {
            "last_sent_ts": 1000,
            "last_signals": {"TSLA": "HOLD / WATCH"},
            "last_triggers": {"TSLA": "hold_watch"},
            "last_positions": {"TSLA": False},
        }

        should_send, reason = _should_send_report(analyses, state, now=1100, heartbeat_hours=4)

        self.assertFalse(should_send)
        self.assertEqual(reason, "quiet")

    def test_should_send_actionable_signal_change(self):
        analyses = [{
            "symbol": "TQQQ",
            "signal": "ACCUMULATE WATCH",
            "trigger": "volume_rebound",
            "position": {"has_position": True},
        }]
        state = {
            "last_sent_ts": 1000,
            "last_signals": {"TQQQ": "HOLD / WATCH"},
            "last_triggers": {"TQQQ": "hold_watch"},
            "last_positions": {"TQQQ": True},
        }

        should_send, reason = _should_send_report(analyses, state, now=1100, heartbeat_hours=4)

        self.assertTrue(should_send)
        self.assertIn("signal change", reason)


if __name__ == "__main__":
    unittest.main()
