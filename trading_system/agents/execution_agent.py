import json
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.message_bus import bus
from agents.paper_trade_agent import PaperTradeAgent
from config import DEFAULT_TRADE_AMOUNT, get_demo_execution_mode, get_execution_broker
from logger import get_logger
from moomoo_trader import execute_moomoo_trade
from risk_manager import check_circuit_breaker
from signal_model import HOLD, category_title, payload_signal_category


log = get_logger("ExecutionAgent")


class ExecutionAgent:
    """
    Listens for trade_signals on the message bus.
    Routes eToro demo handling through PaperTradeAgent and keeps real account signals manual.
    """

    def __init__(self):
        self.sub = bus.get_sub("trade_signals")
        self.running = False
        log.info("ExecutionAgent Initialized [PAPER-GATED MODE]")

    def _paper_notifier(self, text):
        bus.publish("notifications", {"type": "paper_trade_report", "text": text})
        return True

    def _publish_real_recommendation(self, symbol, action, amount, reason, llm_line, paper_result=None, signal_category=None):
        recommendation_label = category_title(signal_category) if signal_category and signal_category != HOLD else action
        paper_line = ""
        if paper_result:
            paper_line = f"\n**Paper Gate:** `{paper_result.get('status', 'unknown')}`"

        bus.publish(
            "notifications",
            {
                "type": "real_recommendation",
                "text": (
                    f"**CLAWDBOT SIGNAL (REAL PORTFOLIO)**\n"
                    f"**ACTION**: `{recommendation_label} {symbol}`\n"
                    f"**CAPITAL**: `${amount:.2f}`{paper_line}\n\n"
                    f"**Quant Rationale & Risk Desk:**\n"
                    f"`{reason}`{llm_line}\n\n"
                    f"*Action required: Execute manually in your broker.*"
                ),
            },
        )

    def process_signal(self, signal):
        symbol = signal.get("symbol")
        action = signal.get("action")
        amount = signal.get("amount", DEFAULT_TRADE_AMOUNT)

        if not symbol or not action:
            return None

        try:
            amount = float(amount)
        except Exception:
            amount = float(DEFAULT_TRADE_AMOUNT)

        symbol = str(symbol).strip().upper()
        action = str(action).strip().upper()
        log.info(f"Received {action} signal for {symbol}. Processing...")

        reason = signal.get("reason", "Algorithmic trigger confirmed.")
        llm_opinion = signal.get("llm_opinion")
        llm_reason = signal.get("llm_reason")
        signal_category = payload_signal_category(signal)

        if check_circuit_breaker():
            bus.publish(
                "notifications",
                {
                    "type": "trade_blocked",
                    "text": f"**ExecutionAgent**\nCircuit breaker active. Blocked: {action} {symbol} (${amount}).",
                },
            )
            return {"status": "blocked", "symbol": symbol, "action": action}

        llm_line = ""
        if llm_opinion:
            flag = "AGREE" if llm_opinion == "AGREE" else "DISAGREE"
            llm_line = f"\n\n**LLM Advisory**: {flag}\n_{llm_reason}_"

        broker = get_execution_broker()
        if broker == "moomoo":
            log.warning("Moomoo auto-execution is disabled; routing signal through paper gate.")

        paper_signal = dict(signal)
        paper_signal["symbol"] = symbol
        paper_signal["action"] = action
        paper_signal["tradeAction"] = action
        paper_signal.setdefault("signal", action)
        paper_signal["signalCategory"] = signal_category
        paper_signal.setdefault("reason", reason)

        paper_agent = PaperTradeAgent(
            mode=get_demo_execution_mode(),
            symbols=[symbol],
            trade_amount=amount,
            notifier=self._paper_notifier,
        )
        paper_result = paper_agent.evaluate_signal(paper_signal)
        self._publish_real_recommendation(
            symbol,
            action,
            amount,
            reason,
            llm_line,
            paper_result=paper_result,
            signal_category=signal_category,
        )
        return paper_result

    def start(self):
        self.running = True
        log.info("Listening on ZMQ for 'trade_signals' payloads...")

        while self.running:
            try:
                topic, msg_bytes = self.sub.recv_multipart()
                msg = json.loads(msg_bytes.decode("utf-8"))
                self.process_signal(msg.get("payload", {}))
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"ZMQ Error: {e}")


if __name__ == "__main__":
    agent = ExecutionAgent()
    agent.start()
