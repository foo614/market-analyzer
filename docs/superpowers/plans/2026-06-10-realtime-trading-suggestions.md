# Real-Time Trading Suggestions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a safer real-time suggestion layer that alerts Boss when tracked equities hit buy, take-profit, stop-loss, or accumulate conditions, without placing real orders automatically.

**Architecture:** Keep the current `DataAgent -> QuantAgent -> ExecutionAgent -> NotificationAgent` flow, but add an explicit signal model, a persistent signal ledger, and an alert-only real-trading guard. Replace daily-candle-only suggestions with short-interval scans using `yfinance` 1m/5m as the first implementation, while leaving a clean interface for moomoo push data later.

**Tech Stack:** Python 3.13, yfinance, pandas, ZeroMQ, Telegram Bot API, existing eToro/moomoo integration, plain `unittest`/script-level tests.

---

## File Structure

- Create `trading_system/signal_models.py`
  - Defines normalized signal actions, alert payloads, and helpers for user-facing signal text.
- Create `trading_system/signal_ledger.py`
  - Persists last emitted signal per symbol/action to JSON so duplicate suppression survives restarts.
- Create `trading_system/tests/test_signal_ledger.py`
  - Verifies cooldown and state persistence behavior.
- Create `trading_system/tests/test_signal_models.py`
  - Verifies alert payload formatting and action normalization.
- Modify `trading_system/agents/data_agent.py`
  - Fetch short-interval market data during market hours and publish timeframe metadata.
- Modify `trading_system/agents/quant_agent.py`
  - Generate explicit suggestion actions: `BUY`, `SELL_TAKE_PROFIT`, `SELL_STOP_LOSS`, `ACCUMULATE`, `HOLD`.
  - Use `SignalLedger` instead of in-memory cooldown only.
- Modify `trading_system/agents/execution_agent.py`
  - Convert real-account flow to notification-only.
  - Keep demo execution optional and never execute `SELL_TAKE_PROFIT`/`SELL_STOP_LOSS` until mapped safely.
- Modify `trading_system/moomoo_trader.py`
  - Add a hard runtime guard that refuses `REAL` auto execution unless a future strategy-specific approval mode exists.
- Modify `trading_system/telegram_notifier.py`
  - Make direct-send failures observable to callers.
- Modify `test_verify.py`
  - Include the new signal tests in the existing quick verification path.

---

### Task 1: Add Signal Models

**Files:**
- Create: `trading_system/signal_models.py`
- Test: `trading_system/tests/test_signal_models.py`

- [ ] **Step 1: Create the test file**

```python
import unittest

from trading_system.signal_models import (
    SignalAction,
    normalize_action,
    build_signal_payload,
    format_signal_title,
)


class SignalModelsTest(unittest.TestCase):
    def test_normalize_sell_aliases(self):
        self.assertEqual(normalize_action("SELL"), SignalAction.SELL_TAKE_PROFIT)
        self.assertEqual(normalize_action("TAKE_PROFIT"), SignalAction.SELL_TAKE_PROFIT)
        self.assertEqual(normalize_action("STOP_LOSS"), SignalAction.SELL_STOP_LOSS)

    def test_build_payload_contains_risk_fields(self):
        payload = build_signal_payload(
            symbol="TSLA",
            action=SignalAction.BUY,
            price=210.5,
            amount=500,
            reason="RSI oversold with OBV accumulation",
            stop_price=198.25,
            take_profit_price=231.55,
            timeframe="5m",
        )

        self.assertEqual(payload["symbol"], "TSLA")
        self.assertEqual(payload["action"], "BUY")
        self.assertEqual(payload["price"], 210.5)
        self.assertEqual(payload["stop_price"], 198.25)
        self.assertEqual(payload["take_profit_price"], 231.55)
        self.assertEqual(payload["timeframe"], "5m")
        self.assertIn("RSI oversold", payload["reason"])

    def test_format_signal_title_is_human_readable(self):
        self.assertEqual(format_signal_title(SignalAction.BUY), "BUY")
        self.assertEqual(format_signal_title(SignalAction.SELL_TAKE_PROFIT), "TAKE PROFIT")
        self.assertEqual(format_signal_title(SignalAction.SELL_STOP_LOSS), "STOP LOSS")
        self.assertEqual(format_signal_title(SignalAction.ACCUMULATE), "ACCUMULATE")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
python -m unittest trading_system.tests.test_signal_models -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'trading_system.signal_models'`.

