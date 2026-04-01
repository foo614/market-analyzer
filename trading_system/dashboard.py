import streamlit as st
import sqlite3
import pandas as pd
import os
from datetime import datetime

st.set_page_config(page_title="Clawd Trading Dashboard", layout="wide")

st.title("📈 Clawd AI Trading Dashboard")

LOCK_FILE = "TRADE_FREEZE.lock"

# --- Sidebar Controls ---
st.sidebar.header("System Controls")
if st.sidebar.button("🚨 MANUAL KILL SWITCH"):
    with open(LOCK_FILE, "w") as f:
        f.write(f"FROZEN ON: {datetime.now().isoformat()}\n")
        f.write("REASON: Manual user override via Dashboard.\n")
        f.write("MANUAL INTERVENTION REQUIRED. Delete this file to resume trading.")
    st.sidebar.error("System Frozen!")
    st.rerun()

if os.path.exists(LOCK_FILE):
    if st.sidebar.button("✅ LIFT FREEZE (Resume Trading)"):
        os.remove(LOCK_FILE)
        st.sidebar.success("System Resumed!")
        st.rerun()

# Check Circuit Breaker
if os.path.exists(LOCK_FILE):
    st.error("🚨 CIRCUIT BREAKER ACTIVE: Automated trading is currently FROZEN due to risk limits or manual override.")
    with open(LOCK_FILE, "r") as f:
        st.code(f.read())
else:
    st.success("✅ System Status: Active & Monitoring")

# Load Data
@st.cache_data(ttl=60)
def load_data():
    try:
        conn = sqlite3.connect("etoro_trades.db")
        df = pd.read_sql_query("SELECT * FROM trades", conn)
        conn.close()
        return df
    except Exception as e:
        return pd.DataFrame()

df = load_data()

if df.empty:
    st.info("No trading data available yet. Waiting for eToro sync.")
else:
    # Key Metrics
    total_pnl = df['NetProfit'].sum()
    winning_trades = df[df['NetProfit'] > 0]
    win_rate = (len(winning_trades) / len(df)) * 100 if len(df) > 0 else 0
    total_trades = len(df)
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Net PnL", f"${total_pnl:.2f}")
    col2.metric("Win Rate", f"{win_rate:.1f}%")
    col3.metric("Total Trades", total_trades)
    
    avg_win = winning_trades['NetProfit'].mean() if not winning_trades.empty else 0
    losing_trades = df[df['NetProfit'] <= 0]
    avg_loss = abs(losing_trades['NetProfit'].mean()) if not losing_trades.empty else 0
    risk_reward = avg_win / avg_loss if avg_loss > 0 else float('inf')
    col4.metric("Risk/Reward Ratio", f"{risk_reward:.2f}")
    
    st.markdown("---")
    
    # Layout with two columns for charts
    chart_col1, chart_col2 = st.columns(2)
    
    with chart_col1:
        st.subheader("Cumulative PnL")
        df_sorted = df.sort_values('CloseDate').reset_index(drop=True)
        df_sorted['Cumulative_PnL'] = df_sorted['NetProfit'].cumsum()
        st.line_chart(df_sorted['Cumulative_PnL'])
        
    with chart_col2:
        st.subheader("Win/Loss Distribution")
        pie_data = pd.DataFrame({
            'Result': ['Wins', 'Losses'],
            'Count': [len(winning_trades), len(losing_trades)]
        })
        st.bar_chart(pie_data.set_index('Result'))

    st.subheader("Recent Trades")
    st.dataframe(df.sort_values('CloseDate', ascending=False).head(10))

# --- Sector Rotation Data ---
st.markdown("---")
st.subheader("🔄 Latest Sector Rotation")
if os.path.exists("sector_rotation.md"):
    with open("sector_rotation.md", "r", encoding="utf-8") as f:
        st.markdown(f.read())
else:
    st.info("No sector rotation data available yet. Will generate after market close.")

st.markdown("---")
st.markdown("*Note: Advanced Reinforcement Learning (PPO/SAC) and LLM Fine-tuning pipelines are pending GPU infrastructure scaling.*")