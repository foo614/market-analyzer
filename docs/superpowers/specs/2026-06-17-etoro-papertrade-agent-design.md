# eToro Paper-Trade Agent Design

Date: 2026-06-17
Status: Approved design, pending implementation plan

## Goal

Build a paper-only auto-trading agent that uses the existing trading indicators to decide whether eToro demo orders are allowed. The agent must backtest the strategy first, gate each symbol by measurable performance, and only then place eToro demo trades. Real trading remains disabled and out of scope.

The first tracked symbols are:

- `TSLA`
- `TQQQ`
- `SOXL`
- `SPCX`

## Current Context

The repo already has the core building blocks:

- `trading_system/indicators.py`: RSI, OBV, MACD, ATR, SMA, VWAP helpers.
- `trading_system/trend_strategy.py`: aggressive 5-minute EMA/VWAP trend strategy with `BUY` and `SELL` trade actions.
- `trading_system/backtest_framework.py`: existing backtest and metric utilities.
- `trading_system/auto_trader.py`: eToro demo execution through `execute_demo_trade`.
- `trading_system/telegram_notifier.py`: Telegram delivery.

The current `ExecutionAgent` is broad and listens to all `trade_signals`. The paper-trade agent should not depend on it in the first implementation. A standalone agent is safer because it can enforce its own backtest gate before it calls eToro demo execution.

Relevant eToro API constraints:

- eToro demo market orders by cash amount are supported through the demo trading execution endpoint.
- eToro trade execution requests have a lower rate limit than read requests, so the agent must cache instrument IDs and throttle order attempts.
- Demo and real environments use different account endpoints and user keys. This design uses only demo account execution.

## Scope

### In Scope

- Backtest the approved strategy before demo trading.
- Produce pass/fail gate results per symbol.
- Run a periodic paper-trade loop.
- Execute eToro demo `BUY` or `SELL` only when the symbol passes the gate and a fresh signal appears.
- Persist paper-agent state to disk.
- Send Telegram reports for backtest results, skipped trades, and demo execution results.
- Provide a dry-run mode that never calls eToro order execution.

### Out of Scope

- Real eToro order execution.
- Moomoo paper or live execution.
- Options trading.
- Margin/leverage optimization.
- Multi-strategy portfolio allocation.
- Automatic parameter optimization as a first release gate.

## Recommended Architecture

Create these files:

- `trading_system/paper_trade_backtester.py`
- `trading_system/paper_trade_state.py`
- `trading_system/agents/paper_trade_agent.py`
- `trading_system/tests/test_paper_trade_backtester.py`
- `trading_system/tests/test_paper_trade_state.py`
- `trading_system/tests/test_paper_trade_agent.py`

Use the existing files:

- `trading_system/trend_strategy.py`
- `trading_system/auto_trader.py`
- `trading_system/telegram_notifier.py`
- `trading_system/broker_providers.py` if available for data fallback.

## Data Flow

1. Load symbol list and config.
2. Fetch historical OHLCV data.
3. Run the strategy over history.
4. Simulate trades from generated `BUY` and `SELL` actions.
5. Calculate performance metrics.
6. Apply the gate.
7. If the gate passes, evaluate latest market data for a fresh signal.
8. If a fresh signal exists and cooldown allows it, call eToro demo execution.
9. Persist state.
10. Send Telegram report.

## Strategy

Use `analyze_trend_frame` from `trend_strategy.py` as the first live strategy because it already includes the current preferred indicators:

- EMA 9/21/50 trend alignment
- VWAP strength
- MACD histogram
- OBV accumulation/distribution
- Volume ratio
- ATR trailing stop
- RSI context

Backtesting should reuse the same indicator logic where possible. If a vectorized backtest helper is needed, it should be derived from `trend_strategy.py` rather than duplicating different rules.

## Backtest Gate

Default gate:

- `min_closed_trades`: `3`
- `min_total_return_pct`: `0`
- `min_win_rate_pct`: `45`
- `require_beats_buy_hold_or_lower_drawdown`: `true`
- `trade_amount`: `$100`
- `cooldown_minutes`: `60`

