- Check gateway health: Run `clawdbot gateway health` during market hours (Mon-Fri, 21:30 - 04:00 SGT).
- If unresponsive/error: Attempt `clawdbot gateway restart`.
- Notify Telegram if restarted.

## Automated Trading System Routine (Multi-Agent Architecture)
- The entire trading system is now orchestrated via `start_all_agents.py` which runs continuously in the background.
- **Health Check:** Ensure that the multi-agent system (`start_all_agents.py`) is running. If it's not running, execute `python trading_system/start_all_agents.py` to launch it.
- **Monitoring:** The agents will handle their own specific routines (Volume, OBV, Execution, Notifications) autonomously.
- **WhatsApp Bot:** Ensure `node whatsapp_reminder/wa_bot.js` runs automatically on the last day of the month at 8:00 PM.
