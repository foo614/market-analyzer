"""
eToro Demo Auto-Trader.
Uses centralized config for API keys instead of parsing TOOLS.md directly.
"""

import os
import sys
import requests
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import get_etoro_headers, etoro_request, ETORO_BASE_URL
from logger import get_logger

log = get_logger("AutoTrader")


def get_instrument_id(symbol):
    """Resolve the instrument ID for a given symbol from eToro."""
    headers = get_etoro_headers(is_real=False)
    url = f"{ETORO_BASE_URL}/market-data/search?internalSymbolFull={symbol}&fields=instrumentId,internalSymbolFull,displayname"
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            for item in data.get('items', []):
                if item.get('internalSymbolFull') == symbol:
                    return item.get('instrumentId')
    except Exception as e:
        log.error(f"Failed to fetch instrument ID for {symbol}: {e}")
    return None


def get_demo_portfolio():
    """Retrieve all open positions on the eToro Demo Account."""
    headers = get_etoro_headers(is_real=False)
    return etoro_request('/trading/info/demo/portfolio', headers=headers)


def demo_has_position(symbol):
    """Check if the Demo Portfolio currently holds a position in the given symbol."""
    instrument_id = get_instrument_id(symbol)
    if not instrument_id:
        return False

    portfolio = get_demo_portfolio()
    if not portfolio:
        return False

    # Handle both key casing variants
    positions = portfolio.get('Positions', portfolio.get('positions', []))
    for pos in positions:
        iid = pos.get('InstrumentID', pos.get('instrumentID'))
        if iid == instrument_id:
            return True

    return False


def execute_demo_trade(symbol, action, amount=1000):
    """Execute a trade on the Demo account."""
    log.info(f"Initiating {action} order for {symbol} on DEMO account...")

    instrument_id = get_instrument_id(symbol)
    if not instrument_id:
        log.error(f"Could not find Instrument ID for {symbol}.")
        return False

    headers = get_etoro_headers(is_real=False)
    url = f"{ETORO_BASE_URL}/trading/execution/demo/market-open-orders/by-amount"

    payload = {
        "InstrumentID": instrument_id,
        "IsBuy": True if action.upper() == 'BUY' else False,
        "Leverage": 1,
        "Amount": amount
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code in [200, 201]:
            log.info(f"✅ DEMO TRADE SUCCESS: {action} {symbol} for ${amount}")
            return True
        else:
            log.error(f"❌ DEMO TRADE FAILED: {response.status_code} - {response.text[:200]}")
            return False
    except Exception as e:
        log.error(f"Error executing trade: {e}")
        return False


if __name__ == "__main__":
    execute_demo_trade("TSLA", "BUY", 500)
