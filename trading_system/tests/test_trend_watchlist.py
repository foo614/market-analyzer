import os
import tempfile
import unittest

import trading_system.config as config
from trading_system.config import get_trend_watchlist


class TrendWatchlistTest(unittest.TestCase):
    def setUp(self):
        self.original = os.environ.get("CLAWDBOT_TREND_WATCHLIST")
        os.environ.pop("CLAWDBOT_TREND_WATCHLIST", None)

    def tearDown(self):
        if self.original is None:
            os.environ.pop("CLAWDBOT_TREND_WATCHLIST", None)
        else:
            os.environ["CLAWDBOT_TREND_WATCHLIST"] = self.original

    def test_default_watchlist_is_configured_list(self):
        self.assertEqual(get_trend_watchlist(), ["TSLA", "SOXL", "TQQQ", "SPCX"])

    def test_env_watchlist_is_normalized_and_deduped(self):
        os.environ["CLAWDBOT_TREND_WATCHLIST"] = "tsla, tqqq TSLA,unh"

        self.assertEqual(get_trend_watchlist(), ["TSLA", "TQQQ", "UNH"])

    def test_tools_local_overrides_tools_md_credentials(self):
        original_tools_path = config.TOOLS_PATH
        original_tools_local_path = config.TOOLS_LOCAL_PATH
        original_cache = config._credentials_cache
        original_cache_mtime = config._credentials_cache_mtime

        with tempfile.TemporaryDirectory() as temp_dir:
            tools_path = os.path.join(temp_dir, "TOOLS.md")
            tools_local_path = os.path.join(temp_dir, "TOOLS.local.md")

            with open(tools_path, "w", encoding="utf-8") as f:
                f.write("- **OpenRouter API Key:** `base-key`\n")
            with open(tools_local_path, "w", encoding="utf-8") as f:
                f.write("- **OpenRouter API Key:** `local-key`\n")

            try:
                config.TOOLS_PATH = tools_path
                config.TOOLS_LOCAL_PATH = tools_local_path
                config._credentials_cache = None
                config._credentials_cache_mtime = None

                self.assertEqual(config.get_credential("openrouter_key"), "local-key")
            finally:
                config.TOOLS_PATH = original_tools_path
                config.TOOLS_LOCAL_PATH = original_tools_local_path
                config._credentials_cache = original_cache
                config._credentials_cache_mtime = original_cache_mtime


if __name__ == "__main__":
    unittest.main()
