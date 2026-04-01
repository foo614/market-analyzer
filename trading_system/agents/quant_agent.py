import sys
import os
import time
import json
from datetime import datetime
import warnings

warnings.simplefilter(action='ignore', category=FutureWarning)

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.message_bus import bus
from backtest_framework import YahooFetcher, generate_signals

class QuantAgent:
    """
    The Brain of the system. 
    It polls the 'market_data' queue.
    Runs the strategy logic (formerly in Node.js).
    Publishes BUY/SELL instructions to 'trade_signals' and 'notifications'.
    """
    def __init__(self):
        self.consumer_name = 'quant_agent'
        self.sub = bus.get_sub('market_data')
            
        self.running = False
        
        # State tracking to avoid notification spam
        self.state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'quant_alert_state.json')
        self.state_data = self._load_state()

        # Best params from grid search
        self.strategy_params = {
            'TSLA': {'rsi_buy': 30, 'rsi_sell': 70, 'obv_fast': 7, 'obv_slow': 10},
            'TQQQ': {'rsi_buy': 30, 'rsi_sell': 70, 'obv_fast': 5, 'obv_slow': 10},
            'SOXL': {'rsi_buy': 30, 'rsi_sell': 70, 'obv_fast': 5, 'obv_slow': 10}
        }
        print(f"[{datetime.now().strftime('%H:%M:%S')}] QuantAgent Initialized")

    def _load_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {'date': '', 'states': {}, 'sentiments': {}}

    def _save_state(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state_data, f, indent=2)
        except Exception:
            pass

    def evaluate_indicator_signal(self, payload):
        """ Evaluates logic previously stored in obv_monitor.js """
        symbol = payload.get('symbol')
        price = payload.get('price', 0)
        atr = payload.get('atr', 0)
        rsi = payload.get('rsi', 50)
        obvStatus = payload.get('obvStatus', 'Neutral')
        isBullish = payload.get('isBullish', None)

        actionSignal = "➖ HOLD"
        
        if rsi > 70 and "Distributing" in obvStatus:
            actionSignal = "TAKE PROFIT (Momentum Fading)"
            bus.publish('trade_signals', {'symbol': symbol, 'action': 'SELL', 'amount': 500, 'reason': actionSignal})
        elif rsi > 80:
            actionSignal = "TAKE PROFIT (Extreme Overbought)"
            bus.publish('trade_signals', {'symbol': symbol, 'action': 'SELL', 'amount': 500, 'reason': actionSignal})
        elif isBullish is False and "Distributing" in obvStatus:
            actionSignal = f"STOP LOSS (Trend Break. ATR Risk: ${(atr * 2):.2f})"
            bus.publish('trade_signals', {'symbol': symbol, 'action': 'SELL', 'amount': 500, 'reason': actionSignal})
        elif rsi < 30 and "Accumulating" in obvStatus:
            sentiment = self.state_data.get('sentiments', {}).get(symbol, 'Neutral')
            if sentiment == 'Bearish':
                actionSignal = f"⚠️ VETOED (News is Bearish)"
            else:
                actionSignal = f"🟢 BUY (Oversold. Suggest Stop: ${(price - (atr * 2)):.2f})"
                bus.publish('trade_signals', {'symbol': symbol, 'action': 'BUY', 'amount': 500, 'reason': actionSignal})
        elif isBullish is False and rsi < 40:
            actionSignal = "⚠️ WARNING (Weakness)"

        # Get current sentiment for table formatting
        current_sent = self.state_data.get('sentiments', {}).get(symbol, 'Neutral')
        return actionSignal, f"| **{symbol}** | ${price:.2f} | {atr:.2f} | {rsi:.1f} | {obvStatus} | {current_sent} | `{actionSignal}` |\n"

    def process_market_data(self, new_messages):
        try:
            if not new_messages:
                return

            current_date = datetime.now().strftime('%Y-%m-%d')
            is_new_day = (current_date != self.state_data.get('date'))
            if is_new_day:
                self.state_data['date'] = current_date
                self.state_data['states'] = {}
                self.state_data.setdefault('sentiments', {})

            has_significant_changes = is_new_day
            markdown_table = "| Ticker | Price | ATR | RSI(14) | OBV Trend | AI Sentiment | Status |\n|---|---|---|---|---|---|---|\n"
            processed_any = False

            for msg in new_messages:
                payload = msg.get('payload', {})
                if payload.get('source') == 'obv_monitor':
                    symbol = payload.get('symbol')
                    if not symbol: continue
                    
                    action, row = self.evaluate_indicator_signal(payload)
                    markdown_table += row
                    processed_any = True
                    
                    prev_action = self.state_data['states'].get(symbol)
                    if not is_new_day and prev_action != action and action != "➖ HOLD":
                        has_significant_changes = True
                        
                    self.state_data['states'][symbol] = action
                    
                elif payload.get('source') == 'sentiment_agent':
                    symbol = payload.get('symbol')
                    sentiment = payload.get('sentiment')
                    if symbol and sentiment:
                        if 'sentiments' not in self.state_data:
                            self.state_data['sentiments'] = {}
                        self.state_data['sentiments'][symbol] = sentiment
                        processed_any = True
                # No offset saves needed in ZMQ mode

            if processed_any:
                self._save_state()
                if has_significant_changes:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] QuantAgent found actionable alerts.")
                    bus.publish('notifications', {
                        'type': 'quant_alert',
                        'text': f"🧠 **QUANTITATIVE MARKET SCAN**\n---\n{markdown_table}"
                    })
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] QuantAgent: No new actionable alerts. Suppressing Telegram.")
                    
        except Exception as e:
            print(f"QuantAgent Error: {e}")

    def start(self):
        self.running = True
        print("QuantAgent started. ZMQ STREAMING ENABLED. Waiting for triggers...")
        
        while self.running:
            try:
                # recv_multipart blocks entirely until an element arrives
                topic, msg_bytes = self.sub.recv_multipart()
                msg = json.loads(msg_bytes.decode('utf-8'))
                self.process_market_data([msg])
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Quant ZMQ Error: {e}")

if __name__ == "__main__":
    agent = QuantAgent()
    agent.start()
