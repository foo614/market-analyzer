"""
Structured logging for the ClawdBot Trading System.
Replaces raw print() calls with consistent, timestamped, leveled output.
Logs to both console and daily rotating file.
"""

import logging
import os
import sys
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')


def get_logger(agent_name):
    """
    Create a logger for an agent with console + file output.

    Usage:
        from logger import get_logger
        log = get_logger("DataAgent")
        log.info("Starting scan...")
        log.warning("API returned empty data")
        log.error("Failed to connect", exc_info=True)
    """
    logger = logging.getLogger(agent_name)

    # Avoid duplicate handlers on re-import
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # ─── Format ──────────────────────────────────────────────────────
    fmt = logging.Formatter(
        fmt=f"[%(asctime)s] [{agent_name}] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    # ─── Console Handler ─────────────────────────────────────────────
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # ─── File Handler (daily rotation) ───────────────────────────────
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        today = datetime.now().strftime('%Y-%m-%d')
        file_path = os.path.join(LOG_DIR, f"{today}.log")
        file_handler = logging.FileHandler(file_path, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except Exception:
        # If we can't write logs, continue with console only
        pass

    return logger
