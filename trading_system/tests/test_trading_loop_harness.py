import os
import tempfile
import unittest

import trading_system.agents.execution_agent as execution_module
from trading_system.agents.execution_agent import ExecutionAgent
from trading_system.agents.paper_trade_agent import PaperTradeAgent
from trading_system.paper_trade_state import PaperTradeState
from trading_system.tests.harness import (
    FakeBroker,
    FakeNotifier,
    ReplayScenario,
    failing_backtest,
    make_frame,
    passing_backtest,
)


def buy_scenario(symbol="TSLA"):
    return ReplayScenario(
        symbol=symbol,
        signal={
            "symbol": symbol,
            "action": "BUY",
            "tradeAction": "BUY",
            "signal": "TREND BUY",
            "trigger": "ema_vwap_momentum",
            "price": 120.0,
            "reason": "Trend confirmed.",
        },
        expected_action="BUY",
        expected_status="dry_run",
    )


class TradingLoopHarnessTest(unittest.TestCase):
    def make_state(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return PaperTradeState(os.path.join(tmp.name, "state.json"))

    def make_agent(self, scenario, mode="dry-run", backtest_runner=passing_backtest, broker=None, notifier=None):
        broker = broker or FakeBroker()
        notifier = notifier or FakeNotifier()
        frame = scenario.frame if scenario.frame is not None else make_frame()
        agent = PaperTradeAgent(
            mode=mode,
            symbols=[scenario.symbol],
            state=self.make_state(),
            backtest_runner=backtest_runner,
            latest_fetcher=lambda symbol: frame,
            signal_analyzer=lambda frame, symbol, timeframe, in_position: dict(scenario.signal, symbol=symbol),
            demo_buy=broker.buy,
            demo_close=broker.close,
            demo_has_position=broker.has_position,
            notifier=notifier,
        )
        return agent, broker, notifier

    def test_passing_buy_signal_dry_run_records_no_broker_call(self):
        scenario = buy_scenario("TSLA")
        agent, broker, notifier = self.make_agent(scenario, mode="dry-run")

        result = agent.evaluate_signal(scenario.signal)

        self.assertEqual(result["status"], scenario.expected_status)
        self.assertEqual(result["action"], scenario.expected_action)
        self.assertEqual(broker.buy_calls, [])
        self.assertEqual(broker.close_calls, [])
        self.assertIn("PAPER TRADE", notifier.messages[0])

    def test_failing_backtest_gate_skips_demo_execute_broker_calls(self):
        scenario = buy_scenario("TQQQ")
        scenario = ReplayScenario(
            symbol=scenario.symbol,
            signal=scenario.signal,
            expected_action="HOLD",
            expected_status="gate_failed",
        )
        agent, broker, notifier = self.make_agent(
            scenario,
            mode="demo-execute",
            backtest_runner=failing_backtest,
        )

        result = agent.evaluate_signal(scenario.signal)

        self.assertEqual(result["status"], scenario.expected_status)
        self.assertEqual(result["action"], scenario.expected_action)
        self.assertEqual(broker.buy_calls, [])
        self.assertEqual(broker.close_calls, [])
        self.assertIn("TQQQ", notifier.messages[0])

    def test_run_once_replays_hold_signal_without_broker_call(self):
        scenario = ReplayScenario(
            symbol="SOXL",
            frame=make_frame(),
            signal={
                "symbol": "SOXL",
                "tradeAction": None,
                "signal": "HOLD",
                "trigger": "no_trigger",
                "price": 50.0,
                "reason": "No fresh signal.",
            },
            expected_action="HOLD",
            expected_status="no_signal",
        )
        agent, broker, notifier = self.make_agent(scenario, mode="dry-run")

        result = agent.run_once(["SOXL"])[0]

        self.assertEqual(result["status"], scenario.expected_status)
        self.assertEqual(result["action"], scenario.expected_action)
        self.assertEqual(broker.buy_calls, [])
        self.assertEqual(broker.close_calls, [])
        self.assertIn("SOXL", notifier.messages[0])

    def test_repeated_demo_execute_buy_hits_cooldown_after_first_fake_buy(self):
        scenario = buy_scenario("TSLA")
        broker = FakeBroker()
        agent, broker, _notifier = self.make_agent(scenario, mode="demo-execute", broker=broker)

        first = agent.evaluate_signal(scenario.signal)
        second = agent.evaluate_signal(scenario.signal)

        self.assertEqual(first["status"], "executed")
        self.assertEqual(second["status"], "cooldown")
        self.assertEqual(broker.buy_calls, [("TSLA", "BUY", 100.0)])
        self.assertEqual(broker.close_calls, [])

    def test_demo_execute_sell_closes_fake_position(self):
        scenario = ReplayScenario(
            symbol="TSLA",
            signal={
                "symbol": "TSLA",
                "action": "SELL",
                "tradeAction": "SELL",
                "signal": "TREND SELL",
                "trigger": "atr_trailing_stop",
                "price": 110.0,
                "reason": "Trailing stop broke.",
            },
            expected_action="SELL",
            expected_status="executed",
        )
        broker = FakeBroker(positions={"TSLA": True})
        agent, broker, _notifier = self.make_agent(scenario, mode="demo-execute", broker=broker)

        result = agent.evaluate_signal(scenario.signal)

        self.assertEqual(result["status"], scenario.expected_status)
        self.assertEqual(result["action"], scenario.expected_action)
        self.assertEqual(broker.buy_calls, [])
        self.assertEqual(broker.close_calls, ["TSLA"])
        self.assertFalse(broker.has_position("TSLA"))

    def test_execution_agent_etoro_path_uses_paper_gate_and_manual_recommendation(self):
        original_publish = execution_module.bus.publish
        original_paper_agent = execution_module.PaperTradeAgent
        original_check_circuit_breaker = execution_module.check_circuit_breaker
        original_get_execution_broker = execution_module.get_execution_broker
        original_get_demo_execution_mode = execution_module.get_demo_execution_mode

        published = []
        created_agents = []
        broker = FakeBroker()

        def paper_agent_factory(**kwargs):
            agent = PaperTradeAgent(
                **kwargs,
                state=self.make_state(),
                backtest_runner=passing_backtest,
                latest_fetcher=lambda symbol: make_frame(),
                signal_analyzer=lambda frame, symbol, timeframe, in_position: buy_scenario(symbol).signal,
                demo_buy=broker.buy,
                demo_close=broker.close,
                demo_has_position=broker.has_position,
            )
            created_agents.append(agent)
            return agent

        execution_module.bus.publish = lambda topic, payload: published.append((topic, payload))
        execution_module.PaperTradeAgent = paper_agent_factory
        execution_module.check_circuit_breaker = lambda: False
        execution_module.get_execution_broker = lambda: "etoro"
        execution_module.get_demo_execution_mode = lambda: "dry-run"

        agent = ExecutionAgent()
        try:
            result = agent.process_signal({
                "symbol": "TSLA",
                "action": "BUY",
                "amount": 500,
                "reason": "Trend confirmed.",
                "signal": "TREND BUY",
                "trigger": "ema_vwap_momentum",
            })
        finally:
            agent.sub.close(0)
            execution_module.bus.publish = original_publish
            execution_module.PaperTradeAgent = original_paper_agent
            execution_module.check_circuit_breaker = original_check_circuit_breaker
            execution_module.get_execution_broker = original_get_execution_broker
            execution_module.get_demo_execution_mode = original_get_demo_execution_mode

        published_types = [payload["type"] for _topic, payload in published]
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(len(created_agents), 1)
        self.assertIn("paper_trade_report", published_types)
        self.assertIn("real_recommendation", published_types)
        self.assertNotIn("trade_success", published_types)
        self.assertEqual(broker.buy_calls, [])
        self.assertEqual(broker.close_calls, [])


if __name__ == "__main__":
    unittest.main()
