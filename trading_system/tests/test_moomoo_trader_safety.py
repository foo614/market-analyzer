import os
import sys
import types
import unittest

import pandas as pd

import trading_system.moomoo_trader as moomoo_trader


class MoomooTraderSafetyTest(unittest.TestCase):
    def setUp(self):
        self.original_env = os.environ.get("FUTU_TRD_ENV")
        self.original_allow = os.environ.get("CLAWDBOT_ALLOW_MOOMOO_LIVE")
        self.original_moomoo = sys.modules.get("moomoo")

        os.environ["FUTU_TRD_ENV"] = "REAL"
        os.environ["CLAWDBOT_ALLOW_MOOMOO_LIVE"] = "1"
        class DummyContext:
            def __init__(self, *args, **kwargs):
                pass

            def get_acc_list(self):
                return 0, [{"trd_env": "REAL", "acc_id": 123}]

            def get_market_snapshot(self, codes):
                return 0, pd.DataFrame([{"code": codes[0], "last_price": 250.0}])

            def place_order(self, **kwargs):
                return 0, {"order_id": "fake"}

            def close(self):
                pass

        sys.modules["moomoo"] = types.SimpleNamespace(
            OpenQuoteContext=DummyContext,
            OpenSecTradeContext=DummyContext,
            SecurityFirm=types.SimpleNamespace(NONE="NONE"),
            TrdSide=types.SimpleNamespace(BUY="BUY", SELL="SELL"),
            OrderType=types.SimpleNamespace(NORMAL="NORMAL"),
            TrdEnv=types.SimpleNamespace(REAL="REAL", SIMULATE="SIMULATE"),
            RET_OK=0,
        )

    def tearDown(self):
        if self.original_env is None:
            os.environ.pop("FUTU_TRD_ENV", None)
        else:
            os.environ["FUTU_TRD_ENV"] = self.original_env

        if self.original_allow is None:
            os.environ.pop("CLAWDBOT_ALLOW_MOOMOO_LIVE", None)
        else:
            os.environ["CLAWDBOT_ALLOW_MOOMOO_LIVE"] = self.original_allow

        if self.original_moomoo is None:
            sys.modules.pop("moomoo", None)
        else:
            sys.modules["moomoo"] = self.original_moomoo

    def test_real_mode_is_blocked_before_opend_connection(self):
        calls = []
        original_probe = moomoo_trader._ensure_opend_reachable
        moomoo_trader._ensure_opend_reachable = lambda host, port: calls.append((host, port))
        try:
            self.assertFalse(moomoo_trader.execute_moomoo_trade("TSLA", "BUY", 500))
            self.assertEqual(calls, [])
        finally:
            moomoo_trader._ensure_opend_reachable = original_probe


if __name__ == "__main__":
    unittest.main()
