import unittest
import time

import pandas as pd

from trading_system.paper_trade_backtester import (
    BacktestGateConfig,
    apply_backtest_gate,
    generate_trend_signals,
    run_backtest_for_frame,
)
from trading_system.signal_model import ACCUMULATE, BUY, TAKE_PROFIT


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
    return pd.DataFrame(rows, index=pd.date_range("2026-01-01", periods=len(closes), freq="5min"))


class PaperTradeBacktesterTest(unittest.TestCase):
    def test_generate_trend_signals_reuses_trend_strategy_buy_logic(self):
        closes = [100 + (i * 0.55) for i in range(80)]
        volumes = [1000] * 55 + [1400] * 25

        result = generate_trend_signals(make_frame(closes, volumes), "TSLA")

        self.assertIn(1, set(result["Signal"]))
        buy_rows = result[result["Signal"] == 1]
        self.assertEqual(buy_rows.iloc[0]["SignalLabel"], "TREND BUY")
        self.assertEqual(buy_rows.iloc[0]["SignalCategory"], BUY)
        self.assertEqual(buy_rows.iloc[0]["TradeAction"], "BUY")

    def test_accumulate_watch_is_not_a_simulated_buy_entry(self):
        closes = [100 + (i * 0.4) for i in range(65)]
        closes = closes[:-1] + [closes[-1] - 1.0]
        volumes = [1000] * 55 + [1300] * 10

        result = generate_trend_signals(make_frame(closes, volumes), "TQQQ")
        accumulate_rows = result[result["SignalLabel"] == "ACCUMULATE WATCH"]

        self.assertFalse(accumulate_rows.empty)
        self.assertEqual(set(accumulate_rows["Signal"]), {0})
        self.assertEqual(set(accumulate_rows["SignalCategory"]), {ACCUMULATE})
        self.assertEqual(set(accumulate_rows["TradeAction"].dropna()), set())

    def test_in_position_overbought_extension_emits_take_profit_exit(self):
        closes = [100 + (i * 0.5) for i in range(80)] + [150, 160, 172, 185, 200]

        result = generate_trend_signals(make_frame(closes), "TSLA")
        take_profit_rows = result[result["SignalCategory"] == TAKE_PROFIT]

        self.assertFalse(take_profit_rows.empty)
        self.assertEqual(take_profit_rows.iloc[0]["SignalLabel"], "TAKE PROFIT WATCH")
        self.assertEqual(take_profit_rows.iloc[0]["TradeAction"], "SELL")
        self.assertEqual(take_profit_rows.iloc[0]["Signal"], -1)

    def test_generate_trend_signals_is_fast_enough_for_intraday_history(self):
        closes = [100 + (i * 0.03) for i in range(500)]
        start = time.perf_counter()

        result = generate_trend_signals(make_frame(closes), "TSLA")

        elapsed = time.perf_counter() - start
        self.assertEqual(len(result), 500)
        self.assertLess(elapsed, 2.0)

    def test_run_backtest_for_frame_returns_numeric_metrics(self):
        closes = [100] * 10 + [105, 110, 115, 120]
        frame = make_frame(closes)
        frame["Signal"] = [0] * 10 + [1, 0, 0, -1]

        result = run_backtest_for_frame("TSLA", frame, use_existing_signals=True)

        metrics = result["metrics"]
        self.assertGreater(metrics["total_return_pct"], 0)
        self.assertEqual(metrics["closed_trades"], 1)
        self.assertEqual(metrics["win_rate_pct"], 100.0)
        self.assertIn("buy_hold_return_pct", metrics)

    def test_apply_backtest_gate_passes_when_thresholds_are_met(self):
        result = {
            "symbol": "TSLA",
            "metrics": {
                "closed_trades": 4,
                "total_return_pct": 12.0,
                "win_rate_pct": 50.0,
                "max_drawdown_pct": 10.0,
                "buy_hold_return_pct": 8.0,
                "buy_hold_max_drawdown_pct": 18.0,
            },
        }

        gate = apply_backtest_gate(result, "TSLA")

        self.assertTrue(gate["passed"])
        self.assertEqual(gate["reasons"], [])

    def test_apply_backtest_gate_fails_closed_on_drawdown(self):
        result = {
            "symbol": "TQQQ",
            "metrics": {
                "closed_trades": 4,
                "total_return_pct": 12.0,
                "win_rate_pct": 60.0,
                "max_drawdown_pct": 45.0,
                "buy_hold_return_pct": 8.0,
                "buy_hold_max_drawdown_pct": 40.0,
            },
        }

        gate = apply_backtest_gate(result, "TQQQ")

        self.assertFalse(gate["passed"])
        self.assertIn("max_drawdown", " ".join(gate["reasons"]))

    def test_apply_backtest_gate_can_use_custom_thresholds(self):
        result = {
            "symbol": "SPCX",
            "metrics": {
                "closed_trades": 1,
                "total_return_pct": 2.0,
                "win_rate_pct": 100.0,
                "max_drawdown_pct": 5.0,
                "buy_hold_return_pct": 10.0,
                "buy_hold_max_drawdown_pct": 8.0,
            },
        }
        config = BacktestGateConfig(min_closed_trades=1, require_beats_buy_hold_or_lower_drawdown=False)

        gate = apply_backtest_gate(result, "SPCX", config=config)

        self.assertTrue(gate["passed"])


if __name__ == "__main__":
    unittest.main()
