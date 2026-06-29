import unittest

from trading_system.news_telegram_monitor import (
    _format_digest,
    _is_related,
    _normalize_news_item,
    _select_new_items,
)


class NewsTelegramMonitorTest(unittest.TestCase):
    def test_normalizes_nested_yfinance_news_item(self):
        item = {
            "content": {
                "id": "abc123",
                "title": "SpaceX stock jumps after IPO debut",
                "summary": "Shares extend gains.",
                "provider": {"displayName": "Yahoo Finance"},
                "canonicalUrl": {"url": "https://finance.yahoo.com/news/spcx"},
                "pubDate": "2026-06-16T12:00:00Z",
            }
        }

        normalized = _normalize_news_item("SPCX", item)

        self.assertEqual(normalized["id"], "abc123")
        self.assertEqual(normalized["symbol"], "SPCX")
        self.assertEqual(normalized["title"], "SpaceX stock jumps after IPO debut")
        self.assertEqual(normalized["publisher"], "Yahoo Finance")
        self.assertEqual(normalized["url"], "https://finance.yahoo.com/news/spcx")

    def test_filters_related_items_by_symbol_or_keywords(self):
        spcx_item = {"symbol": "SPCX", "title": "Unrelated headline", "summary": ""}
        keyword_item = {"symbol": "SPY", "title": "Fed decision moves Nasdaq futures", "summary": ""}
        unrelated_item = {"symbol": "QQQ", "title": "Monthly income ETF distribution", "summary": ""}

        self.assertTrue(_is_related(spcx_item, ["SPCX"], ["fed", "nasdaq"]))
        self.assertTrue(_is_related(keyword_item, ["SPCX"], ["fed", "nasdaq"]))
        self.assertFalse(_is_related(unrelated_item, ["SPCX"], ["fed", "nasdaq"]))

    def test_select_new_items_dedupes_seen_ids(self):
        items = [
            {"id": "1", "title": "Already seen"},
            {"id": "2", "title": "Fresh news"},
        ]
        state = {"seen_ids": ["1"]}

        selected = _select_new_items(items, state, limit=5)

        self.assertEqual([item["id"] for item in selected], ["2"])

    def test_format_digest_is_action_oriented(self):
        message = _format_digest([
            {
                "symbol": "SPCX",
                "title": "SpaceX stock jumps for second day",
                "summary": "Shares climb after debut.",
                "publisher": "Yahoo Finance",
                "url": "https://finance.yahoo.com/news/spcx",
                "published_at": "2026-06-16T12:00:00Z",
            }
        ])

        self.assertIn("FINANCIAL NEWS WATCH", message)
        self.assertIn("SPCX", message)
        self.assertIn("SpaceX stock jumps", message)
        self.assertIn("Trading read", message)


if __name__ == "__main__":
    unittest.main()
