import sys
import os
import time
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.message_bus import bus
from auto_trader import execute_demo_trade, demo_has_position
from risk_manager import check_circuit_breaker

class ExecutionAgent:
    """
    Listens for 'trade_signals' on the message bus.
    When a signal is received, it executes the trade via eToro API
    and publishes the result to the 'notifications' queue.
    """
    def __init__(self):
        self.sub = bus.get_sub('trade_signals')
        self.running = False
        import json
        self.json = json
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ExecutionAgent Initialized [CONCURRENT MODE]")

    def start(self):
        self.running = True
        print("ExecutionAgent is listening on ZMQ for 'trade_signals' payloads...")
        
        while self.running:
            try:
                topic, msg_bytes = self.sub.recv_multipart()
                msg = self.json.loads(msg_bytes.decode('utf-8'))
                signal = msg.get('payload', {})
                
                symbol = signal.get('symbol')
                action = signal.get('action') # 'BUY' or 'SELL'
                amount = signal.get('amount', 500)
                
                if not symbol or not action:
                    continue
                    
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Received {action} signal for {symbol}. Executing...")
                reason = signal.get('reason', 'Algorithmic trigger confirmed.')

                if check_circuit_breaker():
                    bus.publish('notifications', {
                        'type': 'trade_blocked',
                        'text': f"🛑 **ExecutionAgent**\nCircuit breaker active. Blocked: {action} {symbol} (${amount})."
                    })
                    continue
                # --- 1. DEMO: Execute the trade on eToro Demo environment ---
                if action == 'SELL' and not demo_has_position(symbol):
                    print(f"Skipping DEMO SELL for {symbol} (Not held in Demo Portfolio)")
                    # We still want to send the REAL notification below, but we bypass Demo Execution
                else:
                    success = execute_demo_trade(symbol, action, amount)
                    
                    if success:
                        bus.publish('notifications', {
                            'type': 'trade_success',
                            'text': (f"🤖 **AUTO-EXECUTION SUCCESS (DEMO)**\n"
                                     f"**FILLED**: `{'🟩 BUY' if action == 'BUY' else '🟥 SELL'} {symbol}` for `${amount:.2f}`\n"
                                     f"**Algorithm Rationale**: `{reason}`\n"
                                     f"*(Logged to backtest simulation)*")
                        })
                    else:
                        bus.publish('notifications', {
                            'type': 'trade_failure',
                            'text': (f"🤖 **AUTO-EXECUTION FAILURE (DEMO)**\n"
                                     f"**FAILED**: `{'🟩 BUY' if action == 'BUY' else '🟥 SELL'} {symbol}` for `${amount:.2f}`\n"
                                     f"*(Please check eToro API logs)*")
                        })
                
                
                # --- 2. REAL: Provide a recommendation instead of auto-executing ---
                bus.publish('notifications', {
                    'type': 'real_recommendation',
                    'text': (f"🏛️ **CLAWDBOT SIGNAL (REAL PORTFOLIO)**\n"
                             f"**ACTION**: `{'🟩 BUY' if action == 'BUY' else '🟥 SELL'} {symbol}`\n"
                             f"**CAPITAL**: `${amount:.2f}`\n\n"
                             f"📊 **Quant Rationale & Risk Desk:**\n"
                             f"`{reason}`\n\n"
                             f"*Action required: Execute manually in your broker.*")
                })
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"ExecutionAgent ZMQ Error: {e}")

if __name__ == "__main__":
    agent = ExecutionAgent()
    agent.start()