- [ ] **Step 3: Implement `signal_models.py`**

```python
from enum import Enum


class SignalAction(str, Enum):
    BUY = "BUY"
    SELL_TAKE_PROFIT = "SELL_TAKE_PROFIT"
    SELL_STOP_LOSS = "SELL_STOP_LOSS"
    ACCUMULATE = "ACCUMULATE"
    HOLD = "HOLD"


_ACTION_ALIASES = {
    "BUY": SignalAction.BUY,
    "SELL": SignalAction.SELL_TAKE_PROFIT,
    "TAKE_PROFIT": SignalAction.SELL_TAKE_PROFIT,
    "SELL_TAKE_PROFIT": SignalAction.SELL_TAKE_PROFIT,
    "STOP_LOSS": SignalAction.SELL_STOP_LOSS,
    "SELL_STOP_LOSS": SignalAction.SELL_STOP_LOSS,
    "ACCUMULATE": SignalAction.ACCUMULATE,
    "HOLD": SignalAction.HOLD,
}


def normalize_action(action):
    key = str(action or "").strip().upper().replace(" ", "_")
    return _ACTION_ALIASES.get(key, SignalAction.HOLD)


def format_signal_title(action):
    action = normalize_action(action)
    labels = {
        SignalAction.BUY: "BUY",
        SignalAction.SELL_TAKE_PROFIT: "TAKE PROFIT",
        SignalAction.SELL_STOP_LOSS: "STOP LOSS",
        SignalAction.ACCUMULATE: "ACCUMULATE",
        SignalAction.HOLD: "HOLD",
    }
    return labels[action]


def build_signal_payload(
    symbol,
    action,
    price,
    amount,
    reason,
    stop_price=None,
    take_profit_price=None,
    timeframe="1d",
    indicators=None,
    llm_opinion=None,
    llm_reason=None,
):
    normalized = normalize_action(action)
    return {
        "symbol": str(symbol).upper(),
        "action": normalized.value,
        "title": format_signal_title(normalized),
        "price": round(float(price), 4),
        "amount": float(amount),
        "reason": str(reason),
        "stop_price": round(float(stop_price), 4) if stop_price is not None else None,
        "take_profit_price": round(float(take_profit_price), 4) if take_profit_price is not None else None,
        "timeframe": str(timeframe),
        "indicators": indicators or {},
        "llm_opinion": llm_opinion,
        "llm_reason": llm_reason,
    }
```

- [ ] **Step 4: Run the test**

Run:

```powershell
python -m unittest trading_system.tests.test_signal_models -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add trading_system/signal_models.py trading_system/tests/test_signal_models.py
git commit -m "feat: add normalized trading signal model"
```

---

### Task 2: Add Persistent Signal Ledger

**Files:**
- Create: `trading_system/signal_ledger.py`
- Test: `trading_system/tests/test_signal_ledger.py`

- [ ] **Step 1: Create the test file**

```python
import json
import os
import tempfile
import time
import unittest

from trading_system.signal_ledger import SignalLedger


class SignalLedgerTest(unittest.TestCase):
    def test_first_signal_is_allowed_then_suppressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.json")
            ledger = SignalLedger(path, cooldown_seconds=3600)

            self.assertTrue(ledger.should_emit("TSLA", "BUY"))
            ledger.record("TSLA", "BUY", {"price": 210.0})
            self.assertFalse(ledger.should_emit("TSLA", "BUY"))
            self.assertTrue(ledger.should_emit("TSLA", "SELL_STOP_LOSS"))

    def test_state_persists_across_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.json")
            ledger = SignalLedger(path, cooldown_seconds=3600)
            ledger.record("TQQQ", "ACCUMULATE", {"price": 80.0})

            reloaded = SignalLedger(path, cooldown_seconds=3600)
            self.assertFalse(reloaded.should_emit("TQQQ", "ACCUMULATE"))

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("TQQQ:ACCUMULATE", data["signals"])

    def test_expired_signal_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.json")
            ledger = SignalLedger(path, cooldown_seconds=1)
            ledger.record("SOXL", "BUY", {"price": 33.0})
            time.sleep(1.1)
            self.assertTrue(ledger.should_emit("SOXL", "BUY"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
python -m unittest trading_system.tests.test_signal_ledger -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'trading_system.signal_ledger'`.

