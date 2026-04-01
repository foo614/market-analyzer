import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import pytz
import json
import os

yf.set_tz_cache_location("custom_cache_dir")

TICKERS = ['TSLA', 'SOXL', 'TQQQ', 'UNH']
STATE_FILE = "volume_alert_state.json"

def get_historical_thresholds(symbol):
    """Calculate 20-day average volume and 60-day 99th percentile volume."""
    try:
        df = yf.download(symbol, period="3mo", progress=False)
        if df.empty: return None, None
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        daily_vol = df['Volume'].dropna()
        if len(daily_vol) < 20: return None, None
        
        vol_20d_sma = daily_vol.tail(20).mean()
        vol_60d_99th = np.percentile(daily_vol.tail(60), 99)
        
        return vol_20d_sma, vol_60d_99th
    except Exception as e:
        print(f"Error fetching historical for {symbol}: {e}")
        return None, None

def check_intraday_volume():
    """Check 1-minute interval data for sudden volume spikes."""
    print(f"[{datetime.now(pytz.timezone('US/Eastern')).strftime('%H:%M:%S EST')}] Scanning for massive volume spikes...")
    
    # Load state to prevent spamming the same alert
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
        except: pass
        
    current_date = datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d')
    if state.get("date") != current_date:
        state = {"date": current_date, "alerts": []}
        
    alerts = []
    
    for symbol in TICKERS:
        has_surge_alert = f"{symbol}_surge" in state["alerts"] or symbol in state["alerts"]
        has_shrink_alert = f"{symbol}_shrink" in state["alerts"]
        
        if has_surge_alert and has_shrink_alert:
            continue
            
        vol_20d_sma, vol_60d_99th = get_historical_thresholds(symbol)
        if not vol_20d_sma: continue
        
        try:
            # Fetch today's intraday data (1m intervals)
            df_intraday = yf.download(symbol, period="1d", interval="1m", progress=False)
            if df_intraday.empty: continue
            
            if isinstance(df_intraday.columns, pd.MultiIndex):
                df_intraday.columns = df_intraday.columns.droplevel(1)
                
            # Calculate cumulative volume for the day so far
            current_daily_vol = df_intraday['Volume'].sum()
            
            # Calculate Time-Adjusted Expected Volume (assuming 390 minutes in a trading day)
            # Market hours: 9:30 AM to 4:00 PM EST (6.5 hours = 390 minutes)
            minutes_passed = len(df_intraday)
            if minutes_passed == 0: continue
            
            # What the 20d SMA volume *should* be at this time of day (linear projection)
            expected_vol_now = (vol_20d_sma / 390) * minutes_passed
            
            print(f"[{symbol}] Time: {minutes_passed}/390 mins | Current Vol: {current_daily_vol:,.0f} | Expected Now: {expected_vol_now:,.0f} | Ratio: {current_daily_vol/expected_vol_now:.1f}x")
            
            # Condition 1: Surge Alert
            if not has_surge_alert and current_daily_vol > (expected_vol_now * 2.0) and current_daily_vol > (vol_20d_sma * 0.5):
                
                # Analyze Price-Volume Divergence (Simple VWAP proxy)
                typical_price = (df_intraday['High'] + df_intraday['Low'] + df_intraday['Close']) / 3
                vwap = (typical_price * df_intraday['Volume']).sum() / current_daily_vol
                current_price = df_intraday['Close'].iloc[-1]
                open_price = df_intraday['Open'].iloc[0]
                
                if current_price > open_price and current_price < vwap:
                    divergence = "⚠️ **高位滞涨** (价格收红但跌破VWAP，警惕主力出货)"
                    action = "**[强烈建议]** 触发动态止损，减仓避险。"
                elif current_price < open_price and current_price > vwap:
                    divergence = "🟢 **低位承接** (价格收黑但站上VWAP，有抄底资金)"
                    action = "**[观察]** 停止做空，准备抓取反弹。"
                else:
                    divergence = "⚡ **趋势加速** (量价同向爆发)"
                    action = "**[顺势]** 顺势持有，收紧 Trailing Stop。"
                    
                alert_msg = (
                    f"🚨 **【天量异动预警】 ${symbol}**\n\n"
                    f"📊 **成交量极值**:\n"
                    f"- 当前成交量: {current_daily_vol:,.0f}\n"
                    f"- 突破当前预期量: {current_daily_vol/expected_vol_now:.1f}倍\n\n"
                    f"🔍 **量价分析 (基于 1m 级别)**:\n"
                    f"- 今日均价 (VWAP): ${vwap:.2f}\n"
                    f"- 当前现价: ${current_price:.2f}\n"
                    f"- 状态: {divergence}\n\n"
                    f"💡 **系统建议**: {action}"
                )
                alerts.append(alert_msg)
                state["alerts"].append(f"{symbol}_surge")
                
            # Condition 2: Shrink Alert (Less than 50% of expected, must be at least 60 mins into the day)
            elif not has_shrink_alert and minutes_passed >= 60 and current_daily_vol < (expected_vol_now * 0.5):
                current_price = df_intraday['Close'].iloc[-1]
                open_price = df_intraday['Open'].iloc[0]
                
                if current_price > open_price:
                    status = "📈 **无量上涨** (缺乏买盘支撑，可能有诱多嫌疑)"
                elif current_price < open_price:
                    status = "📉 **无量阴跌** (抛压不重但买盘匮乏，阴跌寻底)"
                else:
                    status = "⏸️ **窄幅震荡** (多空双方都在观望)"
                    
                alert_msg = (
                    f"🧊 **【极度缩量预警】 ${symbol}**\n\n"
                    f"📊 **成交量萎缩**:\n"
                    f"- 当前成交量: {current_daily_vol:,.0f}\n"
                    f"- 当前预期量: {expected_vol_now:,.0f}\n"
                    f"- 缩量比例: 仅为预期的 {current_daily_vol/expected_vol_now:.2f}倍\n\n"
                    f"🔍 **价格表现**:\n"
                    f"- 当前现价: ${current_price:.2f}\n"
                    f"- 状态: {status}\n\n"
                    f"💡 **系统建议**: 变盘前夕或交投清淡。若高位无量需警惕回调，若低位无量可能面临方向选择。建议多看少动。"
                )
                alerts.append(alert_msg)
                state["alerts"].append(f"{symbol}_shrink")
                
        except Exception as e:
            print(f"Error processing intraday for {symbol}: {e}")
            
    # Save state
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)
        
    # Send alerts
    if alerts:
        try:
            from telegram_notifier import send_telegram_message
            for msg in alerts:
                send_telegram_message(msg)
                print("Sent volume alert to Telegram.")
        except ImportError:
            for msg in alerts: print(msg)

if __name__ == "__main__":
    check_intraday_volume()
