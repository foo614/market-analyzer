import sys
import os
import time
from datetime import datetime
import json
import re

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.message_bus import bus
from logger import get_logger
from config import (
    get_portfolio_tickers, is_trading_day, is_premarket, is_market_open,
    YFINANCE_CACHE_DIR, SENTIMENT_POLL_INTERVAL, sleep_until_market
)
from llm_router import llm_router
import yfinance as yf

log = get_logger("SentimentAgent")


class SentimentAgent:
    """
    Scrapes recent news via yfinance for the tracked tickers.
    Sends headlines to LLMRouter (Gemini 2.5 Flash primary, Ollama fallback).
    Publishes output to 'market_data' queue.
    Now market-hours-aware with proper rate limiting.
    """
    def __init__(self):
        self.running = False
        log.info("SentimentAgent Initialized")

    def _get_tickers(self):
        """Get current ticker list (dynamic from eToro portfolio)."""
        return get_portfolio_tickers()

    def _extract_llm_json(self, raw_text):
        if not raw_text:
            return None

        text = raw_text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text, flags=re.IGNORECASE)

        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_str = False
        escape = False
        end = None

        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == "\"":
                    in_str = False
                continue

            if ch == "\"":
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        if end is None:
            return None

        candidate = text[start:end]
        try:
            result = json.loads(candidate)
        except Exception:
            try:
                import ast
                result = ast.literal_eval(candidate)
            except Exception:
                return None

        if isinstance(result, dict):
            return result
        return None

    def _parse_sentiment_payload(self, raw_text):
        result = self._extract_llm_json(raw_text)
        if not result:
            return None

        sentiment = result.get("sentiment", "Neutral")
        if sentiment not in ["Bullish", "Bearish", "Neutral"]:
            sentiment = "Neutral"
        reason = result.get("reason", "Analyzed headlines.")
        if not isinstance(reason, str) or not reason.strip():
            reason = "Analyzed headlines."
        return {"sentiment": sentiment, "reason": reason.strip()}

    def analyze_sentiment(self, symbol, headlines):
        cleaned = [h.strip() for h in headlines if isinstance(h, str) and h.strip()]
        if not cleaned:
            return "Neutral", "No headlines"

        headlines_text = "\n".join([f"- {h}" for h in cleaned])
        base_prompt = (
            f"You are a quantitative trading sentiment analyzer.\n"
            f"Review these recent news headlines for {symbol}.\n"
            f"Classify short-term sentiment strictly as Bullish, Bearish, or Neutral.\n"
            f"Return ONLY a valid JSON object with keys sentiment and reason.\n"
            f"Schema: {{\"sentiment\":\"Bullish|Bearish|Neutral\",\"reason\":\"<one sentence>\"}}\n\n"
            f"Headlines:\n{headlines_text}\n"
        )

        raw_text, source = llm_router.route_request(base_prompt, expect_json=True, agent_name="SentimentAgent")
        
        if not raw_text:
            return "Neutral", f"API Error: {source}"
            
        parsed = self._parse_sentiment_payload(raw_text)
        if parsed:
            return parsed["sentiment"], parsed["reason"]
            
        return "Neutral", "Could not parse JSON response from " + source

    def run_news_scan(self):
        tickers = self._get_tickers()
        log.info(f"Scanning news for {tickers}...")

        for symbol in tickers:
            try:
                yf.set_tz_cache_location(YFINANCE_CACHE_DIR)
                ticker = yf.Ticker(symbol)
                news = ticker.news
                if not news:
                    continue

                headlines = [n.get('content', n).get('title', '') for n in news[:5]]

                sentiment, reason = self.analyze_sentiment(symbol, headlines)
                log.info(f"📰 {symbol} Sentiment: {sentiment} | {reason}")

                bus.publish('market_data', {
                    'source': 'sentiment_agent',
                    'symbol': symbol,
                    'sentiment': sentiment,
                    'reason': reason
                })
                
                # Push actionable changes directly to Telegram
                if sentiment in ["Bullish", "Bearish"]:
                    try:
                        from telegram_notifier import send_telegram_message
                        icon = "🟢" if sentiment == "Bullish" else "🔴"
                        msg = f"{icon} **Sentiment Shift for {symbol}**\n**Trend:** {sentiment}\n**AI Reason:** {reason}\n\n**Hot News Context:**\n"
                        for h in headlines[:3]:  # Push the top 3 headlines to Telegram
                            if h:
                                msg += f"- {h}\n"
                        send_telegram_message(msg)
                    except ImportError:
                        pass

                time.sleep(2)

            except Exception as e:
                log.error(f"Error for {symbol}: {e}")

        # Scan for global breaking news (Macro)
        try:
            log.info("Scanning for global breaking news...")
            spy = yf.Ticker('SPY')
            spy_news = spy.news
            if spy_news:
                global_headlines = [n.get('content', n).get('title', '') for n in spy_news[:5]]
                self._check_global_news(global_headlines)
        except Exception as e:
            log.error(f"Global news scan error: {e}")

    def _check_global_news(self, headlines):
        cleaned = [h.strip() for h in headlines if isinstance(h, str) and h.strip()]
        if not cleaned: return

        headlines_text = "\n".join([f"- {h}" for h in cleaned])
        prompt = (
            f"You are a macroeconomic risk analyst.\n"
            f"Review these general market headlines.\n"
            f"Identify if there is any EARTH-SHATTERING breaking news (e.g. War, CPI surprise, Fed Rate Cut, Crash).\n"
            f"If there is breaking news, set 'breaking' to true, and summarize the event in 'summary'. If not, set 'breaking' to false.\n"
            f"Return ONLY a valid JSON object.\n"
            f"Schema: {{\"breaking\":true|false,\"summary\":\"<one sentence max>\"}}\n\n"
            f"Headlines:\n{headlines_text}\n"
        )
        
        raw_text, source = llm_router.route_request(prompt, expect_json=True, agent_name="GlobalNews")
        if not raw_text: return
        
        parsed = self._extract_llm_json(raw_text)
        if parsed and parsed.get("breaking"):
            try:
                from telegram_notifier import send_telegram_message
                msg = f"🚨 **GLOBAL BREAKING NEWS** 🚨\n{parsed.get('summary', '')}\n\n**Sources:**\n"
                for h in cleaned[:3]:
                    msg += f"- {h}\n"
                send_telegram_message(msg)
            except ImportError:
                pass

    def start(self):
        self.running = True
        log.info("SentimentAgent started. Scanning news periodically...")

        while self.running:
            if not is_trading_day():
                log.info("Weekend. Sleeping until Monday.")
                sleep_until_market(log)
                continue

            # Run during pre-market and market hours only
            if not (is_premarket() or is_market_open()):
                log.info("Outside trading window. Sleeping until next pre-market.")
                sleep_until_market(log)
                continue

            self.run_news_scan()
            time.sleep(SENTIMENT_POLL_INTERVAL)


if __name__ == "__main__":
    agent = SentimentAgent()
    agent.start()
