"""
Standalone eToro demo paper-trade agent.

Default mode is dry-run. Demo execution only happens with --mode demo-execute.
Real trading is not implemented here.
"""

import argparse
import os
import sys
import time
from datetime import datetime

SYSTEM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SYSTEM_DIR not in sys.path:
    sys.path.insert(0, SYSTEM_DIR)

from auto_trader import close_demo_position, demo_has_position as etoro_demo_has_position, execute_demo_trade
from paper_trade_backtester import apply_backtest_gate, run_symbol_backtest
from paper_trade_state import PaperTradeState
from telegram_notifier import send_telegram_message
from trend_strategy import analyze_trend_frame


DEFAULT_SYMBOLS = ["TSLA", "TQQQ", "SOXL", "SPCX"]
DEFAULT_TRADE_AMOUNT = 100.0
DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_COOLDOWN_MINUTES = 60


def _normalize_mode(mode):
    value = str(mode or "dry-run").strip().lower().replace("_", "-")
    if value in {"demo", "execute", "demo-execute"}:
        return "demo-execute"
    return "dry-run"


def _format_pct(value):
    try:
        return f"{float(value):+.2f}%"
    except Exception:
        return "N/A"


def _status_label(status):
    labels = {
        "dry_run": "DRY RUN",
        "executed": "EXECUTED",
        "gate_failed": "GATE FAILED",
        "cooldown": "COOLDOWN",
        "no_signal": "NO SIGNAL",
        "already_in_position": "ALREADY IN POSITION",
        "no_position": "NO POSITION",
        "execution_failed": "EXECUTION FAILED",
        "data_error": "DATA ERROR",
    }
    return labels.get(status, str(status).upper())


def format_paper_trade_report(results):
    lines = [
        "**PAPER TRADE REPORT**",
        f"Generated: `{datetime.now().isoformat(timespec='seconds')}`",
        "",
    ]

    for result in results:
        symbol = result.get("symbol", "UNKNOWN")
        status = result.get("status", "unknown")
        action = result.get("action") or "HOLD"
        gate = result.get("gate") or {}
        metrics = gate.get("metrics") or {}
        signal = result.get("signal") or {}
        reasons = gate.get("reasons") or result.get("reasons") or []

        lines.extend([
            f"**{symbol}**",
            f"STATUS: `{_status_label(status)}`",
            f"ACTION: `{action}`",
            f"SIGNAL: `{signal.get('signal', 'HOLD')}`",
            f"TRIGGER: `{signal.get('trigger', 'none')}`",
            f"GATE: `{'PASS' if gate.get('passed') else 'FAIL'}`",
            f"RETURN: `{_format_pct(metrics.get('total_return_pct'))}`",
            f"BUY/HOLD: `{_format_pct(metrics.get('buy_hold_return_pct'))}`",
            f"DRAWDOWN: `{_format_pct(metrics.get('max_drawdown_pct'))}`",
            f"WIN RATE: `{_format_pct(metrics.get('win_rate_pct'))}`",
            f"CLOSED TRADES: `{metrics.get('closed_trades', 'N/A')}`",
        ])
        if reasons:
            lines.append(f"REASONS: `{', '.join(str(r) for r in reasons)}`")
        if signal.get("reason"):
            lines.append(f"READ: `{signal['reason']}`")
        lines.append("")

    lines.append("Demo only. No real order was placed.")
    return "\n".join(lines).strip()


def _default_latest_fetcher(symbol):
    try:
        from broker_providers import fetch_history

        hist, _, _, _ = fetch_history(symbol, provider="auto")
        return hist
    except Exception:
        from paper_trade_backtester import fetch_backtest_history

        return fetch_backtest_history(symbol)


