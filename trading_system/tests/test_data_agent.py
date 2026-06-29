import unittest

import pandas as pd

import trading_system.agents.data_agent as data_module
from trading_system.agents.data_agent import DataAgent


def make_frame():
    index = pd.date_range("2026-06-17 09:30", periods=70, freq="5min")
    rows = []
    for i in range(70):
        close = 100 + (i * 0.5)
        rows.append({
            "Open": close - 0.2,
            "High": close + 0.6,
            "Low": close - 0.6,
            "Close": close,
            "Volume": 1200,
        })
    return pd.DataFrame(rows, index=index)


class DataAgentTest(unittest.TestCase):
    def setUp(self):
        self.original_fetch_history = data_module.fetch_history
        self.original_publish = data_module.bus.publish
        self.published = []
        data_module.bus.publish = lambda topic, payload: self.published.append((topic, payload))

    def tearDown(self):
        data_module.fetch_history = self.original_fetch_history
        data_module.bus.publish = self.original_publish

    def test_technical_scan_uses_broker_provider_metadata(self):
        calls = []
        data_module.fetch_history = lambda symbol, provider="auto", interval=None: (
            calls.append((symbol, provider, interval)) or (make_frame(), "latest", "5m", "moomoo")
        )

        agent = DataAgent()
        agent._get_tickers = lambda: ["TSLA"]
        agent._get_position_symbols = lambda: set()

        agent.run_technical_scan()

        self.assertEqual(calls, [("TSLA", "auto", "5m")])
        self.assertEqual(len(self.published), 1)
        topic, payload = self.published[0]
        self.assertEqual(topic, "market_data")
        self.assertEqual(payload["symbol"], "TSLA")
        self.assertEqual(payload["dataSource"], "moomoo")
        self.assertEqual(payload["dataPeriod"], "latest")
        self.assertEqual(payload["dataInterval"], "5m")
        self.assertEqual(payload["dataConfidence"], "high")
        self.assertEqual(payload["timeframe"], "5m")
        self.assertIn("latestBarTs", payload)


if __name__ == "__main__":
    unittest.main()
