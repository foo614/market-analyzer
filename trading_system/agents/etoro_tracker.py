import os
import sqlite3
import requests
import uuid
import pandas as pd
from datetime import datetime, timedelta
import re
import time
import sys

# Ensure message bus pathing
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from agents.message_bus import bus
except ImportError:
    bus = None

ETORO_BASE_URL = "https://public-api.etoro.com/api/v1"

def get_etoro_keys(is_real=False):
    tools_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'TOOLS.md')
    pub_key, user_key = None, None
    if os.path.exists(tools_path):
        with open(tools_path, 'r', encoding='utf-8') as f:
            content = f.read()
            pub_match = re.search(r'\*\*Public Key:\*\*\s*`([^`]+)`', content)
            key_label = 'Real User Key' if is_real else 'Demo User Key'
            user_match = re.search(rf'\*\*{key_label}:\*\*\s*`([^`]+)`', content)
            if pub_match: pub_key = pub_match.group(1)
            if user_match: user_key = user_match.group(1)
    return pub_key, user_key

def get_headers(is_real=False):
    pub_key, user_key = get_etoro_keys(is_real)
    if not pub_key or not user_key:
        print(f"Warning: eToro keys not found in TOOLS.md for {'Real' if is_real else 'Demo'} mode")
    
    return {
        "x-request-id": str(uuid.uuid4()),
        "x-api-key": pub_key.strip() if pub_key else "",
        "x-user-key": user_key.strip() if user_key else "",
        "Content-Type": "application/json"
    }

def init_db(db_path="etoro_trades.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            PositionID TEXT PRIMARY KEY,
            InstrumentID INTEGER,
            IsBuy BOOLEAN,
            OpenRate REAL,
            CloseRate REAL,
            Amount REAL,
            Leverage REAL,
            NetProfit REAL,
            Fees REAL,
            OpenDate TEXT,
            CloseDate TEXT
        )
    ''')
    conn.commit()
    return conn

def fetch_trade_history(is_real=False):
    print(f"Fetching eToro trade history ({'Real' if is_real else 'Demo'} mode)...")
    headers = get_headers(is_real)
    # Fetch last 7 days of raw history mapping back to SQLite deduplication
    min_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    url = f"{ETORO_BASE_URL}/trading/info/trade/history?minDate={min_date}"
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to fetch eToro history: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Error fetching eToro data: {e}")
        return None

def process_and_save_trades(history_data, conn):
    if not history_data or 'Positions' not in history_data:
        return
    
    cursor = conn.cursor()
    new_trades = 0
    
    for pos in history_data['Positions']:
        pos_id = str(pos.get('PositionID', ''))
        inst_id = pos.get('InstrumentID', 0)
        is_buy = pos.get('IsBuy', True)
        open_rate = pos.get('OpenRate', 0.0)
        close_rate = pos.get('CloseRate', 0.0)
        amount = pos.get('Amount', 0.0)
        leverage = pos.get('Leverage', 1.0)
        net_profit = pos.get('NetProfit', 0.0)
        fees = pos.get('Fees', 0.0)
        open_date = pos.get('OpenDate', '')
        close_date = pos.get('CloseDate', '')
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO trades 
                (PositionID, InstrumentID, IsBuy, OpenRate, CloseRate, Amount, Leverage, NetProfit, Fees, OpenDate, CloseDate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (pos_id, inst_id, is_buy, open_rate, close_rate, amount, leverage, net_profit, fees, open_date, close_date))
            new_trades += 1
        except Exception as e:
            print(f"Error saving trade {pos_id}: {e}")
            
    conn.commit()
    print(f"Saved/Updated {new_trades} trades to database.")

def generate_performance_report(conn, is_real=False):
    df = pd.read_sql_query("SELECT * FROM trades", conn)
    
    if df.empty:
        return "No trade history available for performance metrics."
        
    total_trades = len(df)
    winning_trades = len(df[df['NetProfit'] > 0])
    losing_trades = len(df[df['NetProfit'] <= 0])
    
    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
    
    gross_profit = df[df['NetProfit'] > 0]['NetProfit'].sum()
    gross_loss = abs(df[df['NetProfit'] < 0]['NetProfit'].sum())
    
    pnl_ratio = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')
    net_pnl = df['NetProfit'].sum()
    total_fees = df['Fees'].sum()
    
    # Simple Drawdown calculation based on cumulative PnL
    df = df.sort_values('CloseDate')
    df['Cumulative_PnL'] = df['NetProfit'].cumsum()
    df['Peak'] = df['Cumulative_PnL'].cummax()
    df['Drawdown'] = df['Peak'] - df['Cumulative_PnL']
    max_drawdown = df['Drawdown'].max()
    
    report_lines = [
        f"📈 **PORTFOLIO PERFORMANCE ({'REAL' if is_real else 'DEMO'})**",
        f"`Date: {datetime.now().strftime('%Y-%m-%d')}`",
        f"---",
        f"**OVERVIEW**",
        f"• 🔄 Total Trades: {total_trades}",
        f"• 🎯 Win Rate: `{win_rate:.2f}%`",
        f"• 💵 Net PnL: `${net_pnl:.2f}`\n",
        f"**RISK METRICS**",
        f"• ⚖️ Profit/Loss Ratio: `{pnl_ratio:.2f}`",
        f"• 📉 Max Drawdown: `${max_drawdown:.2f}`",
        f"• 💸 Total Fees: `${total_fees:.2f}`"
    ]
    
    report_content = "\n".join(report_lines)
    with open("etoro_performance.md", "w", encoding="utf-8") as f:
        f.write(report_content)
        
    print(f"eToro performance report generated ({'Real' if is_real else 'Demo'})")
    
    # Notify via ZMQ Message Broker instead of hardcoded python paths
    if bus:
        bus.publish('notifications', {
            'type': 'performance_report',
            'text': report_content
        })
        
    return report_content

class TrackerAgent:
    def __init__(self):
        self.running = False
        print(f"[{datetime.now().strftime('%H:%M:%S')}] TrackerAgent Initialized [CONCURRENT MODE]")
        
    def start(self):
        self.running = True
        print(f"TrackerAgent running. Polling BOTH Demo and Real account history every 60 minutes...")
        
        while self.running:
            try:
                # 1. Sync DEMO Performance
                conn_demo = init_db("etoro_trades_demo.db")
                hist_demo = fetch_trade_history(is_real=False)
                if hist_demo:
                    process_and_save_trades(hist_demo, conn_demo)
                generate_performance_report(conn_demo, is_real=False)
                conn_demo.close()
                
                # 2. Sync REAL Performance
                conn_real = init_db("etoro_trades_real.db")
                hist_real = fetch_trade_history(is_real=True)
                if hist_real:
                    process_and_save_trades(hist_real, conn_real)
                generate_performance_report(conn_real, is_real=True)
                conn_real.close()
                
                # Sleep for 60 minutes
                time.sleep(3600)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"TrackerAgent Error: {e}")
                time.sleep(60)

if __name__ == "__main__":
    agent = TrackerAgent()
    agent.start()
