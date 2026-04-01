import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz
import os

# Disable cache to avoid peewee lock issues
yf.set_tz_cache_location("custom_cache_dir")

# S&P 500 Sector ETFs
SECTORS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLY": "Consumer Discretionary",
    "XLI": "Industrials",
    "XLC": "Communication Services",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLE": "Energy",
    "XLB": "Materials",
    "XLRE": "Real Estate"
}

def calculate_obv_trend(df):
    """Calculates OBV and returns if it's accumulating over last 10 days."""
    if len(df) < 15: return False, 0
    
    obv = [0]
    for i in range(1, len(df)):
        if df['Close'].iloc[i] > df['Close'].iloc[i-1]:
            obv.append(obv[-1] + df['Volume'].iloc[i])
        elif df['Close'].iloc[i] < df['Close'].iloc[i-1]:
            obv.append(obv[-1] - df['Volume'].iloc[i])
        else:
            obv.append(obv[-1])
            
    df['OBV'] = obv
    recent_obv = df['OBV'].tail(5).mean()
    prev_obv = df['OBV'].iloc[-10:-5].mean()
    
    # Calculate % change in OBV momentum
    momentum = ((recent_obv - prev_obv) / abs(prev_obv)) * 100 if prev_obv != 0 else 0
    
    return recent_obv > prev_obv, momentum

def scan_sectors():
    print("Scanning S&P 500 Sectors for Volume Rotation...")
    results = []
    
    for ticker, name in SECTORS.items():
        try:
            df = yf.download(ticker, period="1mo", progress=False)
            if df.empty: continue
            
            # Handle multi-level columns in newer yfinance
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
                
            is_accumulating, momentum = calculate_obv_trend(df)
            
            # Price performance last 5 days
            perf_5d = ((df['Close'].iloc[-1] - df['Close'].iloc[-5]) / df['Close'].iloc[-5]) * 100
            
            results.append({
                "Ticker": ticker,
                "Sector": name,
                "Accumulating": is_accumulating,
                "OBV_Momentum": momentum,
                "Perf_5D": perf_5d
            })
        except Exception as e:
            print(f"Error scanning {ticker}: {e}")
            
    # Sort by OBV Momentum (Money Flow)
    df_results = pd.DataFrame(results)
    if df_results.empty: return
    
    df_results = df_results.sort_values(by="OBV_Momentum", ascending=False)
    
    report_lines = [
        "## 🔄 Sector Rotation Scanner",
        f"**Date:** {datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M EST')}\n",
        "| Sector ETF | Sector Name | Money Flow | 5D Price % | OBV Trend |",
        "| :--- | :--- | :--- | :--- | :--- |"
    ]
    
    for _, row in df_results.iterrows():
        trend_icon = "🟢 Inflow" if row['Accumulating'] else "🔴 Outflow"
        report_lines.append(f"| **{row['Ticker']}** | {row['Sector']} | {row['OBV_Momentum']:+.1f}% | {row['Perf_5D']:+.2f}% | {trend_icon} |")
        
    report_content = "\n".join(report_lines)
    
    with open("sector_rotation.md", "w", encoding="utf-8") as f:
        f.write(report_content)
        
    print("Sector scan complete. Report saved.")
    
    try:
        import sys
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        from agents.message_bus import bus
        bus.publish('notifications', {'text': report_content})
        print("Sector Rotation report pushed to message bus.")
    except Exception as e:
        print(f"Failed to publish to bus: {e}")
        # Fallback
        try:
            from telegram_notifier import send_telegram_message
            send_telegram_message(report_content)
        except ImportError:
            pass

if __name__ == "__main__":
    scan_sectors()
