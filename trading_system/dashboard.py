"""
ClawdBot Trading Dashboard — Streamlit UI.
Displays portfolio performance, system status, live logs, and agent health.
"""

import streamlit as st
import sqlite3
import pandas as pd
import os
import sys
import json
from datetime import datetime, timedelta
import glob

# Add trading system to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

st.set_page_config(
    page_title="ClawdBot Trading Dashboard",
    page_icon="🦞",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── Paths ────────────────────────────────────────────────────────────────────
SYSTEM_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK_FILE = os.path.join(SYSTEM_DIR, "TRADE_FREEZE.lock")
LOG_DIR = os.path.join(SYSTEM_DIR, "logs")
DEMO_DB = os.path.join(SYSTEM_DIR, "etoro_trades_demo.db")
REAL_DB = os.path.join(SYSTEM_DIR, "etoro_trades_real.db")
QUANT_STATE = os.path.join(SYSTEM_DIR, "quant_alert_state.json")

# ─── Custom Styling ──────────────────────────────────────────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    .stMetric { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                padding: 1rem; border-radius: 10px; border: 1px solid #0f3460; }
    div[data-testid="stMetricValue"] { font-size: 1.8rem; }
    .status-active { color: #00ff88; font-weight: bold; }
    .status-frozen { color: #ff4444; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ─── Header ──────────────────────────────────────────────────────────────────
col_title, col_status = st.columns([3, 1])
with col_title:
    st.title("🦞 ClawdBot Trading Dashboard")
with col_status:
    if os.path.exists(LOCK_FILE):
        st.error("🔴 FROZEN")
    else:
        st.success("🟢 ACTIVE")

# ─── Sidebar ─────────────────────────────────────────────────────────────────
st.sidebar.header("⚙️ System Controls")

# Kill switch
if st.sidebar.button("🚨 EMERGENCY KILL SWITCH", type="primary"):
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
    st.sidebar.markdown("---")
    with open(LOCK_FILE, "r") as f:
        st.sidebar.code(f.read(), language="text")

# Account selector
account_mode = st.sidebar.radio("📊 Account View", ["Demo", "Real"], horizontal=True)
db_path = DEMO_DB if account_mode == "Demo" else REAL_DB

# Refresh interval
st.sidebar.markdown("---")
st.sidebar.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")

# ─── Circuit Breaker Banner ─────────────────────────────────────────────────
if os.path.exists(LOCK_FILE):
    st.error("🚨 **CIRCUIT BREAKER ACTIVE**: All automated trading is FROZEN pending manual review.")

# ─── Load Trade Data ─────────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def load_trades(path):
    try:
        if not os.path.exists(path):
            return pd.DataFrame()
        conn = sqlite3.connect(path)
        df = pd.read_sql_query("SELECT * FROM trades", conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

df = load_trades(db_path)

# ─── Key Metrics Row ─────────────────────────────────────────────────────────
st.markdown("### 📈 Portfolio Performance")

if df.empty:
    st.info(f"No {account_mode} trading data available yet. Waiting for eToro sync.")
else:
    total_pnl = df['NetProfit'].sum()
    winning = df[df['NetProfit'] > 0]
    losing = df[df['NetProfit'] <= 0]
    win_rate = (len(winning) / len(df)) * 100 if len(df) > 0 else 0
    avg_win = winning['NetProfit'].mean() if not winning.empty else 0
    avg_loss = abs(losing['NetProfit'].mean()) if not losing.empty else 0
    rr_ratio = avg_win / avg_loss if avg_loss > 0 else float('inf')

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Net PnL", f"${total_pnl:.2f}", delta=f"{'▲' if total_pnl > 0 else '▼'}")
    col2.metric("Win Rate", f"{win_rate:.1f}%")
    col3.metric("Total Trades", len(df))
    col4.metric("Risk/Reward", f"{rr_ratio:.2f}")
    col5.metric("Avg Win", f"${avg_win:.2f}")

    st.markdown("---")

    # ─── Charts ──────────────────────────────────────────────────────────
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.subheader("📊 Cumulative PnL")
        df_sorted = df.sort_values('CloseDate').reset_index(drop=True)
        df_sorted['Cumulative_PnL'] = df_sorted['NetProfit'].cumsum()
        st.line_chart(df_sorted[['Cumulative_PnL']])

    with chart_col2:
        st.subheader("🎯 Win/Loss Distribution")
        chart_data = pd.DataFrame({
            'Result': ['Wins', 'Losses'],
            'Count': [len(winning), len(losing)]
        }).set_index('Result')
        st.bar_chart(chart_data)

    # ─── Recent Trades ───────────────────────────────────────────────────
    st.subheader("🔄 Recent Trades")
    st.dataframe(
        df.sort_values('CloseDate', ascending=False).head(15),
        use_container_width=True,
        hide_index=True
    )

# ─── Quant Agent State ──────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 🧠 Quant Agent Status")

quant_col1, quant_col2 = st.columns(2)

with quant_col1:
    if os.path.exists(QUANT_STATE):
        try:
            with open(QUANT_STATE, 'r') as f:
                quant = json.load(f)
            st.caption(f"Last scan date: {quant.get('date', 'Unknown')}")

            states = quant.get('states', {})
            sentiments = quant.get('sentiments', {})

            if states:
                rows = []
                for symbol, action in states.items():
                    sent = sentiments.get(symbol, 'N/A')
                    rows.append({'Ticker': symbol, 'Signal': action, 'Sentiment': sent})
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.info("No signals generated yet today.")
        except Exception as e:
            st.warning(f"Could not parse quant state: {e}")
    else:
        st.info("Quant agent has not generated state yet.")

with quant_col2:
    st.subheader("📰 AI Sentiment")
    if os.path.exists(QUANT_STATE):
        try:
            with open(QUANT_STATE, 'r') as f:
                quant = json.load(f)
            sentiments = quant.get('sentiments', {})
            if sentiments:
                for sym, sent in sentiments.items():
                    icon = "🟢" if sent == "Bullish" else ("🔴" if sent == "Bearish" else "⚪")
                    st.markdown(f"{icon} **{sym}**: {sent}")
            else:
                st.info("No sentiment data available.")
        except Exception:
            pass

# ─── Live Logs ───────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📋 Live System Logs")

today_log = os.path.join(LOG_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.log")
if os.path.exists(today_log):
    try:
        with open(today_log, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Show last N lines
        num_lines = st.slider("Lines to display", 10, 200, 50)
        log_text = "".join(lines[-num_lines:])
        st.code(log_text, language="text")
    except Exception as e:
        st.warning(f"Could not read log file: {e}")
else:
    # Check for other recent logs
    log_files = sorted(glob.glob(os.path.join(LOG_DIR, "*.log")), reverse=True)
    if log_files:
        selected_log = st.selectbox("Select log file", log_files)
        with open(selected_log, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        st.code("".join(lines[-50:]), language="text")
    else:
        st.info("No log files found yet.")

# ─── Sector Rotation ─────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 🔄 Sector Rotation")
sector_file = os.path.join(SYSTEM_DIR, "sector_rotation.md")
if os.path.exists(sector_file):
    with open(sector_file, "r", encoding="utf-8") as f:
        st.markdown(f.read())
else:
    st.info("No sector rotation data. Will generate next market day.")

# ─── Footer ──────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption("🦞 ClawdBot Multi-Agent Trading System | Local Ollama (gemma4:e4b) | ZeroMQ Bus Architecture")