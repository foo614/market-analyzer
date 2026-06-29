import unittest

import pandas as pd

import trading_system.broker_providers as broker_providers


def make_frame(index_value):
    return pd.DataFrame(
        [{
            "Open": 100.0,
            "High": 101.0,
            "Low": 99.0,
            "Close": 100.5,
            "Volume": 1000,
        }],
        index=[pd.Timestamp(index_value)],
    )


class BrokerProvidersTest(unittest.TestCase):
    def setUp(self):
        self.original_fetch_moomoo = broker_providers.fetch_moomoo_history
        self.original_fetch_yfinance = broker_providers.fetch_yfinance_history

    def tearDown(self):
        broker_providers.fetch_moomoo_history = self.original_fetch_moomoo
        broker_providers.fetch_yfinance_history = self.original_fetch_yfinance

    def test_auto_falls_back_when_moomoo_history_is_stale(self):
        broker_providers.fetch_moomoo_history = lambda symbol, interval="5m": make_frame("2025-01-01")
        broker_providers.fetch_yfinance_history = lambda symbol, preferred_interval=None: (
            make_frame(pd.Timestamp.now()),
            "5d",
            "5m",
            "yfinance",
        )

        frame, period, interval, source = broker_providers.fetch_history("TSLA", provider="auto")

        self.assertEqual(source, "yfinance")
        self.assertEqual(period, "5d")
        self.assertEqual(interval, "5m")
        self.assertFalse(frame.empty)

    def test_explicit_moomoo_raises_when_history_is_stale(self):
        broker_providers.fetch_moomoo_history = lambda symbol, interval="5m": make_frame("2025-01-01")

        with self.assertRaises(RuntimeError):
            broker_providers.fetch_history("TSLA", provider="moomoo")


if __name__ == "__main__":
    unittest.main()