Per-symbol max drawdown:

- `TSLA`: `25%`
- `TQQQ`: `35%`
- `SOXL`: `35%`
- `SPCX`: `40%`

A symbol fails closed if any required metric is unavailable.

## Demo Execution Rules

The agent can call eToro demo execution only when all conditions are true:

- The symbol passed the latest backtest gate.
- The latest signal is `BUY` or `SELL`.
- The signal is not on cooldown.
- For `BUY`, the paper state says no open demo position for that symbol, unless pyramiding is explicitly enabled later.
- For `SELL`, the paper state or eToro demo portfolio says a demo position exists.
- The configured mode is not `dry-run`.

The first release should use fixed cash sizing:

- Default demo order amount: `$100`
- Leverage: `1`
- No automatic stop-loss/take-profit order fields in the first release. Stop and TP stay as Telegram guidance until close-order handling is verified.

## State

Persist to `trading_system/paper_trade_state.json`.

State fields:

- `last_backtest_at`
- `backtest_results` by symbol
- `gate_passed` by symbol
- `positions` by symbol
- `last_signal` by symbol
- `last_order` by symbol
- `cooldowns` by symbol/action
- `mode`: `dry_run` or `demo_execute`

State is advisory. Before a `SELL`, the agent should also check eToro demo portfolio when available.

## Telegram Reports

Backtest report should include:

- Symbol
- Gate result: `PASS` or `FAIL`
- Total return
- Buy-and-hold return
- Max drawdown
- Win rate
- Total closed trades
- Reason for failure when failed

Trade report should include:

- `PAPER TRADE`
- Symbol
- Action
- Amount
- Signal trigger
- Reference price
- Backtest gate summary
- Result: executed, skipped, failed, or dry-run

Every report must include:

- `Demo only. No real order was placed.`

## Error Handling

- If historical data fetch fails, mark the symbol as gate failed for that cycle.
- If eToro instrument ID resolution fails, skip execution and send Telegram failure.
- If eToro demo order returns non-2xx, log the response status and send Telegram failure without retrying immediately.
- If Telegram fails, log locally and continue.
- If state file is corrupt, start from empty state and preserve the bad file as `.bak`.

## Runtime

CLI:

```powershell
python trading_system\agents\paper_trade_agent.py --symbols TSLA,TQQQ,SOXL,SPCX --mode dry-run --once
python trading_system\agents\paper_trade_agent.py --symbols TSLA,TQQQ,SOXL,SPCX --mode demo-execute --interval 300
```

Default mode must be `dry-run`.

## Testing

Unit tests:

- Backtest metrics are calculated correctly from deterministic OHLCV frames.
- Gate passes/fails on expected thresholds.
- Cooldown suppresses repeated orders.
- `BUY` is skipped when already in paper position.
- `SELL` is skipped when no demo position exists.
- Demo execution is not called in `dry-run`.
- Demo execution is called only after a passing gate in `demo-execute`.

Manual checks:

```powershell
python -m unittest trading_system.tests.test_paper_trade_backtester trading_system.tests.test_paper_trade_state trading_system.tests.test_paper_trade_agent -v
python trading_system\agents\paper_trade_agent.py --symbols TSLA,TQQQ,SOXL,SPCX --mode dry-run --once
```

Demo execution smoke test requires explicit user approval after dry-run output is reviewed:

```powershell
python trading_system\agents\paper_trade_agent.py --symbols TSLA --mode demo-execute --once
```

## Safety Decisions

- Real trading is not implemented.
- Default runtime is dry-run.
- The agent does not use `ExecutionAgent` in the first release.
- The agent does not place stop-loss or take-profit orders yet.
- The agent does not trade failed-gate symbols.
- The agent uses fixed small demo sizing first.

## Implementation Sequence

1. Add backtest metric and gate module.
2. Add persistent state module.
3. Add paper-trade agent in dry-run mode.
4. Add eToro demo execution path behind `--mode demo-execute`.
5. Add Telegram reporting.
6. Add focused tests and run one dry-run.
7. Request approval before any demo execution smoke test.
