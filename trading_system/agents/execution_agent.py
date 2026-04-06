import sys
import os
import time
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.message_bus import bus
from auto_trader import execute_demo_trade, demo_has_position
from risk_manager import check_circuit_breaker
from logger import get_logger
from config import DEFAULT_TRADE_AMOUNT

import json

log = get_logger("ExecutionAgent")


class ExecutionAgent:
    """
    Listens for 'trade_signals' on the message bus.
    Executes trades on eToro Demo and sends REAL recommendations via notifications.
    """
    def __init__(self):
        self.sub = bus.get_sub('trade_signals')
        self.running = False
        log.info("ExecutionAgent Initialized [CONCURRENT MODE]")

    def start(self):
        self.running = True
        log.info("Listening on ZMQ for 'trade_signals' payloads...")

        while self.running:
            try:
                topic, msg_bytes = self.sub.recv_multipart()
                msg = json.loads(msg_bytes.decode('utf-8'))
                signal = msg.get('payload', {})

                symbol = signal.get('symbol')
                action = signal.get('action')
                amount = signal.get('amount', DEFAULT_TRADE_AMOUNT)

                if not symbol or not action:
                    continue

                log.info(f"Received {action} signal for {symbol}. Executing...")
                reason = signal.get('reason', 'Algorithmic trigger confirmed.')
                llm_opinion = signal.get('llm_opinion')
                llm_reason = signal.get('llm_reason')

                if check_circuit_breaker():
                    bus.publish('notifications', {
                        'type': 'trade_blocked',
                        'text': f"🛑 **ExecutionAgent**\nCircuit breaker active. Blocked: {action} {symbol} (${amount})."
                    })
                    continue

                # --- 1. DEMO: Execute the trade on eToro Demo environment ---
                if action == 'SELL' and not demo_has_position(symbol):
                    log.info(f"Skipping DEMO SELL for {symbol} (Not held in Demo Portfolio)")
                else:
                    success = execute_demo_trade(symbol, action, amount)
                    status_icon = '🟩 BUY' if action == 'BUY' else '🟥 SELL'

                    if success:
                        bus.publish('notifications', {
                            'type': 'trade_success',
                            'text': (f"🤖 **AUTO-EXECUTION SUCCESS (DEMO)**\n"
                                     f"**FILLED**: `{status_icon} {symbol}` for `${amount:.2f}`\n"
                                     f"**Algorithm Rationale**: `{reason}`\n"
                                     f"*(Logged to backtest simulation)*")
                        })
                    else:
                        bus.publish('notifications', {
                            'type': 'trade_failure',
                            'text': (f"🤖 **AUTO-EXECUTION FAILURE (DEMO)**\n"
                                     f"**FAILED**: `{status_icon} {symbol}` for `${amount:.2f}`\n"
                                     f"*(Please check eToro API logs)*")
                        })

                # --- 2. REAL: Recommendation with LLM advisory ---
                llm_line = ""
                if llm_opinion:
                    flag = "✅" if llm_opinion == "AGREE" else "⚠️"
                    llm_line = f"\n\n🤖 **LLM Advisory**: {flag} {llm_opinion}\n_{llm_reason}_"

                status_icon = '🟩 BUY' if action == 'BUY' else '🟥 SELL'
                bus.publish('notifications', {
                    'type': 'real_recommendation',
                    'text': (f"🏛️ **CLAWDBOT SIGNAL (REAL PORTFOLIO)**\n"
                             f"**ACTION**: `{status_icon} {symbol}`\n"
                             f"**CAPITAL**: `${amount:.2f}`\n\n"
                             f"📊 **Quant Rationale & Risk Desk:**\n"
                             f"`{reason}`{llm_line}\n\n"
                             f"*Action required: Execute manually in your broker.*")
                })
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"ZMQ Error: {e}")


if __name__ == "__main__":
    agent = ExecutionAgent()
    agent.start()
