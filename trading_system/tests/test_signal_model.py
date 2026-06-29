import unittest

from trading_system.signal_model import (
    ACCUMULATE,
    BUY,
    HOLD,
    STOP_LOSS,
    TAKE_PROFIT,
    category_title,
    category_trade_action,
    normalize_signal_category,
    payload_signal_category,
)


class SignalModelTest(unittest.TestCase):
    def test_aliases_normalize_to_canonical_categories(self):
        self.assertEqual(normalize_signal_category("TREND BUY"), BUY)
        self.assertEqual(normalize_signal_category("ACCUMULATE WATCH"), ACCUMULATE)
        self.assertEqual(normalize_signal_category("STOP LOSS WATCH"), STOP_LOSS)
        self.assertEqual(normalize_signal_category("TAKE PROFIT WATCH"), TAKE_PROFIT)
        self.assertEqual(normalize_signal_category("HOLD / WATCH"), HOLD)

    def test_trade_actions_keep_alert_only_categories_out_of_broker_route(self):
        self.assertEqual(category_trade_action(BUY), "BUY")
        self.assertIsNone(category_trade_action(ACCUMULATE))
        self.assertIsNone(category_trade_action(HOLD))
        self.assertEqual(category_trade_action(STOP_LOSS), "SELL")
        self.assertEqual(category_trade_action(TAKE_PROFIT), "SELL")

    def test_sell_categories_keep_distinct_titles(self):
        self.assertEqual(category_title(STOP_LOSS), "STOP LOSS")
        self.assertEqual(category_title(TAKE_PROFIT), "TAKE PROFIT")

    def test_payload_category_prefers_explicit_category_then_signal_text(self):
        self.assertEqual(payload_signal_category({"signalCategory": "TAKE_PROFIT", "signal": "TREND SELL"}), TAKE_PROFIT)
        self.assertEqual(payload_signal_category({"signal": "TREND SELL", "tradeAction": "SELL"}), STOP_LOSS)
        self.assertEqual(payload_signal_category({"tradeAction": "BUY"}), BUY)


if __name__ == "__main__":
    unittest.main()
