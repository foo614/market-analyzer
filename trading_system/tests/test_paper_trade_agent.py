import os
import tempfile
import unittest

import pandas as pd

from trading_system.paper_trade_state import PaperTradeState
from trading_system.agents.paper_trade_agent import PaperTradeAgent, format_paper_trade_report


def make_frame():
    rows = []
    for i in range(80):
        close = 100 + (i * 0.5)
        rows.append({
            "Open": close - 0.2,
            "High": close + 0.6,
            "Low": close - 0.6,
            "Close": close,
            "Volume": 1200,
        })
    return pd.DataFrame(rows)


def passing_backtest(symbol):
    return {
        "symbol": symbol,
        "metrics": {
            "closed_trades": 4,
            "total_return_pct": 10.0,
            "win_rate_pct": 50.0,
            "max_drawdown_pct": 8.0,
            "buy_hold_return_pct": 6.0,
            "buy_hold_max_drawdown_pct": 15.0,
        },
        "trades": [],
    }


def failing_backtest(symbol):
    result = passing_backtest(symbol)
    result["metrics"]["max_drawdown_pct"] = 80.0
    return result


class PaperTradeAgentTest(unittest.TestCase):
    def make_agent(self, mode="dry-run", backtest_runner=passing_backtest, signal=None, demo_has_position=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        calls = {"buy": [], "close": [], "notify": []}
        state = PaperTradeState(os.path.join(tmp.name, "state.json"))
        signal = signal or {
            "symbol": "TSLA",
            "tradeAction": "BUY",
            "signal": "TREND BUY",
            "trigger": "ema_vwap_momentum",
            "price": 120.0,
            "reason": "Trend confirmed.",
        }

        agent = PaperTradeAgent(
            mode=mode,
            state=state,
            backtest_runner=backtest_runner,
            latest_fetcher=lambda symbol: make_frame(),
            signal_analyzer=lambda frame, symbol, timeframe, in_position: dict(signal, symbol=symbol),
            demo_buy=lambda symbol, action, amount: calls["buy"].append((symbol, action, amount)) or True,
            demo_close=lambda symbol: calls["close"].append(symbol) or True,
            demo_has_position=demo_has_position or (lambda symbol: False),
            notifier=lambda text: calls["notify"].append(text) or True,
        )
        return agent, calls

    def test_dry_run_does_not_execute_demo_buy(self):
        agent, calls = self.make_agent(mode="dry-run")

        result = agent.evaluate_symbol("TSLA")

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(calls["buy"], [])
        self.assertIn("TSLA", calls["notify"][0])

    def test_failed_gate_skips_signal_and_execution(self):
        agent, calls = self.make_agent(mode="demo-execute", backtest_runner=failing_backtest)

        result = agent.evaluate_symbol("TSLA")

        self.assertEqual(result["status"], "gate_failed")
        self.assertEqual(calls["buy"], [])
        self.assertEqual(calls["close"], [])

    def test_demo_execute_buy_calls_open_helper(self):
        agent, calls = self.make_agent(mode="demo-execute")

        result = agent.evaluate_symbol("TSLA")

        self.assertEqual(result["status"], "executed")
        self.assertEqual(calls["buy"], [("TSLA", "BUY", 100.0)])
        self.assertTrue(agent.state.has_position("TSLA"))

    def test_external_signal_uses_backtest_gate_and_dry_run(self):
        agent, calls = self.make_agent(mode="dry-run")

        result = agent.evaluate_signal({
            "symbol": "TSLA",
            "action": "BUY",
            "signal": "TREND BUY",
            "trigger": "ema_vwap_momentum",
            "price": 120.0,
            "reason": "Trend confirmed.",
        })

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["action"], "BUY")
        self.assertEqual(calls["buy"], [])
        self.assertIn("TSLA", calls["notify"][0])

    def test_external_signal_gate_failure_blocks_execution(self):
        agent, calls = self.make_agent(mode="demo-execute", backtest_runner=failing_backtest)

        result = agent.evaluate_signal({
            "symbol": "TSLA",
            "action": "BUY",
            "signal": "TREND BUY",
            "trigger": "ema_vwap_momentum",
            "price": 120.0,
            "reason": "Trend confirmed.",
        })

        self.assertEqual(result["status"], "gate_failed")
        self.assertEqual(calls["buy"], [])
        self.assertEqual(calls["close"], [])

    def test_demo_execute_sell_calls_close_helper(self):
        signal = {
            "symbol": "TSLA",
            "tradeAction": "SELL",
            "signal": "TREND SELL",
            "trigger": "atr_trailing_stop",
            "price": 110.0,
            "reason": "Trailing stop broke.",
        }
        agent, calls = self.make_agent(
            mode="demo-execute",
            signal=signal,
            demo_has_position=lambda symbol: True,
        )
        agent.state.set_position("TSLA", True, {"source": "test"})

        result = agent.evaluate_symbol("TSLA")

        self.assertEqual(result["status"], "executed")
        self.assertEqual(calls["buy"], [])
        self.assertEqual(calls["close"], ["TSLA"])
        self.assertFalse(agent.state.has_position("TSLA"))

    def test_cooldown_suppresses_repeated_signal(self):
        agent, calls = self.make_agent(mode="demo-execute")

        first = agent.evaluate_symbol("TSLA")
        second = agent.evaluate_symbol("TSLA")

        self.assertEqual(first["status"], "executed")
        self.assertEqual(second["status"], "cooldown")
        self.assertEqual(len(calls["buy"]), 1)

    def test_format_report_includes_demo_only_notice(self):
        message = format_paper_trade_report([
            {
                "symbol": "TSLA",
                "status": "dry_run",
                "action": "BUY",
                "gate": {"passed": True, "metrics": passing_backtest("TSLA")["metrics"]},
                "signal": {"signal": "TREND BUY", "trigger": "ema_vwap_momentum", "reason": "Trend confirmed."},
            }
        ])

        self.assertIn("PAPER TRADE", message)
        self.assertIn("TSLA", message)
        self.assertIn("Demo only. No real order was placed.", message)


if __name__ == "__main__":
    unittest.main()
