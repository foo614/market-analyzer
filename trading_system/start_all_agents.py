"""
ClawdBot Multi-Agent System Orchestrator.
Spawns all agents as child processes and monitors them with a watchdog loop.
Auto-restarts crashed agents with exponential backoff (max 3 retries).
"""

import subprocess
import sys
import time
import os
import signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from logger import get_logger
from config import WATCHDOG_INTERVAL, check_ollama_health

log = get_logger("Orchestrator")

AGENTS = [
    {"name": "Notification Agent", "file": "notification_agent.py"},
    {"name": "Execution Agent",    "file": "execution_agent.py"},
    {"name": "Quant Agent",        "file": "quant_agent.py"},
    {"name": "Data Agent",         "file": "data_agent.py"},
    {"name": "Sentiment Agent",    "file": "sentiment_agent.py"},
    {"name": "Tracker Agent",      "file": "etoro_tracker.py"},
]

MAX_RESTARTS = 3
RESTART_BACKOFF_BASE = 5  # seconds


class AgentProcess:
    def __init__(self, name, file_path):
        self.name = name
        self.file_path = file_path
        self.process = None
        self.restart_count = 0
        self.last_restart = 0

    def start(self):
        log.info(f"Starting {self.name}...")
        self.process = subprocess.Popen(
            [sys.executable, self.file_path],
            stdout=sys.stdout,
            stderr=sys.stderr
        )
        self.last_restart = time.time()
        return self.process

    def is_alive(self):
        if self.process is None:
            return False
        return self.process.poll() is None

    def restart(self):
        if self.restart_count >= MAX_RESTARTS:
            log.error(f"{self.name} exceeded max restarts ({MAX_RESTARTS}). Giving up.")
            return False

        self.restart_count += 1
        backoff = RESTART_BACKOFF_BASE * (2 ** (self.restart_count - 1))
        log.warning(f"{self.name} CRASHED (exit code: {self.process.returncode}). "
                    f"Restarting in {backoff}s (attempt {self.restart_count}/{MAX_RESTARTS})...")
        time.sleep(backoff)
        self.start()
        return True

    def stop(self):
        if self.process and self.is_alive():
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                log.warning(f"{self.name} required SIGKILL.")

def _cleanup_stale_ports():
    """Kill any zombie processes still holding ZMQ ports 5555/5556."""
    import platform
    if platform.system() != 'Windows':
        return

    for port in [5555, 5556]:
        try:
            result = subprocess.run(
                ['netstat', '-ano'],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if f':{port}' in line and 'LISTENING' in line:
                    parts = line.split()
                    pid = parts[-1]
                    if pid.isdigit() and int(pid) != os.getpid():
                        log.warning(f"Killing zombie process PID {pid} holding port {port}")
                        subprocess.run(['taskkill', '/F', '/PID', pid],
                                       capture_output=True, timeout=5)
                        time.sleep(1)
        except Exception as e:
            log.debug(f"Port cleanup check failed for {port}: {e}")


def main():
    log.info("=" * 50)
    log.info("Starting ClawdBot Multi-Agent System")
    log.info("=" * 50)
    log.info("DEMO: Fully Automated Paper Trading")
    log.info("REAL: Manual Signals & Telegram Monitoring")
    log.info("=" * 50)

    # Pre-flight checks
    ollama_ok, ollama_msg = check_ollama_health()
    if ollama_ok:
        log.info(f"✅ {ollama_msg}")
    else:
        log.warning(f"⚠️ {ollama_msg} — Sentiment/LLM features will degrade gracefully.")

    agents = []

    try:
        # ─── Pre-boot: Kill zombie processes holding ZMQ ports ────────
        _cleanup_stale_ports()

        # Start ZMQ broker first
        log.info("Starting ZeroMQ Message Broker...")
        bus_path = os.path.join(os.path.dirname(__file__), 'bus_server.py')
        bus_agent = AgentProcess("ZMQ Broker", bus_path)
        bus_agent.start()
        agents.append(bus_agent)
        time.sleep(2)  # Give socket time to bind

        # Verify broker is actually alive (catch bind failures early)
        if not bus_agent.is_alive():
            log.critical(f"ZMQ Broker failed to start (exit code: {bus_agent.process.returncode}). "
                         "Port 5555/5556 may still be in use. Aborting.")
            return

        # Start all agents with staggered delays
        agents_dir = os.path.join(os.path.dirname(__file__), 'agents')
        for agent_def in AGENTS:
            agent_path = os.path.join(agents_dir, agent_def["file"])
            agent = AgentProcess(agent_def["name"], agent_path)
            agent.start()
            agents.append(agent)
            time.sleep(1)

        log.info("")
        log.info(f"All {len(agents)} processes started successfully.")
        log.info("Watchdog active. Press Ctrl+C to stop.")
        log.info("")

        # ─── Watchdog Loop ────────────────────────────────────────────
        while True:
            time.sleep(WATCHDOG_INTERVAL)

            for agent in agents:
                if not agent.is_alive():
                    if agent.name == "ZMQ Broker":
                        log.critical("ZMQ Broker died! Shutting down all agents.")
                        raise SystemExit(1)

                    success = agent.restart()
                    if not success:
                        log.error(f"PERMANENT FAILURE: {agent.name}")

    except (KeyboardInterrupt, SystemExit):
        log.info("")
        log.info("Shutting down all agents...")
        for agent in reversed(agents):
            agent.stop()
        log.info("System shutdown complete.")

    except Exception as e:
        log.error(f"Fatal orchestrator error: {e}", exc_info=True)
        for agent in reversed(agents):
            agent.stop()


if __name__ == "__main__":
    main()
