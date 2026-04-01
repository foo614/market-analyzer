import os
import requests
import json
import uuid
import re

ETORO_BASE_URL = "https://public-api.etoro.com/api/v1"

def get_headers():
    tools_path = os.path.join(os.path.dirname(__file__), 'TOOLS.md')
    if not os.path.exists(tools_path):
        tools_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'TOOLS.md')
    
    pub_key, user_key = None, None
    if os.path.exists(tools_path):
        with open(tools_path, 'r', encoding='utf-8') as f:
            content = f.read()
            pub_match = re.search(r'\*\*Public Key:\*\*\s*`([^`]+)`', content)
            user_match = re.search(r'\*\*Demo User Key:\*\*\s*`([^`]+)`', content)
            if pub_match: pub_key = pub_match.group(1)
            if user_match: user_key = user_match.group(1)
            
    return {
        "x-request-id": str(uuid.uuid4()),
        "x-api-key": pub_key.strip() if pub_key else "",
        "x-user-key": user_key.strip() if user_key else "",
        "Content-Type": "application/json"
    }

headers = get_headers()
url = f"{ETORO_BASE_URL}/trading/info/demo/portfolio"
resp = requests.get(url, headers=headers)
print(f"GET {url} -> {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    positions = data.get('Positions', [])
    print(f"Num positions in DEMO PORTFOLIO: {len(positions)}")
    if positions:
        print("Sample Position keys:")
        print(list(positions[0].keys()))
        print(positions[0])
