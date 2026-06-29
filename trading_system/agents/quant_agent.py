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
from logger import get_logger
from config import SIGNAL_COOLDOWN_MINUTES, system_path
from llm_router import llm_router
from signal_model import category_title, category_trade_action, payload_signal_category

log = get_logger("QuantAgent")


def _fmt_num(value, decimals=2):
    try:
        return f"{float(value):.{decimals}f}"
    except Exception:
        return "0.00"


class QuantAgent:
    """
    The Brain of the system.
    Listens to market_data via ZMQ.
    Emits BUY/SELL trade signals and quant scan notifications.
    """
    def __init__(self):
        self.consumer_name = 'quant_agent'
        self.sub = bus.get_sub('market_data')
        self.running = False

        self.state_file = system_path('quant_alert_state.json')
        self.state_data = self._load_state()
        self.signal_ledger_file = system_path('signal_ledger.json')
        self.signal_ledger = self._load_signal_ledger()

        self.cooldowns = {}
        self.start_time = time.time()

        self.strategy_params = {
            'TSLA': {'rsi_buy': 30, 'rsi_sell': 70, 'obv_fast': 7, 'obv_slow': 10},
            'TQQQ': {'rsi_buy': 30, 'rsi_sell': 70, 'obv_fast': 5, 'obv_slow': 10},
            'SOXL': {'rsi_buy': 30, 'rsi_sell': 70, 'obv_fast': 5, 'obv_slow': 10},
            'SPCX': {'rsi_buy': 30, 'rsi_sell': 70, 'obv_fast': 5, 'obv_slow': 10}
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

    def _load_signal_ledger(self):
        try:
            if os.path.exists(self.signal_ledger_file):
                with open(self.signal_ledger_file, 'r') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def _save_signal_ledger(self):
        try:
            tmp_path = self.signal_ledger_file + ".tmp"
            with open(tmp_path, 'w') as f:
                json.dump(self.signal_ledger, f, indent=2, sort_keys=True)
            os.replace(tmp_path, self.signal_ledger_file)
        except Exception:
            pass

    def _ledger_key(self, symbol, action):
        return f"{str(symbol).upper()}:{str(action).upper()}"

    def _payload_bar_ts(self, payload):
        return (
            payload.get('latestBarTs')
            or payload.get('latest_bar_ts')
            or payload.get('barTimestamp')
            or payload.get('bar_ts')
        )

    def _is_on_cooldown(self, symbol, action, payload=None):
        payload = payload or {}
        key = f"{symbol}_{action}"
        last_time = self.cooldowns.get(key, 0)
        elapsed = (time.time() - last_time) / 60
        if elapsed < SIGNAL_COOLDOWN_MINUTES:
            log.debug(f"Signal {action} {symbol} suppressed (cooldown: {elapsed:.0f}/{SIGNAL_COOLDOWN_MINUTES}min)")
            return True

        ledger_key = self._ledger_key(symbol, action)
        last = self.signal_ledger.get(ledger_key, {})
        latest_bar_ts = self._payload_bar_ts(payload)
        trigger = payload.get('trigger')
        if latest_bar_ts and last.get('latestBarTs') == latest_bar_ts and last.get('trigger') == trigger:
            log.debug(f"Signal {action} {symbol} suppressed (same bar/trigger: {trigger})")
            return True

        sent_ts = float(last.get('sentTs', 0) or 0)
        if sent_ts:
            elapsed = (time.time() - sent_ts) / 60
            if elapsed < SIGNAL_COOLDOWN_MINUTES:
                log.debug(f"Signal {action} {symbol} suppressed (ledger cooldown: {elapsed:.0f}/{SIGNAL_COOLDOWN_MINUTES}min)")
                return True
        return False

    def _set_cooldown(self, symbol, action, payload=None):
        payload = payload or {}
        self.cooldowns[f"{symbol}_{action}"] = time.time()
        ledger_key = self._ledger_key(symbol, action)
        self.signal_ledger[ledger_key] = {
            "sentTs": time.time(),
            "symbol": str(symbol).upper(),
            "action": str(action).upper(),
            "trigger": payload.get('trigger'),
            "signal": payload.get('signal'),
            "latestBarTs": self._payload_bar_ts(payload),
            "price": payload.get('price'),
        }
        self._save_signal_ledger()

    def _ask_llm_opinion(self, symbol, indicators, action):
        """
        Ask LLM for a second opinion. Advisory only; it does not block signals.
        """
        prompt = f"""You are a quantitative trading risk advisor. A trading algorithm has generated a {action} signal for {symbol}.

Current indicators:
- Price: ${_fmt_num(indicators.get('price'))}
- RSI(14): {_fmt_num(indicators.get('rsi'), 1)}
- ATR: {_fmt_num(indicators.get('atr'))}
- OBV Trend: {indicators.get('obvStatus', 'Unknown')}
- Trend Status: {indicators.get('trendStatus', 'Unknown')}
- EMA9/21/50: {_fmt_num(indicators.get('ema9'))} / {_fmt_num(indicators.get('ema21'))} / {_fmt_num(indicators.get('ema50'))}
- VWAP: {_fmt_num(indicators.get('vwap'))}
- MACD Hist: {_fmt_num(indicators.get('macdHist'), 4)}
- AI Sentiment: {indicators.get('sentiment', 'Neutral')}
- Above SMA50: {indicators.get('isBullish', 'Unknown')}

Do you AGREE or DISAGREE with the {action} signal? Respond as JSON:
{{"opinion": "AGREE|DISAGREE", "reason": "One sentence explanation."}}"""

        try:
            raw_text, source = llm_router.route_request(prompt, expect_json=True, agent_name="QuantAgent")
            if raw_text:
                import re
                match = re.search(r'\{.*\}', raw_text, re.DOTALL)
                if match:
                    result = json.loads(match.group(0))
                    return result.get('opinion', 'UNKNOWN'), result.get('reason', '')
        except Exception as e:
            log.debug(f"LLM opinion failed: {e}")

        return None, None

    def _evaluate_legacy_payload(self, payload, symbol, price, atr, rsi, obv_status, is_bullish):
        action_signal = "HOLD"
        trade_action = None

        if rsi > 70 and "Distributing" in obv_status:
            action_signal = "TAKE PROFIT (Momentum Fading)"
            trade_action = 'SELL'
        elif rsi > 80:
            action_signal = "TAKE PROFIT (Extreme Overbought)"
            trade_action = 'SELL'
        elif is_bullish is False and "Distributing" in obv_status:
            action_signal = f"WARNING (Trend Break. ATR Risk: ${(atr * 2):.2f})"
        elif rsi < 30 and "Accumulating" in obv_status:
            sentiment = self.state_data.get('sentiments', {}).get(symbol, 'Neutral')
            if sentiment == 'Bearish':
                action_signal = "VETOED (News is Bearish)"
            else:
                action_signal = f"BUY (Oversold. Suggest Stop: ${(price - (atr * 2)):.2f})"
                trade_action = 'BUY'
        elif is_bullish is False and rsi < 40:
            action_signal = "WARNING (Weakness)"

        return action_signal, trade_action, action_signal

    def evaluate_indicator_signal(self, payload):
        """Evaluate a market-data payload and optionally emit a trade signal."""
        symbol = payload.get('symbol')
        price = payload.get('price', 0)
        atr = payload.get('atr', 0)
        rsi = payload.get('rsi', 50)
        obv_status = payload.get('obvStatus', 'Neutral')
        is_bullish = payload.get('isBullish', None)

        if payload.get('source') == 'trend_monitor' or payload.get('strategy') == 'aggressive_ema_vwap_trend':
            raw_signal = payload.get('signal') or "HOLD"
            reason_text = payload.get('reason') or raw_signal
        else:
            raw_signal, _legacy_trade_action, reason_text = self._evaluate_legacy_payload(
                payload, symbol, price, atr, rsi, obv_status, is_bullish
            )

        signal_category = payload_signal_category({**payload, "signal": raw_signal})
        action_signal = category_title(signal_category)
        trade_action = category_trade_action(signal_category)

        if trade_action and self._is_on_cooldown(symbol, signal_category, payload):
            trade_action = None

        llm_tag = ""
        if trade_action:
            indicators = {
                'price': price,
                'rsi': rsi,
                'atr': atr,
                'obvStatus': obv_status,
                'isBullish': is_bullish,
                'trendStatus': payload.get('trendStatus', 'Unknown'),
                'ema9': payload.get('ema9', 0),
                'ema21': payload.get('ema21', 0),
                'ema50': payload.get('ema50', 0),
                'vwap': payload.get('vwap', 0),
                'macdHist': payload.get('macdHist', 0),
                'sentiment': self.state_data.get('sentiments', {}).get(symbol, 'Neutral')
            }
            opinion, reason = self._ask_llm_opinion(symbol, indicators, action_signal)
            if opinion:
                if opinion == "DISAGREE":
                    llm_tag = f"\nLLM Advisory: DISAGREES - {reason}"
                else:
                    llm_tag = f"\nLLM Advisory: AGREES - {reason}"

            bus.publish('trade_signals', {
                'symbol': symbol,
                'action': trade_action,
                'amount': payload.get('amount', 500),
                'reason': reason_text,
                'signal': raw_signal,
                'signalCategory': signal_category,
                'timeframe': payload.get('timeframe'),
                'trigger': payload.get('trigger'),
                'price': price,
                'stopPrice': payload.get('stopPrice'),
                'llm_opinion': opinion,
                'llm_reason': reason
            })
            self._set_cooldown(symbol, signal_category, {**payload, "signal": raw_signal})

        current_sent = self.state_data.get('sentiments', {}).get(symbol, 'Neutral')
        row = f"| **{symbol}** | ${price:.2f} | {atr:.2f} | {rsi:.1f} | {obv_status} | {current_sent} | `{action_signal}` |{llm_tag}\n"
        return action_signal, row

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
                self.cooldowns.clear()

            has_significant_changes = is_new_day
            markdown_table = "| Ticker | Price | ATR | RSI(14) | OBV Trend | AI Sentiment | Status |\n|---|---|---|---|---|---|---|\n"
            processed_any = False

            for msg in new_messages:
                payload = msg.get('payload', {})
                if payload.get('source') in ('obv_monitor', 'trend_monitor'):
                    symbol = payload.get('symbol')
                    if not symbol:
                        continue

                    action, row = self.evaluate_indicator_signal(payload)
                    markdown_table += row
                    processed_any = True

                    prev_action = self.state_data['states'].get(symbol)
                    if not is_new_day and prev_action != action and action != "HOLD":
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
                        'text': f"**QUANTITATIVE MARKET SCAN**\n---\n{markdown_table}"
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
