import io
import unittest

from trading_system.replay_harness import main, run_pipeline_replay, run_replay


class ReplayHarnessCliTest(unittest.TestCase):
    def test_run_replay_reports_dry_run_buy_without_broker_calls(self):
        results = run_replay(["buy"])

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertTrue(result["passed"])
        self.assertEqual(result["name"], "buy")
        self.assertEqual(result["symbol"], "TSLA")
        self.assertEqual(result["action"], "BUY")
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["buy_calls"], [])
        self.assertEqual(result["close_calls"], [])

    def test_run_replay_covers_alert_only_and_sell_categories_without_broker_calls(self):
        results = run_replay(["accumulate", "hold", "stop-loss", "take-profit"])

        by_name = {result["name"]: result for result in results}
        self.assertEqual(by_name["accumulate"]["action"], "HOLD")
        self.assertEqual(by_name["accumulate"]["status"], "no_signal")
        self.assertEqual(by_name["hold"]["action"], "HOLD")
        self.assertEqual(by_name["hold"]["status"], "no_signal")
        self.assertEqual(by_name["stop-loss"]["action"], "SELL")
        self.assertEqual(by_name["stop-loss"]["status"], "dry_run")
        self.assertEqual(by_name["take-profit"]["action"], "SELL")
        self.assertEqual(by_name["take-profit"]["status"], "dry_run")
        for result in results:
            self.assertTrue(result["passed"])
            self.assertEqual(result["buy_calls"], [])
            self.assertEqual(result["close_calls"], [])

    def test_run_pipeline_replay_routes_quant_to_execution_without_broker_calls(self):
        results = run_pipeline_replay(["buy", "accumulate", "take-profit"])

        by_name = {result["name"]: result for result in results}
        self.assertEqual(by_name["buy"]["status"], "dry_run")
        self.assertEqual(by_name["buy"]["action"], "BUY")
        self.assertEqual(by_name["accumulate"]["status"], "no_trade_signal")
        self.assertEqual(by_name["take-profit"]["status"], "dry_run")
        self.assertEqual(by_name["take-profit"]["action"], "SELL")
        for result in results:
            self.assertTrue(result["passed"])
            self.assertEqual(result["buy_calls"], [])
            self.assertEqual(result["close_calls"], [])
            self.assertNotIn("trade_success", result["notification_types"])
            self.assertNotIn("trade_failure", result["notification_types"])

    def test_main_all_scenarios_prints_compact_summary_and_returns_zero(self):
        stdout = io.StringIO()

        exit_code = main(["--scenario", "all"], stdout=stdout)

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("PASS buy TSLA BUY dry_run", output)
        self.assertIn("PASS accumulate TQQQ HOLD no_signal", output)
        self.assertIn("PASS stop-loss SOXL SELL dry_run", output)
        self.assertIn("PASS take-profit TSLA SELL dry_run", output)
        self.assertIn("PASS hold SOXL HOLD no_signal", output)
        self.assertIn("Replay complete: 5 passed, 0 failed", output)

    def test_main_named_scenario_runs_only_that_scenario(self):
        stdout = io.StringIO()

        exit_code = main(["--scenario", "buy"], stdout=stdout)

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("PASS buy TSLA BUY dry_run", output)
        self.assertNotIn("accumulate", output)
        self.assertNotIn("hold", output)
        self.assertIn("Replay complete: 1 passed, 0 failed", output)

    def test_main_can_include_pipeline_replay(self):
        stdout = io.StringIO()

        exit_code = main(["--scenario", "buy", "--include-pipeline"], stdout=stdout)

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("PASS buy TSLA BUY dry_run", output)
        self.assertIn("PIPELINE PASS buy TSLA BUY dry_run", output)
        self.assertIn("Pipeline replay complete: 1 passed, 0 failed", output)

    def test_main_returns_nonzero_for_unknown_scenario(self):
        stdout = io.StringIO()

        exit_code = main(["--scenario", "unknown"], stdout=stdout)

        self.assertEqual(exit_code, 2)
        self.assertIn("Unknown scenario: unknown", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