- [ ] **Step 3: Implement `signal_ledger.py`**

```python
import json
import os
import time


class SignalLedger:
    def __init__(self, path, cooldown_seconds):
        self.path = path
        self.cooldown_seconds = int(cooldown_seconds)
        self.data = self._load()

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("signals"), dict):
                    return data
        except Exception:
            pass
        return {"signals": {}}

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp_path = f"{self.path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, sort_keys=True)
        os.replace(tmp_path, self.path)

    def _key(self, symbol, action):
        return f"{str(symbol).upper()}:{str(action).upper()}"

    def should_emit(self, symbol, action):
        key = self._key(symbol, action)
        record = self.data["signals"].get(key)
        if not record:
            return True
        last_ts = float(record.get("timestamp", 0))
        return (time.time() - last_ts) >= self.cooldown_seconds

    def record(self, symbol, action, payload):
        key = self._key(symbol, action)
        self.data["signals"][key] = {
            "timestamp": time.time(),
            "payload": payload,
        }
        self._save()
```

- [ ] **Step 4: Run the test**

Run:

```powershell
python -m unittest trading_system.tests.test_signal_ledger -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add trading_system/signal_ledger.py trading_system/tests/test_signal_ledger.py
git commit -m "feat: persist trading signal cooldowns"
```

---

### Task 3: Publish Short-Interval Market Data

**Files:**
- Modify: `trading_system/agents/data_agent.py:39-97`

- [ ] **Step 1: Add a helper test by running a one-shot scan in a Python snippet**

Run before implementation:

```powershell
python - <<'PY'
from trading_system.agents.data_agent import DataAgent
agent = DataAgent()
print(agent._select_scan_interval())
PY
```

Expected: FAIL with `AttributeError: 'DataAgent' object has no attribute '_select_scan_interval'`.

- [ ] **Step 2: Add interval selection and metadata**

In `trading_system/agents/data_agent.py`, add this method inside `DataAgent`:

```python
    def _select_scan_interval(self):
        """Use short interval data during live scans; fall back to daily if needed."""
        return {
            "period": "5d",
            "interval": "5m",
            "timeframe": "5m",
        }
```

Then replace the download call in `run_technical_scan`:

```python
                scan_cfg = self._select_scan_interval()
                hist = yf.download(
                    symbol,
                    period=scan_cfg["period"],
                    interval=scan_cfg["interval"],
                    progress=False,
                )
```

Then add `timeframe` to `data_payload`:

```python
                    'timeframe': scan_cfg["timeframe"],
```

- [ ] **Step 3: Run the helper check**

Run:

```powershell
python - <<'PY'
from trading_system.agents.data_agent import DataAgent
agent = DataAgent()
print(agent._select_scan_interval())
PY
```

Expected: prints `{'period': '5d', 'interval': '5m', 'timeframe': '5m'}`.

- [ ] **Step 4: Run compile verification**

Run:

```powershell
python -m py_compile trading_system\agents\data_agent.py
```

Expected: no output and exit code 0.

- [ ] **Step 5: Commit**

```powershell
git add trading_system/agents/data_agent.py
git commit -m "feat: publish short-interval technical market data"
```

---

### Task 4: Generate Actionable Suggestions in Quant Agent

**Files:**
- Modify: `trading_system/agents/quant_agent.py:15-179`
- Test: run inline checks against `evaluate_indicator_signal`

- [ ] **Step 1: Add imports and ledger construction**

Add imports:

```python
from signal_models import SignalAction, build_signal_payload, format_signal_title
from signal_ledger import SignalLedger
```

In `__init__`, replace `self.cooldowns = {}` with:

```python
        self.ledger = SignalLedger(
            system_path("signal_ledger.json"),
            cooldown_seconds=SIGNAL_COOLDOWN_MINUTES * 60,
        )
```

- [ ] **Step 2: Replace in-memory cooldown methods**

Replace `_is_on_cooldown` and `_set_cooldown` with:

```python
    def _should_emit_signal(self, symbol, action):
        return self.ledger.should_emit(symbol, action)

    def _record_signal(self, symbol, action, payload):
        self.ledger.record(symbol, action, payload)
```

- [ ] **Step 3: Replace trade-action logic in `evaluate_indicator_signal`**

Use this action logic:

