# ClawdBot

Multi-agent trading system with:
- Market data + technical scans
- Quant signal generation
- Demo execution gateway
- Telegram notifications

## Setup
1. Create `TOOLS.md` from [TOOLS.example.md](file:///c:/Users/User/clawd-local/TOOLS.example.md).
2. Install Python dependencies:
   - `pip install -r trading_system/requirements.txt`
   - `pip install pyzmq`
3. Run the system:
   - `python trading_system/start_all_agents.py`

## Notes
- Demo trading is automated; real trading is emitted as manual recommendations.
- Secrets are intentionally not committed; keep `TOOLS.md` local.
