import unittest
import os
import tempfile

import trading_system.agents.quant_agent as quant_module
from trading_system.agents.quant_agent import QuantAgent
from trading_system.signal_model import BUY, ACCUMULATE, STOP_LOSS, TAKE_PROFIT


class QuantAgentTrendPayloadTest(unittest.TestCase):
    def setUp(self):
        self.original_publish = quant_module.bus.publish
        self.published = []
        self.agent = None
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.ledger_path = os.path.join(self.temp_dir.name, "signal_ledger.json")
        quant_module.bus.publish = lambda topic, payload: self.published.append((topic, payload))

    def tearDown(self):
        if self.agent is not None:
            self.agent.sub.close(0)
        quant_module.bus.publish = self.original_publish

    def _use_temp_ledger(self, agent):
        agent.signal_ledger_file = self.ledger_path
        agent.signal_ledger = {}
        return agent

    def test_trend_buy_payload_emits_trade_signal(self):
        self.agent = self._use_temp_ledger(QuantAgent())
        self.agent._ask_llm_opinion = lambda *args, **kwargs: (None, None)

        action, row = self.agent.evaluate_indicator_signal({
            "source": "trend_monitor",
            "strategy": "aggressive_ema_vwap_trend",
            "symbol": "TSLA",
            "price": 250.0,
            "rsi": 67.0,
            "atr": 4.5,
            "obvStatus": "Accumulating",
            "isBullish": True,
            "trendStatus": "Bullish",
            "ema9": 249.0,
            "ema21": 247.0,
            "ema50": 241.0,
            "vwap": 246.5,
            "macdHist": 0.42,
            "signal": "TREND BUY",
            "signalCategory": BUY,
            "tradeAction": "BUY",
            "trigger": "ema_vwap_momentum",
            "reason": "EMA/VWAP trend continuation.",
        })

        self.assertEqual(action, "BUY")
        self.assertIn("BUY", row)
        self.assertEqual(len(self.published), 1)
        topic, payload = self.published[0]
        self.assertEqual(topic, "trade_signals")
        self.assertEqual(payload["symbol"], "TSLA")
        self.assertEqual(payload["action"], "BUY")
        self.assertEqual(payload["signalCategory"], BUY)
        self.assertEqual(payload["reason"], "EMA/VWAP trend continuation.")

    def test_accumulate_payload_is_alert_only(self):
        self.agent = self._use_temp_ledger(QuantAgent())
        self.agent._ask_llm_opinion = lambda *args, **kwargs: (None, None)

        action, row = self.agent.evaluate_indicator_signal({
            "source": "trend_monitor",
            "strategy": "aggressive_ema_vwap_trend",
            "symbol": "TQQQ",
            "price": 70.0,
            "rsi": 58.0,
            "atr": 2.5,
            "obvStatus": "Accumulating",
            "isBullish": True,
            "trendStatus": "Bullish",
            "signal": "ACCUMULATE WATCH",
            "signalCategory": ACCUMULATE,
            "tradeAction": None,
            "trigger": "trend_pullback",
            "reason": "Pullback is holding EMA21 with OBV accumulation.",
        })

        self.assertEqual(action, "ACCUMULATE")
        self.assertIn("ACCUMULATE", row)
        self.assertEqual(self.published, [])

    def test_stop_loss_and_take_profit_use_separate_category_cooldowns(self):
        self.agent = self._use_temp_ledger(QuantAgent())
        self.agent._ask_llm_opinion = lambda *args, **kwargs: (None, None)
        base_payload = {
            "source": "trend_monitor",
            "strategy": "aggressive_ema_vwap_trend",
            "symbol": "TSLA",
            "price": 250.0,
            "rsi": 82.0,
            "atr": 4.5,
            "obvStatus": "Accumulating",
            "isBullish": True,
            "trendStatus": "Bullish",
            "tradeAction": "SELL",
            "latestBarTs": "2026-06-24 10:00:00",
        }

        self.agent.evaluate_indicator_signal(dict(
            base_payload,
            signal="TREND SELL",
            signalCategory=STOP_LOSS,
            trigger="atr_trailing_stop",
            reason="Price broke the ATR trailing stop.",
        ))
        self.agent.evaluate_indicator_signal(dict(
            base_payload,
            signal="TAKE PROFIT WATCH",
            signalCategory=TAKE_PROFIT,
            trigger="overbought_extension",
            reason="Position is extended; consider taking profit.",
        ))

        self.assertEqual(len(self.published), 2)
        self.assertEqual(self.published[0][1]["signalCategory"], STOP_LOSS)
        self.assertEqual(self.published[1][1]["signalCategory"], TAKE_PROFIT)
        self.assertEqual(self.published[0][1]["action"], "SELL")
        self.assertEqual(self.published[1][1]["action"], "SELL")

    def test_signal_ledger_suppresses_same_bar_after_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger_path = os.path.join(temp_dir, "signal_ledger.json")
            payload = {
                "source": "trend_monitor",
                "strategy": "aggressive_ema_vwap_trend",
                "symbol": "TSLA",
                "price": 250.0,
                "rsi": 67.0,
                "atr": 4.5,
                "obvStatus": "Accumulating",
                "isBullish": True,
                "trendStatus": "Bullish",
                "ema9": 249.0,
                "ema21": 247.0,
                "ema50": 241.0,
                "vwap": 246.5,
                "macdHist": 0.42,
                "signal": "TREND BUY",
                "signalCategory": BUY,
                "tradeAction": "BUY",
                "trigger": "ema_vwap_momentum",
                "latestBarTs": "2026-06-17 10:00:00",
                "reason": "EMA/VWAP trend continuation.",
            }

            first = QuantAgent()
            first.signal_ledger_file = ledger_path
            first.signal_ledger = {}
            first._ask_llm_opinion = lambda *args, **kwargs: (None, None)
            first.evaluate_indicator_signal(payload)
            first.sub.close(0)

            second = QuantAgent()
            self.agent = second
            second.signal_ledger_file = ledger_path
            second.signal_ledger = second._load_signal_ledger()
            second._ask_llm_opinion = lambda *args, **kwargs: (None, None)
            second.evaluate_indicator_signal(payload)

            self.assertEqual(len(self.published), 1)


if __name__ == "__main__":
    unittest.main()