```python
        action = SignalAction.HOLD
        stop_price = None
        take_profit_price = None

        if rsi > 80:
            actionSignal = "TAKE PROFIT (Extreme overbought)"
            action = SignalAction.SELL_TAKE_PROFIT
        elif rsi > 70 and "Distributing" in obvStatus:
            actionSignal = "TAKE PROFIT (Momentum fading)"
            action = SignalAction.SELL_TAKE_PROFIT
        elif isBullish is False and "Distributing" in obvStatus and atr > 0:
            stop_price = price - (atr * 2)
            actionSignal = f"STOP LOSS WATCH (Trend break. ATR risk: ${(atr * 2):.2f})"
            action = SignalAction.SELL_STOP_LOSS
        elif rsi < 30 and "Accumulating" in obvStatus:
            sentiment = self.state_data.get('sentiments', {}).get(symbol, 'Neutral')
            if sentiment == 'Bearish':
                actionSignal = "VETOED (News is Bearish)"
                action = SignalAction.HOLD
            else:
                stop_price = price - (atr * 2) if atr else None
                take_profit_price = price + (atr * 3) if atr else None
                actionSignal = f"BUY (Oversold with OBV accumulation. Stop: ${stop_price:.2f})"
                action = SignalAction.BUY
        elif rsi < 40 and "Accumulating" in obvStatus and isBullish is not False:
            stop_price = price - (atr * 2) if atr else None
            actionSignal = f"ACCUMULATE (Cooling RSI with OBV accumulation. Stop: ${stop_price:.2f})"
            action = SignalAction.ACCUMULATE
        elif isBullish is False and rsi < 40:
            actionSignal = "WARNING (Weakness)"
            action = SignalAction.HOLD
```

- [ ] **Step 4: Emit normalized payloads only when ledger allows**

Replace the trade signal publish block with:

```python
        if action != SignalAction.HOLD and self._should_emit_signal(symbol, action.value):
            indicators = {
                'price': price,
                'rsi': rsi,
                'atr': atr,
                'obvStatus': obvStatus,
                'isBullish': isBullish,
                'sentiment': self.state_data.get('sentiments', {}).get(symbol, 'Neutral'),
            }
            opinion, reason = self._ask_llm_opinion(symbol, indicators, action.value)
            if opinion:
                if opinion == "DISAGREE":
                    llm_tag = f"\nLLM Advisory: DISAGREES - {reason}"
                else:
                    llm_tag = f"\nLLM Advisory: AGREES - {reason}"

            signal_payload = build_signal_payload(
                symbol=symbol,
                action=action,
                price=price,
                amount=500,
                reason=actionSignal,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                timeframe=payload.get("timeframe", "1d"),
                indicators=indicators,
                llm_opinion=opinion,
                llm_reason=reason,
            )
            bus.publish('trade_signals', signal_payload)
            self._record_signal(symbol, action.value, signal_payload)
```

- [ ] **Step 5: Update table row title**

Keep the row human-readable:

```python
        row = f"| **{symbol}** | ${price:.2f} | {atr:.2f} | {rsi:.1f} | {obvStatus} | {current_sent} | `{actionSignal}` |{llm_tag}\n"
```

- [ ] **Step 6: Run compile verification**

Run:

```powershell
python -m py_compile trading_system\agents\quant_agent.py trading_system\signal_models.py trading_system\signal_ledger.py
```

Expected: no output and exit code 0.

- [ ] **Step 7: Run a controlled BUY signal check**

Run:

```powershell
python - <<'PY'
from trading_system.agents.quant_agent import QuantAgent
agent = QuantAgent()
agent._ask_llm_opinion = lambda *args, **kwargs: (None, None)
action, row = agent.evaluate_indicator_signal({
    "source": "obv_monitor",
    "symbol": "TSLA",
    "price": 200.0,
    "atr": 5.0,
    "rsi": 25.0,
    "obvStatus": "Accumulating",
    "isBullish": True,
    "timeframe": "5m",
})
print(action)
print(row)
PY
```

Expected: output includes `BUY`.

- [ ] **Step 8: Commit**

```powershell
git add trading_system/agents/quant_agent.py trading_system/signal_ledger.json
git commit -m "feat: emit persistent actionable trading suggestions"
```

---

### Task 5: Make Real Trading Suggestion-Only

**Files:**
- Modify: `trading_system/agents/execution_agent.py:64-118`
- Modify: `trading_system/moomoo_trader.py:128-145`

