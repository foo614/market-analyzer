# ClawdBot

Multi-agent trading system with:
- Market data + technical scans
- Quant signal generation
- Demo execution gateway
- Telegram notifications

## Setup
1. Create `TOOLS.md` from [TOOLS.example.md](./TOOLS.example.md).
2. Install Python dependencies:
   - `pip install -r trading_system/requirements.txt`
   - `pip install pyzmq`
3. Run the replay-first safety check:
   - `python -m trading_system.replay_harness --scenario all --include-pipeline`
4. Run the system only after replay is green:
   - `python -m trading_system.start_all_agents`

## Safe Operation
- Before starting agents, run:
  - `python -m trading_system.replay_harness --scenario all --include-pipeline`
  - `python -m unittest discover -s trading_system\tests -v`
- Full startup checklist: [docs/trading_operator_runbook.md](./docs/trading_operator_runbook.md)

## Notes
- Demo mode defaults to `dry-run`; demo execution requires an explicit later mode change.
- Real portfolio trading is emitted as manual recommendations only.
- eToro and moomoo signal routes pass through the paper gate; no real broker order is placed by this loop.
- Secrets are intentionally not committed; keep `TOOLS.md` local.
