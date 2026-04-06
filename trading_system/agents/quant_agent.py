import sys
import os
import time
import json
from datetime import datetime
import warnings

warnings.simplefilter(action='ignore', category=FutureWarning)

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.message_bus import bus
from backtest_framework import YahooFetcher, generate_signals
from logger import get_logger
from config import (
    get_portfolio_tickers, SIGNAL_COOLDOWN_MINUTES,
    OLLAMA_API_URL, OLLAMA_MODEL, check_ollama_health
)

log = get_logger("QuantAgent")


class QuantAgent:
    """
    The Brain of the system.
    Listens to 'market_data' queue via ZMQ.
    Runs strategy logic, emits BUY/SELL to 'trade_signals' and 'notifications'.
    Includes LLM-as-Judge (soft advisory) via local Ollama.
    """
    def __init__(self):
        self.consumer_name = 'quant_agent'
        self.sub = bus.get_sub('market_data')
        self.running = False

        # State tracking
        self.state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'quant_alert_state.json')
        self.state_data = self._load_state()

        # Signal cooldown: {symbol: last_signal_timestamp}
        self.cooldowns = {}

        # LLM client (soft advisory)
        self.llm_client = None
        ollama_ok, msg = check_ollama_health()
        if ollama_ok:
            try:
                from openai import OpenAI
                self.llm_client = OpenAI(
                    base_url=OLLAMA_API_URL,
                    api_key="ollama"
                )
                log.info(f"LLM-as-Judge enabled ({OLLAMA_MODEL})")
            except Exception as e:
                log.warning(f"LLM-as-Judge disabled: {e}")
        else:
            log.warning(f"LLM-as-Judge disabled: {msg}")

        # Best params from grid search
        self.strategy_params = {
            'TSLA': {'rsi_buy': 30, 'rsi_sell': 70, 'obv_fast': 7, 'obv_slow': 10},
            'TQQQ': {'rsi_buy': 30, 'rsi_sell': 70, 'obv_fast': 5, 'obv_slow': 10},
            'SOXL': {'rsi_buy': 30, 'rsi_sell': 70, 'obv_fast': 5, 'obv_slow': 10}
        }
        log.info("QuantAgent Initialized")

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

    def _is_on_cooldown(self, symbol, action):
        """Check if a signal for this symbol is on cooldown."""
        key = f"{symbol}_{action}"
        last_time = self.cooldowns.get(key, 0)
        elapsed = (time.time() - last_time) / 60  # minutes
        if elapsed < SIGNAL_COOLDOWN_MINUTES:
            log.debug(f"Signal {action} {symbol} suppressed (cooldown: {elapsed:.0f}/{SIGNAL_COOLDOWN_MINUTES}min)")
            return True
        return False

    def _set_cooldown(self, symbol, action):
        """Record that a signal was emitted."""
        self.cooldowns[f"{symbol}_{action}"] = time.time()

    def _ask_llm_opinion(self, symbol, indicators, action):
        """
        Ask Ollama for a second opinion on the trade signal.
        Returns (opinion, reasoning) — purely advisory, does NOT block.
        """
        if not self.llm_client:
            return None, None

        prompt = f"""You are a quantitative trading risk advisor. A trading algorithm has generated a {action} signal for {symbol}.

Current indicators:
- Price: ${indicators.get('price', 0):.2f}
- RSI(14): {indicators.get('rsi', 50):.1f}
- ATR: {indicators.get('atr', 0):.2f}
- OBV Trend: {indicators.get('obvStatus', 'Unknown')}
- AI Sentiment: {indicators.get('sentiment', 'Neutral')}
- Above SMA50: {indicators.get('isBullish', 'Unknown')}

Do you AGREE or DISAGREE with the {action} signal? Respond as JSON:
{{"opinion": "AGREE|DISAGREE", "reason": "One sentence explanation."}}"""

        try:
            response = self.llm_client.chat.completions.create(
                model=OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=100
            )
            import re
            raw = response.choices[0].message.content.strip()
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                result = json.loads(match.group(0))
                return result.get('opinion', 'UNKNOWN'), result.get('reason', '')
        except Exception as e:
            log.debug(f"LLM opinion failed: {e}")

        return None, None

    def evaluate_indicator_signal(self, payload):
        """Evaluates technical indicators and generates trade signals."""
        symbol = payload.get('symbol')
        price = payload.get('price', 0)
        atr = payload.get('atr', 0)
        rsi = payload.get('rsi', 50)
        obvStatus = payload.get('obvStatus', 'Neutral')
        isBullish = payload.get('isBullish', None)

        actionSignal = "➖ HOLD"
        trade_action = None

        if rsi > 70 and "Distributing" in obvStatus:
            actionSignal = "TAKE PROFIT (Momentum Fading)"
            trade_action = 'SELL'
        elif rsi > 80:
            actionSignal = "TAKE PROFIT (Extreme Overbought)"
            trade_action = 'SELL'
        elif isBullish is False and "Distributing" in obvStatus:
            actionSignal = f"STOP LOSS (Trend Break. ATR Risk: ${(atr * 2):.2f})"
            trade_action = 'SELL'
        elif rsi < 30 and "Accumulating" in obvStatus:
            sentiment = self.state_data.get('sentiments', {}).get(symbol, 'Neutral')
            if sentiment == 'Bearish':
                actionSignal = f"⚠️ VETOED (News is Bearish)"
            else:
                actionSignal = f"🟢 BUY (Oversold. Suggest Stop: ${(price - (atr * 2)):.2f})"
                trade_action = 'BUY'
        elif isBullish is False and rsi < 40:
            actionSignal = "⚠️ WARNING (Weakness)"

        # ─── Cooldown Check ──────────────────────────────────────────
        if trade_action and self._is_on_cooldown(symbol, trade_action):
            trade_action = None  # Suppress duplicate

        # ─── LLM-as-Judge (Soft Advisory) ────────────────────────────
        llm_tag = ""
        if trade_action:
            indicators = {
                'price': price, 'rsi': rsi, 'atr': atr,
                'obvStatus': obvStatus, 'isBullish': isBullish,
                'sentiment': self.state_data.get('sentiments', {}).get(symbol, 'Neutral')
            }
            opinion, reason = self._ask_llm_opinion(symbol, indicators, trade_action)
            if opinion:
                if opinion == "DISAGREE":
                    llm_tag = f"\n⚠️ **LLM Advisory**: DISAGREES — _{reason}_"
                else:
                    llm_tag = f"\n✅ **LLM Advisory**: AGREES — _{reason}_"

            # Emit trade signal
            bus.publish('trade_signals', {
                'symbol': symbol,
                'action': trade_action,
                'amount': 500,
                'reason': actionSignal,
                'llm_opinion': opinion,
                'llm_reason': reason
            })
            self._set_cooldown(symbol, trade_action)

        # Build table row
        current_sent = self.state_data.get('sentiments', {}).get(symbol, 'Neutral')
        row = f"| **{symbol}** | ${price:.2f} | {atr:.2f} | {rsi:.1f} | {obvStatus} | {current_sent} | `{actionSignal}` |{llm_tag}\n"
        return actionSignal, row

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
                self.cooldowns.clear()  # Reset cooldowns on new day

            has_significant_changes = is_new_day
            markdown_table = "| Ticker | Price | ATR | RSI(14) | OBV Trend | AI Sentiment | Status |\n|---|---|---|---|---|---|---|\n"
            processed_any = False

            for msg in new_messages:
                payload = msg.get('payload', {})
                if payload.get('source') == 'obv_monitor':
                    symbol = payload.get('symbol')
                    if not symbol:
                        continue

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

            if processed_any:
                self._save_state()
                if has_significant_changes:
                    log.info("Actionable alerts found.")
                    bus.publish('notifications', {
                        'type': 'quant_alert',
                        'text': f"🧠 **QUANTITATIVE MARKET SCAN**\n---\n{markdown_table}"
                    })
                else:
                    log.info("No new actionable alerts. Suppressing Telegram.")

        except Exception as e:
            log.error(f"Error processing market data: {e}", exc_info=True)

    def start(self):
        self.running = True
        log.info("QuantAgent started. ZMQ STREAMING ENABLED. Waiting for triggers...")

        while self.running:
            try:
                topic, msg_bytes = self.sub.recv_multipart()
                msg = json.loads(msg_bytes.decode('utf-8'))
                self.process_market_data([msg])
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"ZMQ Error: {e}")


if __name__ == "__main__":
    agent = QuantAgent()
    agent.start()
