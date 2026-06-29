import unittest

import trading_system.agents.execution_agent as execution_module
from trading_system.agents.execution_agent import ExecutionAgent
from trading_system.signal_model import STOP_LOSS, TAKE_PROFIT


class FakePaperTradeAgent:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        FakePaperTradeAgent.instances.append(self)

    def evaluate_signal(self, signal):
        self.calls.append(signal)
        self.kwargs["notifier"]("paper report")
        return {
            "symbol": signal["symbol"],
            "status": self.kwargs.get("status", "dry_run"),
            "action": signal["action"],
            "gate": {"passed": True, "metrics": {"total_return_pct": 5.0}},
            "signal": signal,
        }


class ExecutionAgentTest(unittest.TestCase):
    def setUp(self):
        self.original_publish = execution_module.bus.publish
        self.original_paper_agent = execution_module.PaperTradeAgent
        self.original_check_circuit_breaker = execution_module.check_circuit_breaker
        self.original_get_execution_broker = execution_module.get_execution_broker
        self.original_get_demo_execution_mode = execution_module.get_demo_execution_mode
        self.original_execute_moomoo_trade = execution_module.execute_moomoo_trade

        self.published = []
        self.moomoo_trade_calls = []
        FakePaperTradeAgent.instances = []
        execution_module.bus.publish = lambda topic, payload: self.published.append((topic, payload))
        execution_module.PaperTradeAgent = FakePaperTradeAgent
        execution_module.check_circuit_breaker = lambda: False
        execution_module.get_execution_broker = lambda: "etoro"
        execution_module.get_demo_execution_mode = lambda: "dry-run"
        execution_module.execute_moomoo_trade = lambda *args: self.moomoo_trade_calls.append(args) or True
        self.agent = ExecutionAgent()

    def tearDown(self):
        self.agent.sub.close(0)
        execution_module.bus.publish = self.original_publish
        execution_module.PaperTradeAgent = self.original_paper_agent
        execution_module.check_circuit_breaker = self.original_check_circuit_breaker
        execution_module.get_execution_broker = self.original_get_execution_broker
        execution_module.get_demo_execution_mode = self.original_get_demo_execution_mode
        execution_module.execute_moomoo_trade = self.original_execute_moomoo_trade

    def test_etoro_signal_routes_through_paper_agent_dry_run_by_default(self):
        result = self.agent.process_signal({
            "symbol": "TSLA",
            "action": "BUY",
            "amount": 500,
            "reason": "Trend confirmed.",
            "signal": "TREND BUY",
            "trigger": "ema_vwap_momentum",
        })

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(len(FakePaperTradeAgent.instances), 1)
        instance = FakePaperTradeAgent.instances[0]
        self.assertEqual(instance.kwargs["mode"], "dry-run")
        self.assertEqual(instance.kwargs["trade_amount"], 500)
        self.assertEqual(instance.calls[0]["symbol"], "TSLA")
        self.assertEqual(instance.calls[0]["tradeAction"], "BUY")
        self.assertTrue(any(payload["type"] == "paper_trade_report" for _, payload in self.published))
        self.assertTrue(any(payload["type"] == "real_recommendation" for _, payload in self.published))
        self.assertFalse(any(payload["type"] == "trade_success" for _, payload in self.published))

    def test_etoro_demo_execute_mode_is_explicitly_passed_to_paper_agent(self):
        execution_module.get_demo_execution_mode = lambda: "demo-execute"

        self.agent.process_signal({
            "symbol": "SOXL",
            "action": "BUY",
            "amount": 300,
            "reason": "Trend confirmed.",
        })

        self.assertEqual(FakePaperTradeAgent.instances[0].kwargs["mode"], "demo-execute")

    def test_moomoo_signal_routes_through_paper_gate_without_auto_execution(self):
        execution_module.get_execution_broker = lambda: "moomoo"

        result = self.agent.process_signal({
            "symbol": "TSLA",
            "action": "BUY",
            "amount": 500,
            "reason": "Trend confirmed.",
            "signal": "TREND BUY",
            "trigger": "ema_vwap_momentum",
        })

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(self.moomoo_trade_calls, [])
        self.assertEqual(len(FakePaperTradeAgent.instances), 1)
        self.assertTrue(any(payload["type"] == "paper_trade_report" for _, payload in self.published))
        self.assertTrue(any(payload["type"] == "real_recommendation" for _, payload in self.published))
        self.assertFalse(any(payload["type"] in {"trade_success", "trade_failure"} for _, payload in self.published))

    def test_sell_recommendations_keep_stop_loss_and_take_profit_labels(self):
        cases = [
            (STOP_LOSS, "TREND SELL", "STOP LOSS TSLA"),
            (TAKE_PROFIT, "TAKE PROFIT WATCH", "TAKE PROFIT TSLA"),
        ]

        for category, signal, expected_label in cases:
            with self.subTest(category=category):
                self.published = []
                result = self.agent.process_signal({
                    "symbol": "TSLA",
                    "action": "SELL",
                    "amount": 500,
                    "reason": "Category-specific sell recommendation.",
                    "signal": signal,
                    "signalCategory": category,
                    "trigger": "test_trigger",
                })

                self.assertEqual(result["action"], "SELL")
                recommendations = [
                    payload["text"]
                    for _topic, payload in self.published
                    if payload["type"] == "real_recommendation"
                ]
                self.assertEqual(len(recommendations), 1)
                self.assertIn(expected_label, recommendations[0])


if __name__ == "__main__":
    unittest.main()
