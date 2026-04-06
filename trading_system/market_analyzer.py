"""
Market Analyzer - Pre/Post Market Report Generator.
Uses centralized config and local Ollama for LLM analysis.
"""

import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz
import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import OLLAMA_API_URL, OLLAMA_MODEL, check_ollama_health
from indicators import calculate_rsi
from logger import get_logger

log = get_logger("MarketAnalyzer")

# Disable yfinance cache
yf.set_tz_cache_location("custom_cache_dir")


def get_support_resistance(high, low, close):
    pivot = (high + low + close) / 3
    r1 = (2 * pivot) - low
    s1 = (2 * pivot) - high
    return pivot, r1, s1


def analyze_market():
    log.info("Fetching market data...")

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
        if name == "VIX":
            continue

        index_ticker = yf.Ticker(syms["index"])
        future_ticker = yf.Ticker(syms["future"])

        idx_hist = index_ticker.history(period="1mo")
        fut_hist = future_ticker.history(period="5d")

        if idx_hist.empty or fut_hist.empty:
            continue

        idx_close = idx_hist['Close'].iloc[-1]
        fut_close = fut_hist['Close'].iloc[-1]
        premium = ((fut_close - idx_close) / idx_close) * 100

        idx_hist['SMA_20'] = idx_hist['Close'].rolling(window=20).mean()
        idx_hist['RSI'] = calculate_rsi(idx_hist['Close'])

        rsi = idx_hist['RSI'].iloc[-1]
        sma_20 = idx_hist['SMA_20'].iloc[-1]
        trend = "🟢 Bullish" if idx_close > sma_20 else "🔴 Bearish"

        high = idx_hist['High'].iloc[-1]
        low = idx_hist['Low'].iloc[-1]
        pivot, r1, s1 = get_support_resistance(high, low, idx_close)

        report_lines.append(f"### {name}")
        report_lines.append(f"- **Index Close:** {idx_close:.2f} | **Futures:** {fut_close:.2f}")
        report_lines.append(f"- **Futures Premium:** {premium:.2f}% ({'Bullish' if premium > 0 else 'Bearish'})")
        report_lines.append(f"- **Trend (SMA20):** {trend} | **RSI (14):** {rsi:.1f}")
        report_lines.append(f"- **Levels:** Pivot: {pivot:.2f} | R1: {r1:.2f} | S1: {s1:.2f}\n")

    # 3. ETF Flow Proxies
    report_lines.append(f"## 3. ETF Volume Activity")
    for name, syms in symbols.items():
        if name == "VIX":
            continue
        etf_ticker = yf.Ticker(syms["etf"])
        etf_hist = etf_ticker.history(period="1mo")
        if etf_hist.empty:
            continue

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

    log.info("Market report generated: market_report.md")

    # Notify via Telegram
    try:
        from telegram_notifier import send_telegram_message
        send_telegram_message(report_content)
    except ImportError:
        pass

    return report_content


def generate_llm_brief(raw_data):
    log.info("Asking Ollama to analyze market sentiment...")
    try:
        from openai import OpenAI

        ollama_ok, msg = check_ollama_health()
        if not ollama_ok:
            log.warning(f"Ollama unavailable: {msg}. Skipping LLM.")
            return None

        client = OpenAI(
            base_url=OLLAMA_API_URL,
            api_key="ollama"
        )

        prompt = f"""
        You are a senior quantitative analyst. Review the following raw market data and provide a concise, 
        actionable 3-4 sentence daily brief for a trader in **Chinese (中文)**. 
        Focus on the VIX sentiment, futures premium, and ETF volume rotation.
        Do not output markdown headers, just the plain text insight with appropriate emojis.
        
        Data:
        {raw_data}
        """

        response = client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200
        )

        return f"🤖 **Ollama Gemma Insight:**\n{response.choices[0].message.content.strip()}"

    except Exception as e:
        log.error(f"LLM analysis failed: {e}")
        return None


if __name__ == "__main__":
    analyze_market()
