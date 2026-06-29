import json
import os
import tempfile
import time
import unittest

from trading_system.paper_trade_state import PaperTradeState


class PaperTradeStateTest(unittest.TestCase):
    def test_position_and_backtest_state_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "paper_state.json")
            state = PaperTradeState(path)
            state.set_position("TSLA", True, {"source": "demo"})
            state.set_backtest("TSLA", {"metrics": {"total_return_pct": 5}}, {"passed": True})
            state.save()

            reloaded = PaperTradeState(path)

            self.assertTrue(reloaded.has_position("TSLA"))
            self.assertTrue(reloaded.data["gate_passed"]["TSLA"])
            self.assertEqual(reloaded.data["backtest_results"]["TSLA"]["metrics"]["total_return_pct"], 5)

    def test_cooldown_suppresses_recent_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "paper_state.json")
            state = PaperTradeState(path)
            state.record_order("TQQQ", "BUY", {"status": "executed"}, now=time.time())

            self.assertFalse(state.cooldown_allows("TQQQ", "BUY", cooldown_minutes=60))
            self.assertTrue(state.cooldown_allows("TQQQ", "SELL", cooldown_minutes=60))

    def test_corrupt_file_is_backed_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "paper_state.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{not json")

            state = PaperTradeState(path)

            self.assertEqual(state.data["positions"], {})
            self.assertTrue(os.path.exists(path + ".bak"))

    def test_record_order_writes_expected_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "paper_state.json")
            state = PaperTradeState(path)
            state.record_order("SOXL", "SELL", {"status": "dry_run"}, now=123.0)

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(data["last_order"]["SOXL"]["action"], "SELL")
            self.assertEqual(data["cooldowns"]["SOXL:SELL"], 123.0)

    def test_set_backtest_does_not_persist_full_trade_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "paper_state.json")
            state = PaperTradeState(path)
            state.set_backtest(
                "TSLA",
                {"metrics": {"total_return_pct": 5}, "trades": [{"type": "BUY"}] * 10},
                {"passed": True},
            )

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertNotIn("trades", data["backtest_results"]["TSLA"])
            self.assertEqual(data["backtest_results"]["TSLA"]["metrics"]["total_return_pct"], 5)


if __name__ == "__main__":
    unittest.main()
