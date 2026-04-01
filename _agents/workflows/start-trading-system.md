---
description: Boot sequence to initialize the Multi-Agent Trading System natively
---

# Multi-Agent Boot Sequence

This workflow initializes the complete Python trading cluster (ZMQ Broker, Execution Agent, Quant Agent, Tracker Agent, etc.).

1. **Stop Zombie Processes:**
   First, forcefully terminate any residual background agents to ensure a clean ZeroMQ bus alignment.
   // turbo
   `Stop-Process -Name python -Force`

2. **Initialize Agents:**
   Start the primary Python orchestrator natively in the background. Leave this process running continuously.
   // turbo
   `python trading_system/start_all_agents.py`

*System initialized successfully. All agents are now securely streaming data and executing payloads over ZeroMQ.*
