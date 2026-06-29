"""
Deterministic dry-run replay harness for the paper-trade loop.
"""

import argparse
import os
import tempfile
from dataclasses import dataclass, field

import pandas as pd

from trading_system.agents.paper_trade_agent import PaperTradeAgent
from trading_system.paper_trade_state import PaperTradeState
from trading_system.signal_model import ACCUMULATE, BUY, HOLD, STOP_LOSS, TAKE_PROFIT


@dataclass
class ReplayScenario:
    name: str
    symbol: str
    signal: dict
    expected_action: str
    expected_status: str
    signal_category: str
    gate_passes: bool = True
    in_position: bool = False
    use_run_once: bool = False
    frame: pd.DataFrame | None = None


@dataclass
class _FakeBroker:
    buy_calls: list = field(default_factory=list)
    close_calls: list = field(default_factory=list)

    def buy(self, symbol, action, amount):
        self.buy_calls.append((str(symbol).upper(), str(action).upper(), float(amount)))
        return True

    def close(self, symbol):
        self.close_calls.append(str(symbol).upper())
        return True

    def has_position(self, symbol):
        return False


@dataclass
class _CaptureNotifier:
    messages: list = field(default_factory=list)

    def __call__(self, text):
        self.messages.append(str(text))
        return True


def _make_frame(closes=None, volumes=None):
    closes = closes or [100 + (i * 0.5) for i in range(80)]
    volumes = volumes or [1200] * len(closes)
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


