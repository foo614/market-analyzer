import sys
import os
import time
from datetime import datetime
import json
import re

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.message_bus import bus
import yfinance as yf
from openai import OpenAI

class SentimentAgent:
    """
    Scrapes recent news via yfinance for the tracked tickers.
    Sends headlines to NVIDIA NIM (Llama 3.1) to score Sentiment.
    Publishes output to 'market_data' queue.
    """
    def __init__(self):
        self.running = False
        self.tickers = ['TSLA', 'SOXL', 'TQQQ', 'UNH']
        
        # Extract API key for NVIDIA
        self.api_key = os.environ.get("NVIDIA_API_KEY")
        if not self.api_key:
            tools_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'TOOLS.md')
            if os.path.exists(tools_path):
                with open(tools_path, 'r', encoding='utf-8') as f:
                    match = re.search(r'\*\*NVIDIA API Key:\*\*\s*`([^`]+)`', f.read())
                    if match: self.api_key = match.group(1)
                    
        self.client = None
        if self.api_key and self.api_key != '<your_nvidia_api_key_here>':
            self.client = OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=self.api_key
            )
            
        print(f"[{datetime.now().strftime('%H:%M:%S')}] SentimentAgent Initialized")

    def analyze_sentiment(self, symbol, headlines):
        if not self.client:
            return "Neutral", "No API Key"
            
        headlines_text = "\n".join([f"- {h}" for h in headlines])
        prompt = f"""
You are a quantitative trading sentiment analyzer.
Review these recent news headlines for the stock {symbol}.
Determine the overall short-term sentiment strictly as: Bullish, Bearish, or Neutral.
Output MUST be a valid JSON object strictly matching this format:
{{"sentiment": "Bullish|Bearish|Neutral", "reason": "A 1-sentence punchy summary of why."}}

Headlines:
{headlines_text}
"""
        
        try:
            response = self.client.chat.completions.create(
                model="meta/llama-3.1-8b-instruct",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=150
            )
            
            raw_text = response.choices[0].message.content.strip()
            
            # Use regex to extract the JSON payload, robust to LLM conversational filler
            json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
                sentiment = result.get('sentiment', 'Neutral')
                if sentiment not in ["Bullish", "Bearish", "Neutral"]:
                    sentiment = "Neutral"
                return sentiment, result.get('reason', 'Analyzed headlines.')
            else:
                return "Neutral", "Could not parse JSON response"
                
        except Exception as e:
            print(f"NVIDIA API Error: {e}")
            return "Neutral", "API Error"

    def run_news_scan(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] SentimentAgent: Checking news...")
        
        for symbol in self.tickers:
            try:
                # yfinance disables cache completely to avoid sandbox DB locks
                yf.set_tz_cache_location("custom_cache_dir")
                ticker = yf.Ticker(symbol)
                news = ticker.news
                if not news: continue
                
                # Grab top 5 most recent titles, handling newer and older yfinance versions safely
                headlines = [n.get('content', n).get('title', '') for n in news[:5]]
                
                sentiment, reason = self.analyze_sentiment(symbol, headlines)
                print(f"📰 {symbol} Sentiment: {sentiment} | {reason}")
                
                # Publish to message bus payload
                bus.publish('market_data', {
                    'source': 'sentiment_agent',
                    'symbol': symbol,
                    'sentiment': sentiment,
                    'reason': reason
                })
                
                # Sleep briefly to space out the 40 RPM quota
                time.sleep(2)
                
            except Exception as e:
                print(f"SentimentAgent error for {symbol}: {e}")

    def start(self):
        self.running = True
        print("SentimentAgent started. Scanning news periodically...")
        
        while self.running:
            self.run_news_scan()
            time.sleep(900)  # Sleep 15 minutes between polling rounds

if __name__ == "__main__":
    agent = SentimentAgent()
    agent.start()
