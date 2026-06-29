# eToro Paper-Trade Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone eToro demo paper-trade agent that backtests existing indicators before it can place demo orders.

**Architecture:** Add a small backtest/gate module, a JSON state module, and a standalone `PaperTradeAgent`. The agent defaults to `dry-run`, calls eToro demo buy only through the existing open-order helper, and closes demo positions through a new close-position helper instead of using an open sell order.

**Tech Stack:** Python 3.13, pandas, yfinance, existing eToro REST helpers, Telegram notifier, `unittest`.

---

## File Structure

- Create `trading_system/paper_trade_backtester.py`: generate trend signals, simulate trades, calculate metrics, apply pass/fail gate.
- Create `trading_system/paper_trade_state.py`: persist paper-agent backtest, position, order, and cooldown state.
- Create `trading_system/agents/paper_trade_agent.py`: CLI/runtime loop for dry-run and demo execution.
- Modify `trading_system/auto_trader.py`: add safe demo close-position helpers.
- Create tests:
  - `trading_system/tests/test_paper_trade_backtester.py`
  - `trading_system/tests/test_paper_trade_state.py`
  - `trading_system/tests/test_paper_trade_agent.py`

## Task 1: Backtest and Gate Module

**Files:**
- Create: `trading_system/paper_trade_backtester.py`
- Test: `trading_system/tests/test_paper_trade_backtester.py`

- [ ] Write tests for signal generation, simulation metrics, and pass/fail gates.
- [ ] Run `python -m unittest trading_system.tests.test_paper_trade_backtester -v`; expect import failure before implementation.
- [ ] Implement `BacktestGateConfig`, `generate_trend_signals`, `simulate_trades`, `calculate_metrics`, `run_backtest_for_frame`, `fetch_backtest_history`, `run_symbol_backtest`, and `apply_backtest_gate`.
- [ ] Run the backtester tests; expect pass.

## Task 2: Persistent State Module

**Files:**
- Create: `trading_system/paper_trade_state.py`
- Test: `trading_system/tests/test_paper_trade_state.py`

- [ ] Write tests for position persistence, cooldown checks, order recording, and corrupt-file backup.
- [ ] Run `python -m unittest trading_system.tests.test_paper_trade_state -v`; expect import failure before implementation.
- [ ] Implement `PaperTradeState`.
- [ ] Run the state tests; expect pass.

## Task 3: eToro Demo Close Helper

**Files:**
- Modify: `trading_system/auto_trader.py`
- Test: `trading_system/tests/test_paper_trade_agent.py`

- [ ] Add test coverage through the paper agent to ensure `SELL` calls a close-position function, not `execute_demo_trade(..., "SELL")`.
- [ ] Add `get_demo_position(symbol)` and `close_demo_position(symbol, units_to_deduct=None)` to `auto_trader.py`.
- [ ] Keep `execute_demo_trade` as the demo buy/open helper.
- [ ] Run paper-agent tests after Task 4.

## Task 4: Paper Trade Agent

**Files:**
- Create: `trading_system/agents/paper_trade_agent.py`
- Test: `trading_system/tests/test_paper_trade_agent.py`

- [ ] Write tests for dry-run, failed gate, demo buy, demo sell close, cooldown, and already-in-position skip.
- [ ] Run `python -m unittest trading_system.tests.test_paper_trade_agent -v`; expect import failure before implementation.
- [ ] Implement `PaperTradeAgent`, `format_paper_trade_report`, and CLI parsing.
- [ ] Run paper-agent tests; expect pass.

## Task 5: Verification

**Files:**
- New/modified files from Tasks 1-4.

- [ ] Run focused tests:
  `python -m unittest trading_system.tests.test_paper_trade_backtester trading_system.tests.test_paper_trade_state trading_system.tests.test_paper_trade_agent -v`
- [ ] Run existing related tests:
  `python -m unittest trading_system.tests.test_trend_strategy trading_system.tests.test_stock_telegram_monitor trading_system.tests.test_verify_brokers -v`
- [ ] Compile changed modules:
  `python -m py_compile trading_system\paper_trade_backtester.py trading_system\paper_trade_state.py trading_system\agents\paper_trade_agent.py trading_system\auto_trader.py`
- [ ] Run one dry-run:
  `python trading_system\agents\paper_trade_agent.py --symbols TSLA,TQQQ,SOXL,SPCX --mode dry-run --once`

## Safety Notes

- Default mode is `dry-run`.
- Real trading is not implemented.
- Demo `SELL` uses the close-position endpoint helper.
- No demo execution smoke test is run until dry-run output is reviewed.
