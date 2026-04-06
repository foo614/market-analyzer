"""
Telegram Notifier with message chunking and rate limiting.
Routes messages through NotificationAgent bus when available,
or sends directly as fallback.
"""

import os
import sys
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import get_credential

# Import bus with graceful fallback
try:
    from agents.message_bus import bus
    HAS_BUS = True
except ImportError:
    HAS_BUS = False

# Telegram limits
MAX_MESSAGE_LENGTH = 4000  # Telegram limit is 4096, leaving margin
MAX_MESSAGES_PER_MINUTE = 20
_send_timestamps = []


def _rate_limit_ok():
    """Check if we're within Telegram rate limits."""
    global _send_timestamps
    now = time.time()
    # Prune old timestamps
    _send_timestamps = [t for t in _send_timestamps if now - t < 60]
    return len(_send_timestamps) < MAX_MESSAGES_PER_MINUTE


def _chunk_message(text, max_len=MAX_MESSAGE_LENGTH):
    """Split a long message into chunks that fit Telegram's limit."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        # Try to split at a newline
        split_pos = text.rfind('\n', 0, max_len)
        if split_pos == -1:
            split_pos = max_len

        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip('\n')

    return chunks


def send_telegram_message(message_text, direct_send=False):
    """
    Sends a message via Telegram.
    Supports message chunking for long messages and rate limiting.
    """
    if not message_text:
        return False

    # Route through bus if available (unless called by NotificationAgent directly)
    if HAS_BUS and not direct_send:
        try:
            bus.publish('notifications', {'text': message_text})
            print("Message routed to Notification Agent Bus.")
            return True
        except Exception as e:
            print(f"Failed to route to bus, falling back to direct send: {e}")

    bot_token = get_credential('telegram_bot_token', 'TELEGRAM_BOT_TOKEN')
    chat_id = get_credential('telegram_chat_id', 'TELEGRAM_CHAT_ID')

    if not bot_token or not chat_id or "YOUR_" in bot_token or "YOUR_" in chat_id:
        print("Telegram credentials not properly configured.")
        return False

    # Chunk the message if too long
    chunks = _chunk_message(message_text)
    all_success = True

    for i, chunk in enumerate(chunks):
        if not _rate_limit_ok():
            print("Rate limit reached. Waiting 10s...")
            time.sleep(10)

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown"
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                _send_timestamps.append(time.time())
                if len(chunks) > 1:
                    print(f"Sent chunk {i+1}/{len(chunks)} to Telegram.")
                else:
                    print("Successfully sent message to Telegram.")
            else:
                print(f"Failed to send message: {response.text}")
                all_success = False
        except Exception as e:
            print(f"Error sending to Telegram: {e}")
            all_success = False

        # Small delay between chunks to avoid rate limiting
        if i < len(chunks) - 1:
            time.sleep(0.5)

    return all_success


def send_file_content(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return send_telegram_message(content)
    except FileNotFoundError:
        print(f"File not found: {file_path}")
        return False
