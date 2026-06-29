# Trading Operator Runbook

Use this loop before starting or changing the trading agents.

## Safety Boundary

- Real portfolio trading is recommendation-only.
- Demo execution defaults to `dry-run`.
- Do not enable demo execution until the dry-run replay output has been reviewed.
- Do not treat `CLAWDBOT_EXECUTION_BROKER=moomoo` as permission to auto-execute; runtime signals still route through the paper gate.

## Pre-Start Loop

Run these commands from the repo root:

```powershell
python -m trading_system.replay_harness --scenario all --include-pipeline
python -m unittest discover -s trading_system\tests -v
python -m py_compile trading_system\signal_model.py trading_system\trend_strategy.py trading_system\replay_harness.py trading_system\agents\quant_agent.py trading_system\agents\execution_agent.py trading_system\agents\paper_trade_agent.py
```

Expected result:

- Paper replay passes all `BUY`, `ACCUMULATE`, `STOP_LOSS`, `TAKE_PROFIT`, and `HOLD` scenarios.
- Pipeline replay passes without broker calls or `trade_success` notifications.
- Unit tests pass.
- Compile check exits with no output.

## Start Agents

Start agents only after the pre-start loop is green:

```powershell
python -m trading_system.start_all_agents
```

## If Replay Fails

Stop the loop and fix the failing scenario first. Do not start agents after a failed replay.

Typical routing:

- `gate_failed`: inspect backtest metrics and thresholds.
- `cooldown`: verify duplicate signal timing.
- `trade_success` in replay output: treat as a safety regression.
- Missing `signalCategory`: normalize the source payload before routing.

## Changing Signal Behavior

For every new signal category or strategy rule:

1. Add or update a deterministic replay scenario.
2. Add the smallest focused unit test for the rule.
3. Run the pre-start loop.
4. Start agents only after the replay and tests are green.