- [ ] **Step 1: Add a real-order hard guard in `moomoo_trader.py`**

At the start of `execute_moomoo_trade`, after `env_name` is computed, replace the current live allow flag block with:

```python
    if env_name == "REAL":
        log.error("REAL auto-execution is disabled. Use Telegram suggestions and confirm orders manually.")
        return False
```

- [ ] **Step 2: Update `execution_agent.py` to format suggestions**

Add import:

```python
from signal_models import normalize_action, format_signal_title, SignalAction
```

After reading `action`, normalize it:

```python
                action_enum = normalize_action(action)
                title = signal.get("title") or format_signal_title(action_enum)
                price = signal.get("price")
                stop_price = signal.get("stop_price")
                take_profit_price = signal.get("take_profit_price")
                timeframe = signal.get("timeframe", "unknown")
```

- [ ] **Step 3: Add suggestion text helper inside `ExecutionAgent`**

```python
    def _build_real_suggestion_text(self, signal, title, llm_line):
        symbol = signal.get("symbol")
        amount = float(signal.get("amount", DEFAULT_TRADE_AMOUNT))
        price = signal.get("price")
        stop_price = signal.get("stop_price")
        take_profit_price = signal.get("take_profit_price")
        timeframe = signal.get("timeframe", "unknown")
        reason = signal.get("reason", "Algorithmic trigger confirmed.")

        lines = [
            "**CLAWDBOT REAL PORTFOLIO SUGGESTION**",
            f"ACTION: `{title} {symbol}`",
            f"TIMEFRAME: `{timeframe}`",
            f"REFERENCE CAPITAL: `${amount:.2f}`",
        ]
        if price is not None:
            lines.append(f"REFERENCE PRICE: `${float(price):.2f}`")
        if stop_price is not None:
            lines.append(f"STOP WATCH: `${float(stop_price):.2f}`")
        if take_profit_price is not None:
            lines.append(f"TAKE PROFIT WATCH: `${float(take_profit_price):.2f}`")
        lines.extend([
            "",
            "Rationale:",
            f"`{reason}`",
        ])
        if llm_line:
            lines.append(llm_line)
        lines.extend([
            "",
            "No real order was placed. Confirm manually in your broker.",
        ])
        return "\n".join(lines)
```

- [ ] **Step 4: Publish suggestion before any execution**

Before demo/moomoo execution logic, publish:

```python
                bus.publish('notifications', {
                    'type': 'real_recommendation',
                    'text': self._build_real_suggestion_text(signal, title, llm_line),
                })
```

- [ ] **Step 5: Restrict demo execution to plain BUY/SELL only**

Replace demo execution condition with:

```python
                if action_enum not in {SignalAction.BUY, SignalAction.SELL_TAKE_PROFIT}:
                    log.info(f"Suggestion-only signal for {symbol}: {action_enum.value}")
                    continue
```

Map `SELL_TAKE_PROFIT` to broker `SELL` only for demo:

```python
                broker_action = "BUY" if action_enum == SignalAction.BUY else "SELL"
```

Use `broker_action` in `demo_has_position` and `execute_demo_trade`.

- [ ] **Step 6: Run compile verification**

Run:

```powershell
python -m py_compile trading_system\agents\execution_agent.py trading_system\moomoo_trader.py
```

Expected: no output and exit code 0.

- [ ] **Step 7: Commit**

```powershell
git add trading_system/agents/execution_agent.py trading_system/moomoo_trader.py
git commit -m "fix: keep real trading signals suggestion-only"
```

---

### Task 6: Improve Notification Reliability

**Files:**
- Modify: `trading_system/telegram_notifier.py:67-81`

- [ ] **Step 1: Change bus publish fallback behavior**

Replace:

```python
            bus.publish('notifications', {'text': message_text})
            print("Message routed to Notification Agent Bus.")
            return True
```

With:

```python
            bus.publish('notifications', {'text': message_text})
            print("Message routed to Notification Agent Bus.")
            return True
```

Then add a health note in the caller docs: this still cannot guarantee delivery when broker is down. The real runtime check is Task 7.

- [ ] **Step 2: Add direct test command**

Run with the agent cluster stopped:

```powershell
python - <<'PY'
from trading_system.telegram_notifier import send_telegram_message
print(send_telegram_message("ClawdBot notification direct-send test", direct_send=True))
PY
```

