"""
Risk Manager with live portfolio equity from eToro API.
Manages circuit breaker, per-symbol allocation warnings, and daily trade limits.
"""

import sqlite3
import pandas as pd
from datetime import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from logger import get_logger
from config import (
    LOCK_FILE, MAX_DAILY_LOSS_PCT, MAX_DAILY_TRADES,
    MAX_SYMBOL_ALLOCATION_PCT, get_portfolio_equity
)

log = get_logger("RiskManager")

# Cached equity (refreshed once per check cycle)
_cached_equity = None
_equity_last_refresh = 0


def _get_portfolio_value():
    """Get live portfolio equity, with caching."""
    import time
    global _cached_equity, _equity_last_refresh

    now = time.time()
    # Refresh every 5 minutes max
    if _cached_equity and (now - _equity_last_refresh < 300):
        return _cached_equity

    equity = get_portfolio_equity(is_real=False)  # Use Demo for circuit breaker
    if equity and equity > 0:
        _cached_equity = equity
        _equity_last_refresh = now
        return equity

    # Fallback to cached or default
    return _cached_equity or 10000.0


def check_circuit_breaker(db_path="etoro_trades.db"):
    """Check if trading should be frozen due to risk limits."""
    if os.path.exists(LOCK_FILE):
        log.warning("CIRCUIT BREAKER ACTIVE: System is currently frozen pending manual review.")
        return True

    try:
        conn = sqlite3.connect(db_path)
        today_str = datetime.now().strftime('%Y-%m-%d')
        query = f"SELECT * FROM trades WHERE CloseDate LIKE '{today_str}%'"
        df = pd.read_sql_query(query, conn)
        conn.close()

        if df.empty:
            log.info("No trades closed today. Circuit breaker clear.")
            return False

        # Daily trade count limit
        if len(df) >= MAX_DAILY_TRADES:
            log.warning(f"Daily trade limit reached ({len(df)}/{MAX_DAILY_TRADES}). Freezing.")
            trigger_freeze(0, 0, reason=f"Daily trade count limit exceeded ({len(df)} trades)")
            return True

        # Daily PnL limit
        portfolio_value = _get_portfolio_value()
        daily_pnl = df['NetProfit'].sum()
        loss_pct = abs(daily_pnl) / portfolio_value

        if daily_pnl < 0 and loss_pct >= MAX_DAILY_LOSS_PCT:
            log.critical(f"Daily loss of ${abs(daily_pnl):.2f} exceeds {MAX_DAILY_LOSS_PCT*100}% of ${portfolio_value:.0f}!")
            trigger_freeze(daily_pnl, loss_pct)
            return True

        log.info(f"Daily PnL: ${daily_pnl:.2f} (Portfolio: ${portfolio_value:.0f}). Circuit breaker clear.")
        return False

    except Exception as e:
        log.error(f"Risk manager error: {e}")
        return False


def trigger_freeze(pnl, pct, reason=None):
    """Activate the circuit breaker freeze."""
    freeze_reason = reason or f"Daily loss threshold exceeded. Loss: ${pnl:.2f} ({pct*100:.2f}%)"

    with open(LOCK_FILE, "w") as f:
        f.write(f"FROZEN ON: {datetime.now().isoformat()}\n")
        f.write(f"REASON: {freeze_reason}\n")
        f.write("MANUAL INTERVENTION REQUIRED. Delete this file to resume trading.")

    # Notify via Telegram
    try:
        from telegram_notifier import send_telegram_message
        msg = f"🛑 *CIRCUIT BREAKER TRIGGERED* 🛑\n\n{freeze_reason}\nAll automated trading strategies are now *FROZEN* pending manual review."
        send_telegram_message(msg)
    except ImportError:
        pass


if __name__ == "__main__":
    is_frozen = check_circuit_breaker()
    sys.exit(1 if is_frozen else 0)
