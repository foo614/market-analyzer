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
    OLLAMA_API_URL, OLLAMA_MODEL, check_ollama_health,
    SENTIMENT_POLL_INTERVAL, sleep_until_market
)
import yfinance as yf

log = get_logger("SentimentAgent")


class SentimentAgent:
    """
    Scrapes recent news via yfinance for the tracked tickers.
    Sends headlines to local Ollama (gemma4:e4b) to score Sentiment.
    Publishes output to 'market_data' queue.
    Now market-hours-aware with Ollama health checks and retry logic.
    """
    def __init__(self):
        self.running = False

        # Initialize Ollama client with health check
        self.client = None
        ollama_ok, msg = check_ollama_health()
        if ollama_ok:
            try:
                from openai import OpenAI
                self.client = OpenAI(
                    base_url=OLLAMA_API_URL,
                    api_key="ollama"
                )
                log.info(f"Ollama connected ({OLLAMA_MODEL})")
            except Exception as e:
                log.warning(f"Ollama client init failed: {e}")
        else:
            log.warning(f"Ollama unavailable: {msg}")

        log.info("SentimentAgent Initialized")

    def _get_tickers(self):
        """Get current ticker list (dynamic from eToro portfolio)."""
        return get_portfolio_tickers()

    def _parse_llm_json(self, raw_text):
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

        if not isinstance(result, dict):
            return None

        sentiment = result.get("sentiment", "Neutral")
        if sentiment not in ["Bullish", "Bearish", "Neutral"]:
            sentiment = "Neutral"
        reason = result.get("reason", "Analyzed headlines.")
        if not isinstance(reason, str) or not reason.strip():
            reason = "Analyzed headlines."
        return {"sentiment": sentiment, "reason": reason.strip()}

    def analyze_sentiment(self, symbol, headlines):
        if not self.client:
            return "Neutral", "No LLM available"

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

        # Retry logic: 1 retry with 5s backoff
        for attempt in range(2):
            try:
                try:
                    response = self.client.chat.completions.create(
                        model=OLLAMA_MODEL,
                        messages=[{"role": "user", "content": base_prompt}],
                        temperature=0.2,
                        max_tokens=150,
                        response_format={"type": "json_object"}
                    )
                except TypeError:
                    response = self.client.chat.completions.create(
                        model=OLLAMA_MODEL,
                        messages=[{"role": "user", "content": base_prompt}],
                        temperature=0.2,
                        max_tokens=150
                    )

                raw_text = response.choices[0].message.content.strip()

                parsed = self._parse_llm_json(raw_text)
                if parsed:
                    return parsed["sentiment"], parsed["reason"]

                repair_prompt = (
                    "Convert the following into a valid JSON object ONLY.\n"
                    "Schema: {\"sentiment\":\"Bullish|Bearish|Neutral\",\"reason\":\"<one sentence>\"}\n\n"
                    f"TEXT:\n{raw_text}\n"
                )
                try:
                    repair = self.client.chat.completions.create(
                        model=OLLAMA_MODEL,
                        messages=[{"role": "user", "content": repair_prompt}],
                        temperature=0.0,
                        max_tokens=150,
                        response_format={"type": "json_object"}
                    )
                except TypeError:
                    repair = self.client.chat.completions.create(
                        model=OLLAMA_MODEL,
                        messages=[{"role": "user", "content": repair_prompt}],
                        temperature=0.0,
                        max_tokens=150
                    )

                repaired_text = repair.choices[0].message.content.strip()
                repaired = self._parse_llm_json(repaired_text)
                if repaired:
                    return repaired["sentiment"], repaired["reason"]

                return "Neutral", "Could not parse JSON response"

            except Exception as e:
                if attempt == 0:
                    log.warning(f"Ollama error for {symbol}, retrying in 5s: {e}")
                    time.sleep(5)
                else:
                    log.error(f"Ollama failed after retry for {symbol}: {e}")
                    return "Neutral", "API Error"

        return "Neutral", "API Error"

    def run_news_scan(self):
        tickers = self._get_tickers()
        log.info(f"Scanning news for {tickers}...")

        for symbol in tickers:
            try:
                yf.set_tz_cache_location("custom_cache_dir")
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

                time.sleep(2)

            except Exception as e:
                log.error(f"Error for {symbol}: {e}")

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