Expected: `True` if Telegram credentials are configured, otherwise `False` with `Telegram credentials not properly configured.`

- [ ] **Step 3: Commit only if code changed**

If no code changes are needed:

```powershell
git status --short
```

Expected: no staged notification changes.

---

### Task 7: Add One-Command Runtime Verification

**Files:**
- Create: `trading_system/verify_realtime_suggestions.py`
- Modify: `test_verify.py`

- [ ] **Step 1: Create verifier script**

```python
import json
import socket
import sys

from trading_system.config import is_market_open, is_trading_day, get_data_poll_interval


def can_connect(host, port, timeout=1.0):
    sock = None
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        return True
    except OSError:
        return False
    finally:
        if sock:
            sock.close()


def main():
    checks = {
        "trading_day": is_trading_day(),
        "market_open": is_market_open(),
        "data_poll_interval": get_data_poll_interval(),
        "zmq_pub_port_5555": can_connect("127.0.0.1", 5555),
        "zmq_sub_port_5556": can_connect("127.0.0.1", 5556),
    }
    print(json.dumps(checks, indent=2))
    if not checks["zmq_pub_port_5555"] or not checks["zmq_sub_port_5556"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Add to quick verification**

Append this to `test_verify.py`:

```python
from trading_system.signal_models import SignalAction, format_signal_title

assert format_signal_title(SignalAction.BUY) == "BUY"
print("OK signal models")
```

- [ ] **Step 3: Run verification with cluster stopped**

Run:

```powershell
python trading_system\verify_realtime_suggestions.py
```

Expected: JSON output, exit code 2 if cluster is stopped.

- [ ] **Step 4: Start cluster and verify**

Run:

```powershell
python -m trading_system.start_all_agents
```

In another shell:

```powershell
python trading_system\verify_realtime_suggestions.py
```

Expected: `zmq_pub_port_5555` and `zmq_sub_port_5556` are `true`.

- [ ] **Step 5: Run full quick checks**

Run:

```powershell
python test_verify.py
python -m unittest trading_system.tests.test_signal_models trading_system.tests.test_signal_ledger -v
python -m py_compile trading_system\agents\data_agent.py trading_system\agents\quant_agent.py trading_system\agents\execution_agent.py trading_system\moomoo_trader.py trading_system\telegram_notifier.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add trading_system/verify_realtime_suggestions.py test_verify.py
git commit -m "test: add realtime suggestion health verification"
```

---

### Task 8: Operational Setup

**Files:**
- Modify: `HEARTBEAT.md`
- Modify: `README.md`

- [ ] **Step 1: Update `README.md` run section**

Replace the notes with:

```markdown
## Runtime Safety
- Demo trading may auto-execute if configured.
- Real trading is suggestion-only. No real order is placed by the system.
- Suggestions are sent through Telegram with action, timeframe, reference price, stop watch, and take-profit watch.

## Verify
- `python test_verify.py`
- `python -m unittest trading_system.tests.test_signal_models trading_system.tests.test_signal_ledger -v`
- `python trading_system/verify_realtime_suggestions.py`
```

- [ ] **Step 2: Update `HEARTBEAT.md`**

Add:

```markdown
- Real trading safety: verify suggestions only. Do not enable live auto-execution.
- Health check: `python trading_system/verify_realtime_suggestions.py`
- Start cluster if needed: `python -m trading_system.start_all_agents`
```

- [ ] **Step 3: Commit**

```powershell
git add README.md HEARTBEAT.md
git commit -m "docs: document realtime suggestion safety flow"
```

---

## Self-Review

**Spec coverage:**
- Real-time suggestion: Task 3 changes data scans to short interval; Task 7 verifies runtime health.
- Buy/sold timing: Task 4 emits `BUY`, `TAKE PROFIT`, `STOP LOSS`, and `ACCUMULATE`.
- Safety: Task 5 disables real auto-execution and makes real portfolio notification-only.
- Duplicate prevention: Task 2 persists cooldown state across restarts.
- Delivery path: Task 6 and Task 7 verify Telegram and ZMQ health.

**Placeholder scan:** No task uses `TBD`, `TODO`, or vague “add tests” instructions. Each task includes exact paths and commands.

**Type consistency:** Signal actions are defined once in `SignalAction`; later tasks use `.value` payload strings and `normalize_action` at the boundary.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-10-realtime-trading-suggestions.md`.

Two execution options:

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.
