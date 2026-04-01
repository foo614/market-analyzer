import os
import requests
import re
import sys

# To support backward compatibility while we migrate to the Message Bus
try:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from agents.message_bus import bus
    HAS_BUS = True
except ImportError:
    HAS_BUS = False

def get_credentials():
    # Try to read from TOOLS.md
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    try:
        # Traverse up one directory to find TOOLS.md
        tools_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'TOOLS.md')
        if os.path.exists(tools_path):
            with open(tools_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            if not bot_token:
                token_match = re.search(r'\*\*Bot Token:\*\*\s*`([^`]+)`', content)
                if token_match:
                    bot_token = token_match.group(1)
                    
            if not chat_id:
                chat_match = re.search(r'\*\*Chat ID:\*\*\s*`([^`]+)`', content)
                if chat_match:
                    chat_id = chat_match.group(1)
    except Exception as e:
        print(f"Error reading TOOLS.md: {e}")
        
    return bot_token, chat_id

def send_telegram_message(message_text, direct_send=False):
    """
    Sends a message via Telegram. 
    In the new architecture, this should ideally be called by the NotificationAgent,
    but we keep it functional here for legacy scripts.
    """
    if not message_text:
        return
        
    # If the message bus is available, route it through the Notification Agent instead of sending directly
    # UNLESS direct_send is True (which means the NotificationAgent itself is calling this)
    if HAS_BUS and not direct_send:
        try:
            bus.publish('notifications', {'text': message_text})
            print("Message routed to Notification Agent Bus.")
            return True
        except Exception as e:
            print(f"Failed to route to bus, falling back to direct send: {e}")

    bot_token, chat_id = get_credentials()
    
    if not bot_token or not chat_id or "YOUR_" in bot_token or "YOUR_" in chat_id:
        print("Telegram credentials not properly configured in TOOLS.md or environment variables.")
        return False
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("Successfully sent message to Telegram.")
            return True
        else:
            print(f"Failed to send message: {response.text}")
            return False
    except Exception as e:
        print(f"Error sending to Telegram: {e}")
        return False

def send_file_content(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return send_telegram_message(content)
    except FileNotFoundError:
        print(f"File not found: {file_path}")
        return False
