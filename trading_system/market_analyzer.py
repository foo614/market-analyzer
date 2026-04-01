import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz
import os

# Disable yfinance cache entirely to bypass peewee/sqlite issues in sandbox
yf.set_tz_cache_location("custom_cache_dir")

def calculate_rsi(data, periods=14):
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=periods).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=periods).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_support_resistance(high, low, close):
    pivot = (high + low + close) / 3
    r1 = (2 * pivot) - low
    s1 = (2 * pivot) - high
    return pivot, r1, s1

def analyze_market():
    print("Fetching market data...")
    
    # Indices and their corresponding futures
    symbols = {
        "S&P 500": {"index": "^GSPC", "future": "ES=F", "etf": "SPY"},
        "NASDAQ": {"index": "^IXIC", "future": "NQ=F", "etf": "QQQ"},
        "Dow Jones": {"index": "^DJI", "future": "YM=F", "etf": "DIA"},
        "VIX": {"index": "^VIX"}
    }
    
    report_lines = [
        f"# Market Analysis Report",
        f"**Generated:** {datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
    ]
    
    # 1. VIX Fear Index
    vix_data = yf.Ticker("^VIX").history(period="5d")
    if not vix_data.empty:
        current_vix = vix_data['Close'].iloc[-1]
        prev_vix = vix_data['Close'].iloc[-2]
        sentiment = "🔴 High Fear (Bearish)" if current_vix > 25 else ("🟢 Complacency (Bullish)" if current_vix < 15 else "⚪ Neutral")
        report_lines.append(f"## 1. Market Sentiment (VIX)")
        report_lines.append(f"- **Current VIX:** {current_vix:.2f} (Previous: {prev_vix:.2f})")
        report_lines.append(f"- **Sentiment:** {sentiment}\n")

    # 2. Major Indices Technicals
    report_lines.append(f"## 2. Major Indices & Futures Premium")
    
    for name, syms in symbols.items():
        if name == "VIX": continue
        
        index_ticker = yf.Ticker(syms["index"])
        future_ticker = yf.Ticker(syms["future"])
        
        idx_hist = index_ticker.history(period="1mo")
        fut_hist = future_ticker.history(period="5d")
        
        if idx_hist.empty or fut_hist.empty: continue
            
        idx_close = idx_hist['Close'].iloc[-1]
        fut_close = fut_hist['Close'].iloc[-1]
        premium = ((fut_close - idx_close) / idx_close) * 100
        
        # Tech Indicators
        idx_hist['SMA_20'] = idx_hist['Close'].rolling(window=20).mean()
        idx_hist['RSI'] = calculate_rsi(idx_hist['Close'])
        
        rsi = idx_hist['RSI'].iloc[-1]
        sma_20 = idx_hist['SMA_20'].iloc[-1]
        trend = "🟢 Bullish" if idx_close > sma_20 else "🔴 Bearish"
        
        # Support / Resistance
        high = idx_hist['High'].iloc[-1]
        low = idx_hist['Low'].iloc[-1]
        pivot, r1, s1 = get_support_resistance(high, low, idx_close)
        
        report_lines.append(f"### {name}")
        report_lines.append(f"- **Index Close:** {idx_close:.2f} | **Futures:** {fut_close:.2f}")
        report_lines.append(f"- **Futures Premium:** {premium:.2f}% ({'Bullish' if premium > 0 else 'Bearish'})")
        report_lines.append(f"- **Trend (SMA20):** {trend} | **RSI (14):** {rsi:.1f}")
        report_lines.append(f"- **Levels:** Pivot: {pivot:.2f} | R1: {r1:.2f} | S1: {s1:.2f}\n")
        
    # 3. ETF Flow Proxies (Volume vs Average Volume)
    report_lines.append(f"## 3. ETF Volume Activity")
    for name, syms in symbols.items():
        if name == "VIX": continue
        etf_ticker = yf.Ticker(syms["etf"])
        etf_hist = etf_ticker.history(period="1mo")
        if etf_hist.empty: continue
        
        vol_today = etf_hist['Volume'].iloc[-1]
        vol_avg = etf_hist['Volume'].mean()
        vol_surge = ((vol_today - vol_avg) / vol_avg) * 100
        
        flow_status = "🔥 High Activity" if vol_surge > 20 else ("🧊 Low Activity" if vol_surge < -20 else "⚖️ Normal")
        report_lines.append(f"- **{syms['etf']} ({name}):** Volume {vol_today:,.0f} ({vol_surge:+.1f}% vs 30d Avg) - {flow_status}")

    report_content = "\n".join(report_lines)
    
    # Generate LLM Sentiment Brief
    llm_brief = generate_llm_brief(report_content)
    if llm_brief:
        report_content = f"{llm_brief}\n\n---\n\n{report_content}"
        
    # Save to file
    with open("market_report.md", "w", encoding="utf-8") as f:
        f.write(report_content)
        
    print("Market report generated: market_report.md")
    
    # Notify via Telegram
    try:
        from telegram_notifier import send_telegram_message
        send_telegram_message(report_content)
    except ImportError:
        pass
        
    return report_content

def generate_llm_brief(raw_data):
    print("Asking NVIDIA NIM to analyze market sentiment...")
    try:
        import re
        import os
        from openai import OpenAI
        
        # Extract API key for NVIDIA
        api_key = os.environ.get("NVIDIA_API_KEY")
        if not api_key:
            tools_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'TOOLS.md')
            if os.path.exists(tools_path):
                with open(tools_path, 'r', encoding='utf-8') as f:
                    match = re.search(r'\*\*NVIDIA API Key:\*\*\s*`([^`]+)`', f.read())
                    if match: api_key = match.group(1)
                    
        if not api_key or api_key == '<your_nvidia_api_key_here>':
            print("No valid NVIDIA API key found. Skipping LLM.")
            return None
            
        # NVIDIA NIM uses the OpenAI client format but points to their base URL
        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=api_key
        )
        
        prompt = f"""
        You are a senior quantitative analyst. Review the following raw market data and provide a concise, 
        actionable 3-4 sentence daily brief for a trader in **Chinese (中文)**. 
        Focus on the VIX sentiment, futures premium, and ETF volume rotation.
        Do not output markdown headers, just the plain text insight with appropriate emojis.
        
        Data:
        {raw_data}
        """
        
        # Using Meta's Llama 3.1 70B Instruct via NVIDIA NIM as default
        response = client.chat.completions.create(
            model="meta/llama-3.1-70b-instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200
        )
        
        return f"🤖 **NVIDIA Llama Insight:**\n{response.choices[0].message.content.strip()}"
        
    except Exception as e:
        print(f"LLM analysis failed: {e}")
        return None

if __name__ == "__main__":
    analyze_market()
