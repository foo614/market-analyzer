from dataclasses import dataclass, field

import pandas as pd


@dataclass
class ReplayScenario:
    symbol: str
    signal: dict
    expected_action: str
    expected_status: str
    frame: pd.DataFrame | None = None


@dataclass
class FakeBroker:
    positions: dict = field(default_factory=dict)
    buy_result: bool = True
    close_result: bool = True
    buy_calls: list = field(default_factory=list, init=False)
    close_calls: list = field(default_factory=list, init=False)

    def __post_init__(self):
        self.positions = {str(symbol).upper(): bool(value) for symbol, value in self.positions.items()}

    def buy(self, symbol, action, amount):
        symbol = str(symbol).upper()
        action = str(action).upper()
        amount = float(amount)
        self.buy_calls.append((symbol, action, amount))
        if self.buy_result and action == "BUY":
            self.positions[symbol] = True
        return self.buy_result

    def close(self, symbol):
        symbol = str(symbol).upper()
        self.close_calls.append(symbol)
        if self.close_result:
            self.positions.pop(symbol, None)
        return self.close_result

    def has_position(self, symbol):
        return bool(self.positions.get(str(symbol).upper()))


@dataclass
class FakeNotifier:
    messages: list = field(default_factory=list)
    payloads: list = field(default_factory=list)

    def __call__(self, payload):
        if isinstance(payload, dict):
            self.payloads.append(payload)
            self.messages.append(str(payload.get("text", payload)))
        else:
            self.messages.append(str(payload))
        return True


def make_frame(closes=None, volumes=None):
    closes = closes or [100 + (i * 0.5) for i in range(80)]
    volumes = volumes or [1200] * len(closes)
    rows = []
    for close, volume in zip(closes, volumes):
        rows.append({
            "Open": close - 0.2,
            "High": close + 0.6,
            "Low": close - 0.6,
            "Close": close,
            "Volume": volume,
        })
    return pd.DataFrame(rows)


def passing_backtest(symbol):
    return {
        "symbol": str(symbol).upper(),
        "metrics": {
            "closed_trades": 4,
            "total_return_pct": 10.0,
            "win_rate_pct": 50.0,
            "max_drawdown_pct": 8.0,
            "buy_hold_return_pct": 6.0,
            "buy_hold_max_drawdown_pct": 15.0,
        },
        "trades": [],
    }


def failing_backtest(symbol):
    result = passing_backtest(symbol)
    result["metrics"]["max_drawdown_pct"] = 80.0
    return result
