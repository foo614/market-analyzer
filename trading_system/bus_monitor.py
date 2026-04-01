import os
import json
import time
from datetime import datetime

class BusMonitor:
    """
    A simple terminal dashboard to watch Agents communicating on the Message Bus in real-time.
    """
    def __init__(self, bus_dir=None):
        if bus_dir is None:
            self.bus_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bus_data")
        else:
            self.bus_dir = bus_dir
        self.last_counts = {
            'market_data': 0,
            'trade_signals': 0,
            'notifications': 0,
            'system_state': 0
        }
        self.last_ids = {
            'market_data': None,
            'trade_signals': None,
            'notifications': None,
            'system_state': None
        }

    def _read_queue(self, queue_name):
        path = os.path.join(self.bus_dir, f"{queue_name}.json")
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def clear_screen(self):
        os.system('cls' if os.name == 'nt' else 'clear')

    def start(self):
        print("Starting Agent Communication Monitor... (Press Ctrl+C to stop)")
        
        while True:
            try:
                # We won't clear screen entirely to preserve log history, 
                # instead we'll just print new messages as they arrive.
                
                for queue in self.last_counts.keys():
                    data = self._read_queue(queue)
                    
                    if len(data) > self.last_counts[queue]:
                        # New messages arrived!
                        new_msgs = data[self.last_counts[queue]:]
                        
                        for msg in new_msgs:
                            timestamp = msg.get('timestamp', '')[:19]
                            payload = msg.get('payload', {})
                            
                            # Format based on queue type
                            if queue == 'trade_signals':
                                print(f"[{timestamp}] ⚡ [QUANT -> EXECUTION] | {payload.get('action')} {payload.get('symbol')} (${payload.get('amount')}) | Reason: {payload.get('reason')}")
                            elif queue == 'notifications':
                                text = payload if isinstance(payload, str) else payload.get('text', '...')
                                preview = text.replace('\n', ' ')[:60] + "..."
                                print(f"[{timestamp}] 📢 [SYSTEM -> NOTIFICATION] | Broadcasting: {preview}")
                            elif queue == 'market_data':
                                print(f"[{timestamp}] 📡 [DATA -> QUANT] | New market data pushed")
                            elif queue == 'system_state':
                                print(f"[{timestamp}] 🤖 [AGENT HEARTBEAT] | {payload}")
                                
                        self.last_counts[queue] = len(data)
                        self.last_ids[queue] = data[-1]['id'] if data else None
                        
                time.sleep(1)
            except KeyboardInterrupt:
                print("\nStopping Monitor.")
                break
            except Exception as e:
                print(f"Monitor Error: {e}")
                time.sleep(2)

if __name__ == "__main__":
    monitor = BusMonitor()
    monitor.start()