def _passing_backtest(symbol):
    return {
        "symbol": str(symbol).upper(),
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


def _failing_backtest(symbol):
    result = _passing_backtest(symbol)
    result["metrics"]["max_drawdown_pct"] = 80.0
    return result


def _scenarios():
    return {
        "buy": ReplayScenario(
            name="buy",
            symbol="TSLA",
            signal={
                "symbol": "TSLA",
                "action": "BUY",
                "tradeAction": "BUY",
                "signal": "TREND BUY",
                "signalCategory": BUY,
                "trigger": "ema_vwap_momentum",
                "price": 120.0,
                "reason": "Trend confirmed.",
            },
            expected_action="BUY",
            expected_status="dry_run",
            signal_category=BUY,
        ),
        "accumulate": ReplayScenario(
            name="accumulate",
            symbol="TQQQ",
            signal={
                "symbol": "TQQQ",
                "tradeAction": None,
                "signal": "ACCUMULATE WATCH",
                "signalCategory": ACCUMULATE,
                "trigger": "trend_pullback",
                "price": 70.0,
                "reason": "Pullback is holding trend support.",
            },
            expected_action="HOLD",
            expected_status="no_signal",
            signal_category=ACCUMULATE,
            use_run_once=True,
        ),
        "stop-loss": ReplayScenario(
            name="stop-loss",
            symbol="SOXL",
            signal={
                "symbol": "SOXL",
                "action": "SELL",
                "tradeAction": "SELL",
                "signal": "TREND SELL",
                "signalCategory": STOP_LOSS,
                "trigger": "atr_trailing_stop",
                "price": 45.0,
                "reason": "Price broke the ATR trailing stop.",
            },
            expected_action="SELL",
            expected_status="dry_run",
            signal_category=STOP_LOSS,
            in_position=True,
        ),
        "take-profit": ReplayScenario(
            name="take-profit",
            symbol="TSLA",
            signal={
                "symbol": "TSLA",
                "action": "SELL",
                "tradeAction": "SELL",
                "signal": "TAKE PROFIT WATCH",
                "signalCategory": TAKE_PROFIT,
                "trigger": "overbought_extension",
                "price": 150.0,
                "reason": "Position is extended; consider taking profit.",
            },
            expected_action="SELL",
            expected_status="dry_run",
            signal_category=TAKE_PROFIT,
            in_position=True,
        ),
        "hold": ReplayScenario(
            name="hold",
            symbol="SOXL",
            signal={
                "symbol": "SOXL",
                "tradeAction": None,
                "signal": "HOLD",
                "signalCategory": HOLD,
                "trigger": "no_trigger",
                "price": 50.0,
                "reason": "No fresh signal.",
            },
            expected_action="HOLD",
            expected_status="no_signal",
            signal_category=HOLD,
            use_run_once=True,
        ),
    }


def _select_scenarios(names):
    available = _scenarios()
    aliases = {
        "passing-buy": "buy",
        "hold-signal": "hold",
    }
    selected_names = []
    for name in names:
        if name == "all":
            selected_names.extend(available)
        elif aliases.get(name, name) in available:
            selected_names.append(aliases.get(name, name))
        else:
            raise ValueError(f"Unknown scenario: {name}")
    return [available[name] for name in dict.fromkeys(selected_names)]


def _run_scenario(scenario):
    broker = _FakeBroker()
    notifier = _CaptureNotifier()
    frame = scenario.frame if scenario.frame is not None else _make_frame()
    backtest_runner = _passing_backtest if scenario.gate_passes else _failing_backtest

    with tempfile.TemporaryDirectory() as tmp:
        state = PaperTradeState(os.path.join(tmp, "paper_trade_state.json"))
        if scenario.in_position:
            state.set_position(scenario.symbol, True, {"source": "replay_harness"})

        agent = PaperTradeAgent(
            mode="dry-run",
            symbols=[scenario.symbol],
            state=state,
            backtest_runner=backtest_runner,
            latest_fetcher=lambda symbol: frame,
            signal_analyzer=lambda frame, symbol, timeframe, in_position: dict(scenario.signal, symbol=symbol),
            demo_buy=broker.buy,
            demo_close=broker.close,
            demo_has_position=broker.has_position,
            notifier=notifier,
        )
        if scenario.use_run_once:
            result = agent.run_once([scenario.symbol])[0]
        else:
            result = agent.evaluate_signal(scenario.signal)

    passed = (
        result.get("status") == scenario.expected_status
        and result.get("action") == scenario.expected_action
        and broker.buy_calls == []
        and broker.close_calls == []
    )
    return {
        "name": scenario.name,
        "symbol": scenario.symbol,
        "action": result.get("action"),
        "status": result.get("status"),
        "expected_action": scenario.expected_action,
        "expected_status": scenario.expected_status,
        "passed": passed,
        "buy_calls": broker.buy_calls,
        "close_calls": broker.close_calls,
        "notifications": notifier.messages,
    }


def run_replay(scenarios=None):
    selected = _select_scenarios(scenarios or ["all"])
    return [_run_scenario(scenario) for scenario in selected]


def _run_pipeline_scenario(scenario):
    import trading_system.agents.execution_agent as execution_module
    import trading_system.agents.quant_agent as quant_module

    broker = _FakeBroker()
    published = []
    original_publish = quant_module.bus.publish
    original_paper_agent = execution_module.PaperTradeAgent
    original_check_circuit_breaker = execution_module.check_circuit_breaker
    original_get_execution_broker = execution_module.get_execution_broker
    original_get_demo_execution_mode = execution_module.get_demo_execution_mode
    quant = None
    execution = None

    def capture_publish(topic, payload):
        published.append((topic, payload))

    try:
        quant_module.bus.publish = capture_publish
        execution_module.bus.publish = capture_publish
        execution_module.check_circuit_breaker = lambda: False
        execution_module.get_execution_broker = lambda: "etoro"
        execution_module.get_demo_execution_mode = lambda: "dry-run"

        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, f"{scenario.name}_paper_state.json")
            quant_state_path = os.path.join(tmp, f"{scenario.name}_quant_state.json")
            ledger_path = os.path.join(tmp, f"{scenario.name}_signal_ledger.json")

            def paper_agent_factory(**kwargs):
                state = PaperTradeState(state_path)
                if scenario.in_position:
                    state.set_position(scenario.symbol, True, {"source": "pipeline_replay"})
                return PaperTradeAgent(
                    **kwargs,
                    state=state,
                    backtest_runner=_passing_backtest if scenario.gate_passes else _failing_backtest,
                    latest_fetcher=lambda symbol: scenario.frame if scenario.frame is not None else _make_frame(),
                    signal_analyzer=lambda frame, symbol, timeframe, in_position: dict(scenario.signal, symbol=symbol),
                    demo_buy=broker.buy,
                    demo_close=broker.close,
                    demo_has_position=broker.has_position,
                )

            execution_module.PaperTradeAgent = paper_agent_factory

            quant = quant_module.QuantAgent()
            quant.state_file = quant_state_path
            quant.state_data = {"date": "", "states": {}, "sentiments": {}}
            quant.signal_ledger_file = ledger_path
            quant.signal_ledger = {}
            quant.cooldowns = {}
            quant._ask_llm_opinion = lambda *args, **kwargs: (None, None)

            execution = execution_module.ExecutionAgent()
            quant.evaluate_indicator_signal(dict(scenario.signal))
            trade_signals = [payload for topic, payload in published if topic == "trade_signals"]

            if trade_signals:
                result = execution.process_signal(trade_signals[-1])
            else:
                result = {"symbol": scenario.symbol, "action": "HOLD", "status": "no_trade_signal"}
    finally:
        if quant is not None:
            quant.sub.close(0)
        if execution is not None:
            execution.sub.close(0)
        quant_module.bus.publish = original_publish
        execution_module.bus.publish = original_publish
        execution_module.PaperTradeAgent = original_paper_agent
        execution_module.check_circuit_breaker = original_check_circuit_breaker
        execution_module.get_execution_broker = original_get_execution_broker
        execution_module.get_demo_execution_mode = original_get_demo_execution_mode

    notification_types = [
        payload.get("type")
        for topic, payload in published
        if topic == "notifications" and isinstance(payload, dict)
    ]
    expected_status = "no_trade_signal" if scenario.expected_action == "HOLD" else scenario.expected_status
    passed = (
        result.get("status") == expected_status
        and result.get("action") == scenario.expected_action
        and broker.buy_calls == []
        and broker.close_calls == []
        and "trade_success" not in notification_types
        and "trade_failure" not in notification_types
    )
    return {
        "name": scenario.name,
        "symbol": scenario.symbol,
        "action": result.get("action"),
        "status": result.get("status"),
        "expected_action": scenario.expected_action,
        "expected_status": expected_status,
        "passed": passed,
        "buy_calls": broker.buy_calls,
        "close_calls": broker.close_calls,
        "notification_types": notification_types,
    }


