import sys
import os
import time
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.message_bus import bus
from volume_monitor import check_intraday_volume
from sector_scanner import scan_sectors
import yfinance as yf
import pandas as pd

class DataAgent:
    """
    The sensory system.
    Runs high-frequency data fetching (e.g., volume spikes).
    Instead of executing logic or sending alerts directly, 
    it publishes raw findings to the message bus for the Quant/Notification agents.
    """
    def __init__(self):
        self.running = False
        self.last_sector_scan = None
        self.tickers = ['TSLA', 'SOXL', 'TQQQ', 'UNH']
        import warnings
        warnings.simplefilter(action='ignore', category=FutureWarning)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] DataAgent Initialized")

    def _calculate_rsi(self, prices, period=14):
        if len(prices) <= period: return 50
        gains, losses = 0.0, 0.0
        for i in range(1, period + 1):
            diff = prices[-i] - prices[-i-1]
            if diff > 0: gains += diff
            else: losses -= diff
        rs = (gains / period) / (losses / period) if losses != 0 else float('inf')
        return 100.0 if losses == 0 else 100.0 - (100.0 / (1 + rs))

    def _calculate_atr(self, quotes, period=14):
        if len(quotes) <= period + 1: return 0
        tr_array = []
        for i in range(1, len(quotes)):
            h, l = quotes[i]['high'], quotes[i]['low']
            pc = quotes[i-1]['close']
            tr = max(h - l, abs(h - pc), abs(l - pc))
            tr_array.append(tr)
        return sum(tr_array[-period:]) / period

    def run_technical_scan(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] DataAgent: Running Technical Oscillator Scan natively...")
        appended_count = 0
        
        for symbol in self.tickers:
            try:
                hist = yf.download(symbol, period="3mo", interval="1d", progress=False)
                if hist.empty: continue
                
                # Handle YF multiindex weirdness cleanly
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
                currentPrice = prices[-1]
                sma50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else None
                
                rsi = self._calculate_rsi(prices, 14)
                atr = self._calculate_atr(quotes, 14)
                
                obv_array = [0]
                for i in range(1, len(quotes)):
                    currentObv = obv_array[-1]
                    if quotes[i]['close'] > quotes[i-1]['close']: currentObv += quotes[i]['volume']
                    elif quotes[i]['close'] < quotes[i-1]['close']: currentObv -= quotes[i]['volume']
                    obv_array.append(currentObv)
                    
                recentObv = sum(obv_array[-5:]) / 5 if len(obv_array) >= 10 else 0
                prevObv = sum(obv_array[-10:-5]) / 5 if len(obv_array) >= 10 else 0
                obvStatus = "Accumulating" if recentObv > prevObv else "Distributing"
                
                isBullish = currentPrice > sma50 if sma50 else None
                
                data_payload = {
                    'source': 'obv_monitor', # Maintained for QuantAgent backward compatibility
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
                print(f"Error natively analyzing {symbol}: {e}")

        if appended_count > 0:
            print(f"Published {appended_count} technical matrices to the ZMQ market_data bus.")

    def run_volume_scan(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] DataAgent: Scanning Volume...")
        # For this refactor, we wrap the existing function.
        # In a fully decoupled state, volume_monitor would return data instead of printing/alerting.
        try:
            check_intraday_volume()
        except Exception as e:
            print(f"DataAgent Error (Volume): {e}")
            
    def run_sector_scan(self):
        now = datetime.now()
        # Run sector scan once per day around 4:30 PM EST
        # For the sake of the agent polling loop, we just do a daily check
        today_str = now.strftime('%Y-%m-%d')
        if self.last_sector_scan != today_str:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] DataAgent: Running Daily Sector Rotation Scan...")
            try:
                scan_sectors()
                self.last_sector_scan = today_str
            except Exception as e:
                print(f"DataAgent Error (Sector): {e}")

    def start(self):
        self.running = True
        print("DataAgent started. Polling data sources...")
        
        while self.running:
            self.run_technical_scan()
            self.run_volume_scan()
            self.run_sector_scan()
            # Polling unified matrices natively every 15 minutes during market hours
            time.sleep(900)

if __name__ == "__main__":
    agent = DataAgent()
    agent.start()
