import sys
import os
import time
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.message_bus import bus
from logger import get_logger
from config import (
    get_real_position_tickers, get_trend_watchlist, is_market_open, is_trading_day,
    get_data_poll_interval, sleep_until_market
)
from broker_providers import fetch_history
from trend_strategy import analyze_trend_frame
import pandas as pd

import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

log = get_logger("DataAgent")


class DataAgent:
    """
    The sensory system.
    Fetches technical data and publishes raw findings to the message bus.
    Now market-hours-aware and uses dynamic tickers from eToro portfolio.
    """
    def __init__(self):
        self.running = False
        self.last_sector_scan = None
        log.info("DataAgent Initialized")

    def _get_tickers(self):
        """Get current trend scanner watchlist."""
        return get_trend_watchlist()

    def _get_position_symbols(self):
        """Get real held symbols without fallback assumptions."""
        return set(get_real_position_tickers())

    def _data_context(self, hist, period, interval, source):
        source = str(source or "unknown")
        latest_bar_ts = str(hist.index[-1]) if hist is not None and len(hist.index) else ""

        confidence = "high" if source == "moomoo" else "medium"
        nonzero_volume_count = 0
        if hist is not None and "Volume" in hist.columns:
            volumes = pd.to_numeric(hist["Volume"], errors="coerce").fillna(0)
            nonzero_volume_count = int((volumes > 0).sum())
            required_volume_bars = min(10, max(2, len(volumes) // 3))
            if nonzero_volume_count < required_volume_bars:
                confidence = "low"
        if hist is None or len(hist) < 55:
            confidence = "low"

        return {
            "dataSource": source,
            "dataPeriod": str(period),
            "dataInterval": str(interval),
            "dataConfidence": confidence,
            "latestBarTs": latest_bar_ts,
            "nonzeroVolumeBars": nonzero_volume_count,
        }

    def run_technical_scan(self):
        tickers = self._get_tickers()
        position_symbols = self._get_position_symbols()
        log.info(f"Running Technical Scan on {tickers}...")
        appended_count = 0

        for symbol in tickers:
            try:
                hist, period, interval, source = fetch_history(symbol, provider="auto", interval="5m")
                if hist.empty:
                    continue

                if isinstance(hist.columns, pd.MultiIndex):
                    hist.columns = hist.columns.droplevel(1)

                data_payload = analyze_trend_frame(
                    hist,
                    symbol=symbol,
                    timeframe=interval,
                    in_position=str(symbol).upper() in position_symbols,
                )
                data_payload.update(self._data_context(hist, period, interval, source))

                bus.publish('market_data', data_payload)
                appended_count += 1
            except Exception as e:
                log.error(f"Error analyzing {symbol}: {e}")

        if appended_count > 0:
            log.info(f"Published {appended_count} technical matrices to ZMQ bus.")

    def run_volume_scan(self):
        log.info("Scanning Volume...")
        try:
            from volume_monitor import check_intraday_volume
            check_intraday_volume()
        except Exception as e:
            log.error(f"Volume scan error: {e}")

    def run_flash_crash_scan(self):
        log.info("Scanning for Market Flash Crashes...")
        try:
            from flash_crash_monitor import check_flash_crash
            check_flash_crash()
        except Exception as e:
            log.error(f"Flash crash scan error: {e}")

    def run_sector_scan(self):
        now = datetime.now()
        today_str = now.strftime('%Y-%m-%d')
        if self.last_sector_scan != today_str:
            log.info("Running Daily Sector Rotation Scan...")
            try:
                from sector_scanner import scan_sectors
                scan_sectors()
                self.last_sector_scan = today_str
            except Exception as e:
                log.error(f"Sector scan error: {e}")

    def run_daily_backtest(self):
        now = datetime.now()
        today_str = now.strftime('%Y-%m-%d')
        # Use a new state variable or just piggyback on last_sector_scan safely
        if not hasattr(self, 'last_backtest_scan'):
            self.last_backtest_scan = ""
            
        if self.last_backtest_scan != today_str:
            log.info("Running Daily Backtest Optimization...")
            try:
                from backtest_framework import run_daily_optimization
                run_daily_optimization()
                self.last_backtest_scan = today_str
            except Exception as e:
                log.error(f"Daily backtest error: {e}")
                self.last_backtest_scan = today_str

    def start(self):
        self.running = True
        log.info("DataAgent started. Polling data sources...")

        while self.running:
            if not is_trading_day():
                log.info("Weekend. Sleeping until Monday market open.")
                sleep_until_market(log)
                continue

            if not is_market_open():
                log.info("Market closed. Sleeping until next open.")
                sleep_until_market(log)
                continue

            self.run_technical_scan()
            self.run_volume_scan()
            self.run_flash_crash_scan()
            self.run_sector_scan()
            self.run_daily_backtest()
            interval = get_data_poll_interval()
            if interval <= 60:
                log.info("TURBO MODE ACTIVE (1 min polling)")
            time.sleep(interval)


if __name__ == "__main__":
    agent = DataAgent()
    agent.start()