class PaperTradeAgent:
    def __init__(
        self,
        mode="dry-run",
        symbols=None,
        trade_amount=DEFAULT_TRADE_AMOUNT,
        cooldown_minutes=DEFAULT_COOLDOWN_MINUTES,
        state=None,
        backtest_runner=None,
        latest_fetcher=None,
        signal_analyzer=None,
        demo_buy=None,
        demo_close=None,
        demo_has_position=None,
        notifier=None,
    ):
        self.mode = _normalize_mode(mode)
        self.symbols = self._normalize_symbols(symbols or DEFAULT_SYMBOLS)
        self.trade_amount = float(trade_amount)
        self.cooldown_minutes = int(cooldown_minutes)
        self.state = state or PaperTradeState()
        self.backtest_runner = backtest_runner or run_symbol_backtest
        self.latest_fetcher = latest_fetcher or _default_latest_fetcher
        self.signal_analyzer = signal_analyzer or analyze_trend_frame
        self.demo_buy = demo_buy or execute_demo_trade
        self.demo_close = demo_close or close_demo_position
        self.demo_has_position = demo_has_position or etoro_demo_has_position
        self.notifier = notifier or (lambda text: send_telegram_message(text, direct_send=True))
        self.state.set_mode(self.mode.replace("-", "_"))

    def _normalize_symbols(self, symbols):
        if isinstance(symbols, str):
            symbols = symbols.split(",")
        return [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]

    def _has_demo_position(self, symbol):
        if self.state.has_position(symbol):
            return True
        if self.mode == "demo-execute" and self.demo_has_position:
            try:
                return bool(self.demo_has_position(symbol))
            except Exception:
                return False
        return False

    def _analyze_latest_signal(self, symbol, in_position):
        frame = self.latest_fetcher(symbol)
        return self.signal_analyzer(frame, symbol=symbol, timeframe="5m", in_position=in_position)

    def _normalize_external_signal(self, signal):
        normalized = dict(signal or {})
        symbol = str(normalized.get("symbol") or "").strip().upper()
        action = normalized.get("tradeAction") or normalized.get("action")
        action = str(action).strip().upper() if action else None
        normalized["symbol"] = symbol
        normalized["action"] = action
        normalized["tradeAction"] = action
        normalized.setdefault("signal", action or "HOLD")
        normalized.setdefault("trigger", "external_signal")
        normalized.setdefault("reason", "External trading signal.")
        return symbol, normalized

    def _run_backtest_gate(self, symbol, signal=None):
        try:
            backtest = self.backtest_runner(symbol)
            gate = apply_backtest_gate(backtest, symbol)
            self.state.set_backtest(symbol, backtest, gate)
        except Exception as exc:
            result = {
                "symbol": symbol,
                "status": "data_error",
                "action": "HOLD",
                "gate": {"passed": False, "reasons": [str(exc)], "metrics": {}},
                "signal": signal or {"signal": "HOLD", "trigger": "backtest_error", "reason": str(exc)},
            }
            self.notifier(format_paper_trade_report([result]))
            return None, result

        if not gate["passed"]:
            result = {
                "symbol": symbol,
                "status": "gate_failed",
                "action": "HOLD",
                "gate": gate,
                "signal": signal or {"signal": "HOLD", "trigger": "backtest_gate", "reason": "Backtest gate failed."},
            }
            self.notifier(format_paper_trade_report([result]))
            return None, result

        return gate, None

    def _evaluate_signal_after_gate(self, symbol, gate, signal, in_position=None):
        action = signal.get("tradeAction")
        action = str(action).upper() if action else None
        self.state.record_signal(symbol, action or "HOLD", signal)

        if action not in {"BUY", "SELL"}:
            result = {"symbol": symbol, "status": "no_signal", "action": "HOLD", "gate": gate, "signal": signal}
            self.notifier(format_paper_trade_report([result]))
            return result

        if not self.state.cooldown_allows(symbol, action, self.cooldown_minutes):
            result = {"symbol": symbol, "status": "cooldown", "action": action, "gate": gate, "signal": signal}
            self.notifier(format_paper_trade_report([result]))
            return result

        if in_position is None:
            in_position = self._has_demo_position(symbol)

        if action == "BUY" and in_position:
            result = {"symbol": symbol, "status": "already_in_position", "action": action, "gate": gate, "signal": signal}
            self.notifier(format_paper_trade_report([result]))
            return result

        if action == "SELL" and not in_position:
            result = {"symbol": symbol, "status": "no_position", "action": action, "gate": gate, "signal": signal}
            self.notifier(format_paper_trade_report([result]))
            return result

        if self.mode == "dry-run":
            order = {"status": "dry_run", "amount": self.trade_amount}
            self.state.record_order(symbol, action, order)
            result = {"symbol": symbol, "status": "dry_run", "action": action, "gate": gate, "signal": signal}
            self.notifier(format_paper_trade_report([result]))
            return result

        if action == "BUY":
            success = self.demo_buy(symbol, "BUY", self.trade_amount)
            if success:
                self.state.set_position(symbol, True, {"source": "etoro_demo", "amount": self.trade_amount})
        else:
            success = self.demo_close(symbol)
            if success:
                self.state.set_position(symbol, False)

        status = "executed" if success else "execution_failed"
        order = {"status": status, "amount": self.trade_amount}
        self.state.record_order(symbol, action, order)
        result = {"symbol": symbol, "status": status, "action": action, "gate": gate, "signal": signal}
        self.notifier(format_paper_trade_report([result]))
        return result

    def evaluate_signal(self, signal):
        symbol, normalized = self._normalize_external_signal(signal)
        if not symbol:
            result = {
                "symbol": "UNKNOWN",
                "status": "data_error",
                "action": "HOLD",
                "gate": {"passed": False, "reasons": ["missing_symbol"], "metrics": {}},
                "signal": normalized,
            }
            self.notifier(format_paper_trade_report([result]))
            return result

        gate, result = self._run_backtest_gate(symbol, signal=normalized)
        if result:
            return result

        return self._evaluate_signal_after_gate(symbol, gate, normalized)

    def evaluate_symbol(self, symbol):
        symbol = str(symbol).upper()
        gate, result = self._run_backtest_gate(symbol)
        if result:
            return result

        in_position = self._has_demo_position(symbol)
        try:
            signal = self._analyze_latest_signal(symbol, in_position=in_position)
        except Exception as exc:
            signal = {"signal": "HOLD", "tradeAction": None, "trigger": "latest_data_error", "reason": str(exc)}

        return self._evaluate_signal_after_gate(symbol, gate, signal, in_position=in_position)

    def run_once(self, symbols=None):
        selected = self._normalize_symbols(symbols or self.symbols)
        return [self.evaluate_symbol(symbol) for symbol in selected]


def _split_arg(value):
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def main():
    parser = argparse.ArgumentParser(description="Backtest-gated eToro demo paper-trade agent.")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="Comma-separated symbols.")
    parser.add_argument("--mode", default="dry-run", choices=["dry-run", "demo-execute"], help="Runtime mode.")
    parser.add_argument("--amount", type=float, default=DEFAULT_TRADE_AMOUNT, help="Demo order amount in USD.")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS, help="Polling interval in seconds.")
    parser.add_argument("--cooldown-minutes", type=int, default=DEFAULT_COOLDOWN_MINUTES, help="Per-symbol/action cooldown.")
    parser.add_argument("--once", action="store_true", help="Run one cycle then exit.")
    args = parser.parse_args()

    agent = PaperTradeAgent(
        mode=args.mode,
        symbols=_split_arg(args.symbols),
        trade_amount=args.amount,
        cooldown_minutes=args.cooldown_minutes,
    )

    while True:
        agent.run_once()
        if args.once:
            return
        time.sleep(max(args.interval, 60))


if __name__ == "__main__":
    main()
