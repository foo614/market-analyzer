import sys
import os
import time
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.message_bus import bus
from telegram_notifier import send_telegram_message
from logger import get_logger

import json

log = get_logger("NotificationAgent")


class NotificationAgent:
    def __init__(self):
        self.consumer_name = 'notification_agent'
        self.sub = bus.get_sub('notifications')
        self.running = False
        log.info("NotificationAgent Initialized")

    def start(self):
        self.running = True
        log.info("Listening on ZMQ for 'notifications'...")

        while self.running:
            try:
                topic, msg_bytes = self.sub.recv_multipart()
                msg = json.loads(msg_bytes.decode('utf-8'))
                payload = msg.get('payload', {})
                success = False

                if isinstance(payload, str):
                    success = send_telegram_message(payload, direct_send=True)
                elif isinstance(payload, dict):
                    text = payload.get('text', '')
                    if text:
                        success = send_telegram_message(text, direct_send=True)

                if success:
                    log.info("Broadcasted message via Telegram")
                else:
                    log.warning("Telegram send failed or skipped.")

            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"ZMQ Error: {e}")


if __name__ == "__main__":
    agent = NotificationAgent()
    agent.start()
