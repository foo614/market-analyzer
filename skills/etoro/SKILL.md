# Etoro Skill

Connects to eToro API to fetch real-time portfolio balance, positions, and execute trades securely.

## Configuration
Requires `ETORO_API_KEY` and `ETORO_PUBLIC_KEY`.
Use `clawdbot gateway config.patch` to set these environment variables.

## Usage
- `etoro.portfolio`: Fetch live portfolio data.
- `etoro.status`: Check API connectivity.
