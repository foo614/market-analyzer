---
description: Boot sequence to initialize the Multi-Agent Trading System natively
---

# Multi-Agent Boot Sequence

This workflow initializes the Python trading cluster after the local replay
safety checks pass. Real portfolio signals remain manual recommendations, and
demo mode defaults to `dry-run`.

1. **Run Replay Safety Checks:**
   // turbo
   `python -m trading_system.replay_harness --scenario all --include-pipeline`

2. **Run Unit Checks:**
   // turbo
   `python -m unittest discover -s trading_system\tests -v`

3. **Inspect Existing Python Processes Before Restarting:**
   // turbo
   `Get-Process python`

4. **Initialize Agents:**
   Start the primary Python orchestrator natively. Leave this process running continuously.
   // turbo
   `python -m trading_system.start_all_agents`

Expected runtime flow: `DataAgent -> QuantAgent -> ExecutionAgent -> NotificationAgent`.
The execution agent routes signals through the paper gate and emits real
portfolio recommendations for manual action.
