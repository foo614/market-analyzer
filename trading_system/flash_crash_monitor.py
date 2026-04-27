import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz
import os
import json
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import SYSTEM_DIR
from llm_router import llm_router
from agents.message_bus import bus
from agents.sentiment_agent import SentimentAgent

yf.set_tz_cache_location(os.path.join(SYSTEM_DIR, "custom_cache_dir"))

INDEX_TICKERS = {'SPY': 'S&P 500', 'QQQ': 'NASDAQ'}
CRASH_THRESHOLD = -0.015  # -1.5% drop from the intraday High
STATE_FILE = os.path.join(SYSTEM_DIR, "flash_crash_state.json")

def check_flash_crass():
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
        except:
            pass
            
    current_date = datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d')
    if state.get("date") != current_date:
        state = {"date": current_date, "alerts": []}
        
    for symbol, name in INDEX_TICKERS.items():
        if symbol in state["alerts"]:
            continue  # Already alerted for this index today
            
        try:
            df = yf.download(symbol, period="1d", interval="1m", progress=False)
            if df.empty: continue
            
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
                
            current_price = df['Close'].iloc[-1]
            high_price = df['High'].max()
            
            drop_pct = (current_price - high_price) / high_price
            
            if drop_pct <= CRASH_THRESHOLD:
                # Sudden drastic drop detected! Fetch reasons!
                print(f"🚨 Flash crash detected on {name} ({symbol}): {drop_pct*100:.2f}% drop from high.")
                
                # Fetch news
                ticker = yf.Ticker(symbol)
                news = ticker.news
                headlines = [n.get('content', n).get('title', '') for n in news[:8] if n]
                cleaned_headlines = [h.strip() for h in headlines if isinstance(h, str) and h.strip()]
                headlines_text = "\n".join([f"- {h}" for h in cleaned_headlines])
                
                prompt = (
                    f"You are a breaking market news analyst.\n"
                    f"The {name} just suffered a sudden intraday drop of {drop_pct*100:.2f}%.\n"
                    f"Review these recent headlines over the last few hours.\n"
                    f"Identify exactly what caused the market to suddenly drop today.\n"
                    f"Return ONLY a valid JSON object.\n"
                    f"Schema: {{\"reason\":\"<one or two sentences explaining the drop>\"}}\n\n"
                    f"Headlines:\n{headlines_text}\n"
                )
                
                raw_text, source = llm_router.route_request(prompt, expect_json=True, agent_name="FlashCrashMonitor")
                
                # Parse using the sentiment agent's robust parser
                agent = SentimentAgent()
                parsed = agent._parse_llm_json(raw_text)
                
                explanation = "Could not definitively identify the reason from current headlines."
                if parsed and parsed.get("reason"):
                    explanation = parsed.get("reason")
                    
                alert_msg = (
                    f"📉 **【大盘急跌预警】 {name} Flash Drop**\n\n"
                    f"**Index:** `{symbol}`\n"
                    f"**Intraday Drop:** `{drop_pct*100:.2f}%` from today's high!\n\n"
                    f"🧠 **AI Market Analysis:**\n"
                    f"{explanation}\n\n"
                    f"**Recent Headlines:**\n"
                )
                for h in cleaned_headlines[:3]:
                    alert_msg += f"- {h}\n"
                    
                # Publish to message bus
                bus.publish('notifications', {'type': 'flash_crash_alert', 'text': alert_msg})
                
                # Record to prevent spam
                state["alerts"].append(symbol)
                
        except Exception as e:
            print(f"Error checking flash crash for {symbol}: {e}")
            
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

if __name__ == "__main__":
    check_flash_crass()
