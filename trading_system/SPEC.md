# ClawdBot Multi-Agent Trading System Specification

## 1. System Overview
The ClawdBot Trading System is a decoupled, event-driven Multi-Agent Architecture for automated and assisted stock trading. It uses a ZeroMQ message bus for inter-agent communication and local Ollama (gemma4:e4b) for AI-powered analysis.

## 2. Architecture: ZeroMQ Message Bus
At the core is a ZMQ XSUB/XPUB proxy (`bus_server.py`) that routes messages between agents over TCP.

### Active Queues (Topics):
- `market_data`: Raw data payloads from Data Agent and Sentiment Agent.
- `trade_signals`: Actionable `BUY/SELL` instructions from the Quant Agent.
- `notifications`: Formatted messages for human consumption (Telegram delivery).
- `system_state`: Heartbeat and health statuses of active agents.

### Centralized Infrastructure:
- **`config.py`**: Single source of truth for all credentials, API keys, market hours, thresholds, and dynamic ticker discovery from eToro portfolio.
- **`logger.py`**: Structured logging with `[HH:MM:SS] [AgentName] [LEVEL]` format, console + daily file output.
- **`indicators.py`**: Unified technical indicator library (RSI, ATR, OBV, MACD, SMA, VWAP). All agents import from here.

---

## 3. Agent Specifications

### 3.1 Data Agent (`agents/data_agent.py`)
**Role:** The Sensory System.
- Polls Yahoo Finance for technical data on dynamically-discovered tickers (from eToro portfolio).
- Calculates RSI, ATR, OBV, SMA via unified `indicators.py`.
- **Market-hours aware**: Only polls during Mon-Fri 9:30 AM - 4:00 PM ET.
- Runs volume monitoring and daily sector rotation scans.
- **Output:** Publishes structured JSON to `market_data` queue.

### 3.2 Quant Agent (`agents/quant_agent.py`)
**Role:** The Strategy Brain.
- Consumes `market_data` queue via ZMQ streaming.
- Applies optimized technical logic (RSI + OBV + MACD + ATR trailing stop).
- **Signal cooldown**: Suppresses duplicate signals per symbol for 60 minutes.
- **LLM-as-Judge (Soft Advisory)**: Before emitting signals, queries local Ollama gemma4:e4b for a second opinion. LLM agreement/disagreement is displayed in Telegram alerts but does NOT block execution.
- **Output:** Emits trade signals to `trade_signals` queue.

### 3.3 Execution Agent (`agents/execution_agent.py`)
**Role:** The Hands (Order Gateway).
- Listens to `trade_signals` queue.
- Executes trades on eToro Demo via REST API.
- Sends REAL portfolio recommendations (manual execution) via `notifications`.
- Includes LLM advisory opinion in notification messages.

### 3.4 Notification Agent (`agents/notification_agent.py`)
**Role:** The Mouthpiece.
- Listens to `notifications` queue.
- Delivers messages to Telegram with **message chunking** (4000-char splits) and **rate limiting** (20/min).

### 3.5 Sentiment Agent (`agents/sentiment_agent.py`)
**Role:** AI News Analyst.
- Scrapes headlines via yfinance for portfolio tickers.
- Sends headlines to local Ollama gemma4:e4b for sentiment scoring.
- **Retry logic**: 1 retry with 5s backoff on Ollama failures.
- **Market-hours aware**: Only scans during pre-market (7 AM) and market hours.

### 3.6 Tracker Agent (`agents/etoro_tracker.py`)
**Role:** Portfolio Historian.
- Syncs trade history from both Demo and Real eToro accounts.
- Stores in local SQLite databases.
- Generates performance reports (Win Rate, Net PnL, Drawdown).

---

## 4. Sub-Modules & Utilities

### Market Analyzer (`market_analyzer.py`)
- Analyzes VIX, S&P 500, NASDAQ, and Futures premiums.
- Passes raw data to local Ollama (`gemma4:e4b`) to generate a concise, Chinese-language trader brief.

### Risk Manager (`risk_manager.py`)
- Fetches live portfolio equity from eToro API (not hardcoded).
- Circuit breaker: Freezes trading if daily loss exceeds 1%.
- Daily trade count limit: Max 10 round-trips per day.
- Per-symbol allocation warnings at 40%.

### Auto Trader (`auto_trader.py`)
- eToro Demo trade execution gateway.
- Uses centralized config for API credentials.

---

## 5. Deployment & Process Management

- **Orchestrator:** `start_all_agents.py`
  - Spawns ZMQ broker + 6 agents as background processes.
  - **Watchdog loop**: Checks child health every 30s, auto-restarts crashed agents with exponential backoff (max 3 retries).
  - **Pre-flight checks**: Validates Ollama connectivity before boot.
  - **Graceful shutdown**: SIGTERM → 5s wait → SIGKILL.

## 6. Dynamic Ticker Discovery
The system no longer uses a hardcoded ticker list. On startup:
1. Fetches Real portfolio from eToro `/trading/info/portfolio`.
2. Extracts unique `instrumentID` values from open positions.
3. Resolves each to a ticker symbol via `/market-data/search`.
4. Caches the mapping (refreshed hourly alongside Tracker Agent).
5. Falls back to `['TSLA', 'SOXL', 'TQQQ']` if API is unreachable.