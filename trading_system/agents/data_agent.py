import sys
import os
import time
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.message_bus import bus
from logger import get_logger
from config import (
    get_portfolio_tickers, is_market_open, is_trading_day,
    DATA_POLL_INTERVAL, sleep_until_market
)
from indicators import calculate_rsi_scalar, calculate_atr_scalar, calculate_obv_from_lists
import yfinance as yf
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
        """Get current ticker list (dynamic from eToro portfolio)."""
        return get_portfolio_tickers()

    def run_technical_scan(self):
        tickers = self._get_tickers()
        log.info(f"Running Technical Scan on {tickers}...")
        appended_count = 0

        for symbol in tickers:
            try:
                hist = yf.download(symbol, period="3mo", interval="1d", progress=False)
                if hist.empty:
                    continue

                if isinstance(hist.columns, pd.MultiIndex):
                    hist.columns = hist.columns.droplevel(1)

                quotes = []
                for index, row in hist.iterrows():
                    quotes.append({
                        'close': float(row['Close']),
                        'high': float(row['High']),
                        'low': float(row['Low']),
                        'volume': float(row['Volume'])
                    })

                prices = [q['close'] for q in quotes]
                volumes = [q['volume'] for q in quotes]
                currentPrice = prices[-1]
                sma50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else None

                rsi = calculate_rsi_scalar(prices, 14)
                atr = calculate_atr_scalar(quotes, 14)

                obv_array = calculate_obv_from_lists(prices, volumes)

                recentObv = sum(obv_array[-5:]) / 5 if len(obv_array) >= 10 else 0
                prevObv = sum(obv_array[-10:-5]) / 5 if len(obv_array) >= 10 else 0
                obvStatus = "Accumulating" if recentObv > prevObv else "Distributing"

                isBullish = currentPrice > sma50 if sma50 else None

                data_payload = {
                    'source': 'obv_monitor',
                    'symbol': symbol,
                    'price': currentPrice,
                    'sma50': sma50,
                    'rsi': rsi,
                    'atr': atr,
                    'recentObv': recentObv,
                    'prevObv': prevObv,
                    'obvStatus': obvStatus,
                    'isBullish': isBullish
                }

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
            self.run_sector_scan()
            time.sleep(DATA_POLL_INTERVAL)


if __name__ == "__main__":
    agent = DataAgent()
    agent.start()
