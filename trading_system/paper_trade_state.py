"""
Persistent state for the eToro demo paper-trade agent.
"""

import json
import os
import time

try:
    from .config import system_path
except ImportError:
    from config import system_path


def _empty_state():
    return {
        "last_backtest_at": None,
        "backtest_results": {},
        "gate_passed": {},
        "positions": {},
        "last_signal": {},
        "last_order": {},
        "cooldowns": {},
        "mode": "dry_run",
    }


class PaperTradeState:
    def __init__(self, path=None):
        self.path = path or system_path("paper_trade_state.json")
        self.data = self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return _empty_state()

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("state root must be an object")
        except Exception:
            backup_path = self.path + ".bak"
            try:
                if os.path.exists(backup_path):
                    os.remove(backup_path)
                os.replace(self.path, backup_path)
            except Exception:
                pass
            return _empty_state()

        base = _empty_state()
        base.update(data)
        for key, default in _empty_state().items():
            if key not in base or not isinstance(base[key], type(default)) and default is not None:
                base[key] = default
        return base

    def save(self):
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, sort_keys=True)
        os.replace(tmp_path, self.path)

    def set_mode(self, mode):
        self.data["mode"] = str(mode or "dry_run")
        self.save()

    def set_backtest(self, symbol, result, gate):
        symbol = str(symbol).upper()
        self.data["last_backtest_at"] = time.time()
        self.data["backtest_results"][symbol] = self._compact_backtest_result(result)
        self.data["gate_passed"][symbol] = bool((gate or {}).get("passed"))
        self.save()

    def _compact_backtest_result(self, result):
        result = result or {}
        compact = {
            "symbol": result.get("symbol"),
            "generated_at": result.get("generated_at"),
            "metrics": result.get("metrics"),
        }
        if result.get("error"):
            compact["error"] = result.get("error")
        return compact

    def set_position(self, symbol, has_position, metadata=None):
        symbol = str(symbol).upper()
        if has_position:
            self.data["positions"][symbol] = metadata or {"source": "paper_state"}
        else:
            self.data["positions"].pop(symbol, None)
        self.save()

    def has_position(self, symbol):
        return str(symbol).upper() in self.data.get("positions", {})

    def cooldown_key(self, symbol, action):
        return f"{str(symbol).upper()}:{str(action).upper()}"

    def cooldown_allows(self, symbol, action, cooldown_minutes, now=None):
        now = time.time() if now is None else float(now)
        last_ts = float(self.data.get("cooldowns", {}).get(self.cooldown_key(symbol, action), 0) or 0)
        return (now - last_ts) >= (float(cooldown_minutes) * 60.0)

    def record_signal(self, symbol, action, signal, now=None):
        symbol = str(symbol).upper()
        now = time.time() if now is None else float(now)
        self.data["last_signal"][symbol] = {
            "action": str(action).upper(),
            "timestamp": now,
            "signal": signal,
        }
        self.save()

    def record_order(self, symbol, action, order, now=None):
        symbol = str(symbol).upper()
        action = str(action).upper()
        now = time.time() if now is None else float(now)
        self.data["last_order"][symbol] = {
            "action": action,
            "timestamp": now,
            "order": order,
        }
        self.data["cooldowns"][self.cooldown_key(symbol, action)] = now
        self.save()
