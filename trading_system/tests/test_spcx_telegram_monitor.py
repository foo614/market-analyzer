import time
import unittest

import pandas as pd

from trading_system.signal_model import ACCUMULATE, STOP_LOSS, TAKE_PROFIT
from trading_system.spcx_telegram_monitor import (
    _build_intraday_analysis,
    _should_send_alert,
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


class SpcxTelegramMonitorTest(unittest.TestCase):
    def test_breakout_above_prior_high_is_tp_watch(self):
        hist = make_frame([150, 152, 154, 156, 158, 160, 162, 164, 166, 169])

        analysis = _build_intraday_analysis(hist)

        self.assertEqual(analysis["signal"], "TAKE PROFIT WATCH")
        self.assertEqual(analysis["signalCategory"], TAKE_PROFIT)
        self.assertEqual(analysis["tradeAction"], "SELL")
        self.assertEqual(analysis["trigger"], "breakout")
        self.assertTrue(analysis["actionable"])

    def test_breakdown_below_vwap_is_sl_watch(self):
        hist = make_frame([170, 169, 168, 167, 166, 165, 164, 163, 162, 158])

        analysis = _build_intraday_analysis(hist)

        self.assertEqual(analysis["signal"], "STOP LOSS WATCH")
        self.assertEqual(analysis["signalCategory"], STOP_LOSS)
        self.assertEqual(analysis["tradeAction"], "SELL")
        self.assertEqual(analysis["trigger"], "vwap_breakdown")
        self.assertTrue(analysis["actionable"])

    def test_volume_spike_rebound_is_accumulate(self):
        hist = make_frame(
            [160, 159, 158, 157, 156, 157, 158, 159, 160, 162],
            [1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 5000],
        )

        analysis = _build_intraday_analysis(hist)

        self.assertEqual(analysis["signal"], "ACCUMULATE WATCH")
        self.assertEqual(analysis["signalCategory"], ACCUMULATE)
        self.assertIsNone(analysis["tradeAction"])
        self.assertEqual(analysis["trigger"], "volume_rebound")
        self.assertGreaterEqual(analysis["volume_ratio"], 3.0)

    def test_cooldown_suppresses_repeated_same_trigger(self):
        state = {
            "last_alert_key": "SPCX:breakout",
            "last_alert_ts": time.time(),
        }
        analysis = {
            "symbol": "SPCX",
            "trigger": "breakout",
            "actionable": True,
        }

        should_send, reason = _should_send_alert(analysis, state, cooldown_minutes=60, force_send=False)

        self.assertFalse(should_send)
        self.assertEqual(reason, "cooldown active")

    def test_same_market_bar_does_not_realert_after_cooldown(self):
        state = {
            "last_alert_key": "SPCX:breakout",
            "last_alert_ts": time.time() - 7200,
            "last_alert_bar_ts": "2026-06-12 16:24:00+00:00",
        }
        analysis = {
            "symbol": "SPCX",
            "trigger": "breakout",
            "latest_bar_ts": "2026-06-12 16:24:00+00:00",
            "actionable": True,
        }

        should_send, reason = _should_send_alert(analysis, state, cooldown_minutes=45, force_send=False)

        self.assertFalse(should_send)
        self.assertEqual(reason, "same market bar")


if __name__ == "__main__":
    unittest.main()
