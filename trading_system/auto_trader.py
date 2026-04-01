import os
import requests
import uuid
import json
import re

ETORO_BASE_URL = "https://public-api.etoro.com/api/v1"

def get_etoro_keys():
    tools_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'TOOLS.md')
    pub_key, user_key = None, None
    if os.path.exists(tools_path):
        with open(tools_path, 'r', encoding='utf-8') as f:
            content = f.read()
            pub_match = re.search(r'\*\*Public Key:\*\*\s*`([^`]+)`', content)
            user_match = re.search(r'\*\*Demo User Key:\*\*\s*`([^`]+)`', content)
            if pub_match: pub_key = pub_match.group(1)
            if user_match: user_key = user_match.group(1)
    return pub_key, user_key

def get_headers():
    pub_key, user_key = get_etoro_keys()
    if not pub_key or not user_key:
        print("Warning: eToro keys not found in TOOLS.md")
    
    return {
        "x-request-id": str(uuid.uuid4()),
        "x-api-key": pub_key.strip() if pub_key else "",
        "x-user-key": user_key.strip() if user_key else "",
        "Content-Type": "application/json"
    }

def get_instrument_id(symbol):
    """Resolve the instrument ID for a given symbol from eToro."""
    url = f"{ETORO_BASE_URL}/market-data/search?internalSymbolFull={symbol}&fields=instrumentId,internalSymbolFull,displayname"
    try:
        response = requests.get(url, headers=get_headers())
        if response.status_code == 200:
            data = response.json()
            for item in data.get('items', []):
                if item.get('internalSymbolFull') == symbol:
                    return item.get('instrumentId')
    except Exception as e:
        print(f"Failed to fetch instrument ID for {symbol}: {e}")
    return None

def get_demo_portfolio():
    """Retrieve all natively open positions on the eToro Demo Account."""
    url = f"{ETORO_BASE_URL}/trading/info/demo/portfolio"
    try:
        response = requests.get(url, headers=get_headers())
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Failed to fetch demo portfolio state: {e}")
    return None

def demo_has_position(symbol):
    """Check if the Demo Portfolio currently inherently holds a position in the given symbol."""
    instrument_id = get_instrument_id(symbol)
    if not instrument_id:
        return False
        
    portfolio = get_demo_portfolio()
    if not portfolio or 'Positions' not in portfolio:
        return False
        
    for pos in portfolio['Positions']:
        if pos.get('InstrumentID') == instrument_id:
            return True
            
    return False

def execute_demo_trade(symbol, action, amount=1000):
    """
    Execute a trade on the Demo account.
    action: 'BUY' or 'SELL'
    amount: Default $1000 per trade
    """
    print(f"Initiating {action} order for {symbol} on DEMO account...")
    
    instrument_id = get_instrument_id(symbol)
    if not instrument_id:
        print(f"Could not find Instrument ID for {symbol}.")
        return False
        
    url = f"{ETORO_BASE_URL}/trading/execution/demo/market-open-orders/by-amount"
    
    payload = {
        "InstrumentID": instrument_id,
        "IsBuy": True if action.upper() == 'BUY' else False,
        "Leverage": 1,
        "Amount": amount
    }
    
    try:
        response = requests.post(url, headers=get_headers(), json=payload)
        if response.status_code in [200, 201]:
            print(f"✅ DEMO TRADE SUCCESS: {action} {symbol} for ${amount}")
            print(json.dumps(response.json(), indent=2))
                
            return True
        else:
            print(f"❌ DEMO TRADE FAILED: {response.status_code}")
            print(response.text)
            return False
    except Exception as e:
        print(f"Error executing trade: {e}")
        return False

if __name__ == "__main__":
    # Test the API with a $500 BUY on TSLA
    execute_demo_trade("TSLA", "BUY", 500)