def run_pipeline_replay(scenarios=None):
    selected = _select_scenarios(scenarios or ["all"])
    return [_run_pipeline_scenario(scenario) for scenario in selected]


def main(argv=None, stdout=None):
    stdout = stdout or None
    parser = argparse.ArgumentParser(description="Run deterministic dry-run paper-trade replay scenarios.")
    parser.add_argument(
        "--scenario",
        action="append",
        default=None,
        help="Scenario name to run. Use multiple times or pass 'all'.",
    )
    parser.add_argument(
        "--include-pipeline",
        action="store_true",
        help="Also route selected scenarios through QuantAgent and ExecutionAgent with fake paper dependencies.",
    )
    args = parser.parse_args(argv)

    def write(line):
        print(line, file=stdout)

    try:
        results = run_replay(args.scenario or ["all"])
    except ValueError as exc:
        write(str(exc))
        return 2

    passed = 0
    failed = 0
    for result in results:
        prefix = "PASS" if result["passed"] else "FAIL"
        if result["passed"]:
            passed += 1
        else:
            failed += 1
        write(f"{prefix} {result['name']} {result['symbol']} {result['action']} {result['status']}")

    write(f"Replay complete: {passed} passed, {failed} failed")

    if args.include_pipeline:
        pipeline_passed = 0
        pipeline_failed = 0
        for result in run_pipeline_replay(args.scenario or ["all"]):
            prefix = "PIPELINE PASS" if result["passed"] else "PIPELINE FAIL"
            if result["passed"]:
                pipeline_passed += 1
            else:
                pipeline_failed += 1
            write(f"{prefix} {result['name']} {result['symbol']} {result['action']} {result['status']}")
        write(f"Pipeline replay complete: {pipeline_passed} passed, {pipeline_failed} failed")
        failed += pipeline_failed

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
