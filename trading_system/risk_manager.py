import sqlite3
import pandas as pd
from datetime import datetime
import os
import sys

LOCK_FILE = "TRADE_FREEZE.lock"
PORTFOLIO_VALUE = 10000.0  # Should dynamically fetch from eToro, static for now
MAX_DAILY_LOSS_PCT = 0.01  # 1%

def check_circuit_breaker(db_path="etoro_trades.db"):
    if os.path.exists(LOCK_FILE):
        print("⚠️ CIRCUIT BREAKER ACTIVE: System is currently frozen pending manual review.")
        return True
        
    try:
        conn = sqlite3.connect(db_path)
        # Get today's trades
        today_str = datetime.now().strftime('%Y-%m-%d')
        query = f"SELECT * FROM trades WHERE CloseDate LIKE '{today_str}%'"
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if df.empty:
            print("Risk Manager: No trades closed today. Circuit breaker clear.")
            return False
            
        daily_pnl = df['NetProfit'].sum()
        loss_pct = abs(daily_pnl) / PORTFOLIO_VALUE
        
        if daily_pnl < 0 and loss_pct >= MAX_DAILY_LOSS_PCT:
            print(f"🚨 ALERT: Daily loss of ${abs(daily_pnl):.2f} exceeds {MAX_DAILY_LOSS_PCT*100}% threshold!")
            trigger_freeze(daily_pnl, loss_pct)
            return True
            
        print(f"Risk Manager: Daily PnL is ${daily_pnl:.2f}. Circuit breaker clear.")
        return False
        
    except Exception as e:
        print(f"Error in risk manager: {e}")
        return False

def trigger_freeze(pnl, pct):
    with open(LOCK_FILE, "w") as f:
        f.write(f"FROZEN ON: {datetime.now().isoformat()}\n")
        f.write(f"REASON: Daily loss threshold exceeded. Loss: ${pnl:.2f} ({pct*100:.2f}%)\n")
        f.write("MANUAL INTERVENTION REQUIRED. Delete this file to resume trading.")
    
    # Notify via Telegram
    try:
        from telegram_notifier import send_telegram_message
        msg = f"🛑 *CIRCUIT BREAKER TRIGGERED* 🛑\n\nDaily loss exceeded 1% (${abs(pnl):.2f}).\nAll automated trading strategies are now *FROZEN* pending manual review."
        send_telegram_message(msg)
    except ImportError:
        pass

if __name__ == "__main__":
    is_frozen = check_circuit_breaker()
    sys.exit(1 if is_frozen else 0)
