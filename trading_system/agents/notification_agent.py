import sys
import os
import time
from datetime import datetime

# Add parent directory to path so we can import telegram_notifier
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.message_bus import bus
from telegram_notifier import send_telegram_message

class NotificationAgent:
    def __init__(self):
        self.consumer_name = 'notification_agent'
        self.sub = bus.get_sub('notifications')
        self.running = False
        import json
        self.json = json
        print(f"[{datetime.now().strftime('%H:%M:%S')}] NotificationAgent Initialized")

    def start(self):
        self.running = True
        print("NotificationAgent is listening on ZMQ for 'notifications'...")
        
        while self.running:
            try:
                topic, msg_bytes = self.sub.recv_multipart()
                msg = self.json.loads(msg_bytes.decode('utf-8'))
                payload = msg.get('payload', {})
                success = False
                
                if isinstance(payload, str):
                    success = send_telegram_message(payload, direct_send=True)
                elif isinstance(payload, dict):
                    text = payload.get('text', '')
                    if text:
                        success = send_telegram_message(text, direct_send=True)
                        
                if success:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Broadcasted message via Telegram")
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Telegram send failed or skipped.")
                    
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"NotificationAgent ZMQ Error: {e}")

if __name__ == "__main__":
    agent = NotificationAgent()
    agent.start()
