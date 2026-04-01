import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import os
import requests
import re

# Disable yfinance cache entirely to bypass peewee/sqlite issues in sandbox
yf.set_tz_cache_location("custom_cache_dir")

def get_alpha_vantage_key():
    key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if key: return key
    try:
        tools_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'TOOLS.md')
        if os.path.exists(tools_path):
            with open(tools_path, 'r', encoding='utf-8') as f:
                match = re.search(r'\*\*Alpha Vantage API Key:\*\*\s*`([^`]+)`', f.read())
                if match: return match.group(1)
    except: pass
    return None

# --- Data Fetchers ---
class DataFetcher:
    def fetch(self, symbol, start_date, end_date):
        raise NotImplementedError

class YahooFetcher(DataFetcher):
    def fetch(self, symbol, start_date, end_date):
        print(f"Fetching {symbol} from Yahoo Finance...")
        try:
            df = yf.download(symbol, start=start_date, end=end_date, progress=False)
            if df.empty:
                raise ValueError("Yahoo Finance returned empty dataframe")
            # Handle multi-level columns in recent yfinance versions
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            return df
        except Exception as e:
            print(f"Yahoo Fetcher failed: {e}. Falling back to Alpha Vantage...")
            return AlphaVantageFetcher().fetch(symbol, start_date, end_date)

class AlphaVantageFetcher(DataFetcher):
    def fetch(self, symbol, start_date, end_date):
        print(f"Fetching {symbol} from Alpha Vantage...")
        api_key = get_alpha_vantage_key()
        if not api_key:
            print("Alpha Vantage API key not found.")
            return pd.DataFrame()
            
        url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={symbol}&outputsize=full&apikey={api_key}"
        try:
            response = requests.get(url).json()
            if "Time Series (Daily)" not in response:
                print(f"Alpha Vantage error: {response.get('Note', response)}")
                return pd.DataFrame()
                
            data = response["Time Series (Daily)"]
            df = pd.DataFrame.from_dict(data, orient='index')
            df.index = pd.to_datetime(df.index)
            df = df.rename(columns={
                '1. open': 'Open',
                '2. high': 'High',
                '3. low': 'Low',
                '4. close': 'Close',
                '5. volume': 'Volume'
            }).astype(float)
            
            # Filter by date range
            mask = (df.index >= start_date) & (df.index <= end_date)
            df = df.loc[mask].sort_index()
            return df
        except Exception as e:
            print(f"Alpha Vantage Fetcher failed: {e}")
            return pd.DataFrame()

class QuandlFetcher(DataFetcher):
    def fetch(self, symbol, start_date, end_date):
        # Stub for Quandl/Nasdaq Data Link Integration
        print(f"Fetching {symbol} from Quandl (Stub)...")
        return pd.DataFrame()

# --- Algorithm Logic ---
def calculate_obv(df):
    obv = [0]
    for i in range(1, len(df)):
        if df['Close'].iloc[i] > df['Close'].iloc[i-1]:
            obv.append(obv[-1] + df['Volume'].iloc[i])
        elif df['Close'].iloc[i] < df['Close'].iloc[i-1]:
            obv.append(obv[-1] - df['Volume'].iloc[i])
        else:
            obv.append(obv[-1])
    return obv

def calculate_rsi(data, periods=14):
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=periods).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=periods).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_macd(df, fast=12, slow=26, signal=9):
    exp1 = df['Close'].ewm(span=fast, adjust=False).mean()
    exp2 = df['Close'].ewm(span=slow, adjust=False).mean()
    macd = exp1 - exp2
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line

def calculate_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(period).mean()

def generate_signals(df, rsi_buy=30, rsi_sell=70, rsi_period=14, obv_fast=5, obv_slow=10, use_obv=True):
    """
    Advanced Strategy:
    1. Trend Filter: Price must be above SMA 200 for long-term safety (optional, but good for high win rate)
    2. Momentum: MACD must be curling up (MACD > Signal Line)
    3. Volume: OBV must be accumulating
    4. Entry: RSI Oversold (< rsi_buy)
    5. Exit: RSI Overbought (> rsi_sell) OR Trailing Stop Hit (ATR based)
    """
    df = df.copy()
    
    # Calculate indicators
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    df['SMA_200'] = df['Close'].rolling(window=200).mean()
    df['RSI'] = calculate_rsi(df['Close'], rsi_period)
    df['OBV'] = calculate_obv(df)
    df['MACD'], df['MACD_Signal'] = calculate_macd(df)
    df['ATR'] = calculate_atr(df)
    
    df[f'OBV_SMA_{obv_fast}'] = df['OBV'].rolling(window=obv_fast).mean()
    df[f'OBV_SMA_{obv_slow}'] = df['OBV'].rolling(window=obv_slow).mean()
    
    # Trend Conditions
    df['OBV_Accumulating'] = df[f'OBV_SMA_{obv_fast}'] > df[f'OBV_SMA_{obv_slow}']
    df['MACD_Bullish'] = df['MACD'] > df['MACD_Signal']
    
    signals = []
    current_pos = 0 # 0: flat, 1: long
    trailing_stop = 0
    
    for i in range(len(df)):
        if pd.isna(df['RSI'].iloc[i]) or pd.isna(df['ATR'].iloc[i]) or pd.isna(df['SMA_200'].iloc[i]):
            signals.append(0)
            continue
            
        rsi = df['RSI'].iloc[i]
        obv_acc = df['OBV_Accumulating'].iloc[i]
        macd_bull = df['MACD_Bullish'].iloc[i]
        close_price = df['Close'].iloc[i]
        atr = df['ATR'].iloc[i]
        
        # --- Advanced Entry Logic ---
        # Relaxed conditions to allow for more trades while still filtering bad ones.
        # 1. RSI is relatively cheap (oversold or cooling down)
        # 2. Volume is accumulating (OBV crossover)
        # 3. Momentum is shifting upwards (MACD crossover)
        # Removed SMA 200 filter as it's too restrictive for volatile tech stocks like TSLA/TQQQ
        buy_condition = (rsi < rsi_buy) and obv_acc and macd_bull
        
        # --- Advanced Exit Logic ---
        # 1. RSI Overbought (Take Profit)
        # 2. Hard Trailing Stop hit (Stop Loss)
        sell_condition = False
        if current_pos == 1:
            # Update trailing stop (e.g., 3.0 * ATR below highest price since entry)
            new_stop = close_price - (3.0 * atr)
            if new_stop > trailing_stop:
                trailing_stop = new_stop
                
            if close_price < trailing_stop:
                sell_condition = True # Stopped out
            elif rsi > rsi_sell:
                sell_condition = True # Profit taken
                
        # Execute
        if buy_condition and current_pos == 0:
            signals.append(1)
            current_pos = 1
            trailing_stop = close_price - (2.5 * atr) # Initialize stop
        elif sell_condition and current_pos == 1:
            signals.append(-1)
            current_pos = 0
            trailing_stop = 0
        else:
            signals.append(0)
            
    df['Signal'] = signals
    return df

# --- Backtest Engine ---
def backtest(df, initial_capital=10000):
    capital = initial_capital
    position = 0
    trades = []
    
    df['Portfolio_Value'] = capital
    
    for i in range(len(df)):
        price = df['Close'].iloc[i]
        signal = df['Signal'].iloc[i]
        
        if signal == 1 and position == 0: # Buy
            position = capital / price
            capital = 0
            trades.append({'type': 'Buy', 'price': price, 'date': df.index[i]})
        elif signal == -1 and position > 0: # Sell
            capital = position * price
            position = 0
            trades.append({'type': 'Sell', 'price': price, 'date': df.index[i]})
            
        current_value = capital + (position * price)
        df.iloc[i, df.columns.get_loc('Portfolio_Value')] = current_value
        
    # Close any open positions at the end
    if position > 0:
        capital = position * df['Close'].iloc[-1]
        trades.append({'type': 'Sell', 'price': df['Close'].iloc[-1], 'date': df.index[-1]})
        df.iloc[-1, df.columns.get_loc('Portfolio_Value')] = capital

    return df, trades

def calculate_metrics(df, trades, initial_capital):
    final_value = df['Portfolio_Value'].iloc[-1]
    total_return = (final_value - initial_capital) / initial_capital
    
    days = (df.index[-1] - df.index[0]).days
    years = days / 365.25
    cagr = (final_value / initial_capital) ** (1 / years) - 1 if years > 0 else 0
    
    df['Peak'] = df['Portfolio_Value'].cummax()
    df['Drawdown'] = (df['Portfolio_Value'] - df['Peak']) / df['Peak']
    max_drawdown = df['Drawdown'].min()
    
    # Daily returns for Sharpe
    df['Daily_Return'] = df['Portfolio_Value'].pct_change()
    sharpe_ratio = (df['Daily_Return'].mean() / df['Daily_Return'].std()) * np.sqrt(252) if df['Daily_Return'].std() != 0 else 0
    
    # Trade metrics
    winning_trades = 0
    losing_trades = 0
    gross_profit = 0
    gross_loss = 0
    
    for i in range(1, len(trades), 2):
        if i >= len(trades): break
        buy_price = trades[i-1]['price']
        sell_price = trades[i]['price']
        profit = sell_price - buy_price
        
        if profit > 0:
            winning_trades += 1
            gross_profit += profit
        else:
            losing_trades += 1
            gross_loss += abs(profit)
            
    total_closed_trades = winning_trades + losing_trades
    win_rate = winning_trades / total_closed_trades if total_closed_trades > 0 else 0
    pnl_ratio = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    return {
        "Total Return": f"{total_return*100:.2f}%",
        "CAGR": f"{cagr*100:.2f}%",
        "Max Drawdown": f"{max_drawdown*100:.2f}%",
        "Sharpe Ratio": f"{sharpe_ratio:.2f}",
        "Win Rate": f"{win_rate*100:.2f}%",
        "P/L Ratio": f"{pnl_ratio:.2f}",
        "Total Trades": total_closed_trades
    }

def run_backtest_suite(symbol="TSLA", years=1, optimize=False):
    print(f"\n--- Running Backtest for {symbol} ({years}Y) ---")
    end_date = datetime.now()
    start_date = end_date.replace(year=end_date.year - years)
    
    fetcher = YahooFetcher() # Defaulting to Yahoo Finance
    raw_df = fetcher.fetch(symbol, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
    
    report_text = ""
    
    if raw_df.empty:
        print("Failed to fetch data.")
        return "Failed to fetch data."
        
    if optimize:
        print("\n[ Running Parameter Grid Search... ]")
        best_return = -float('inf')
        best_params = None
        best_metrics = None
        
        rsi_buy_options = [25, 30, 35]
        rsi_sell_options = [65, 70, 75]
        obv_fast_options = [3, 5, 7]
        obv_slow_options = [10, 15, 20]
        
        total_combinations = len(rsi_buy_options) * len(rsi_sell_options) * len(obv_fast_options) * len(obv_slow_options)
        print(f"Testing {total_combinations} combinations...")
        
        for rb in rsi_buy_options:
            for rs in rsi_sell_options:
                for of in obv_fast_options:
                    for os in obv_slow_options:
                        # Generate signals with current parameters
                        df = generate_signals(raw_df, rsi_buy=rb, rsi_sell=rs, obv_fast=of, obv_slow=os)
                        df, trades = backtest(df)
                        metrics = calculate_metrics(df, trades, 10000)
                        
                        # Extract raw return for comparison
                        ret_str = metrics["Total Return"].replace('%', '')
                        ret_val = float(ret_str)
                        
                        if ret_val > best_return:
                            best_return = ret_val
                            best_params = {'rsi_buy': rb, 'rsi_sell': rs, 'obv_fast': of, 'obv_slow': os}
                            best_metrics = metrics
                            
        report_text += f"🚀 **{symbol} {years}年回测参数寻优报告**\n\n"
        report_text += f"**🏆 最佳参数组合:**\n"
        report_text += f"- RSI 买入线: `{best_params['rsi_buy']}`\n"
        report_text += f"- RSI 卖出线: `{best_params['rsi_sell']}`\n"
        report_text += f"- OBV 快慢线: `{best_params['obv_fast']}日` / `{best_params['obv_slow']}日`\n\n"
        report_text += f"**📊 性能指标:**\n"
        for k, v in best_metrics.items():
            report_text += f"- {k}: {v}\n"
            
        # Re-run best for plotting
        df = generate_signals(raw_df, **best_params)
        df, trades = backtest(df)
    else:
        # Generate signals using default basic parameters for baseline comparison
        # (Using the simple version to show the contrast)
        df = raw_df.copy()
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['RSI'] = calculate_rsi(df['Close'], 14)
        df['OBV'] = calculate_obv(df)
        df['OBV_SMA_5'] = df['OBV'].rolling(window=5).mean()
        df['OBV_SMA_10'] = df['OBV'].rolling(window=10).mean()
        df['OBV_Accumulating'] = df['OBV_SMA_5'] > df['OBV_SMA_10']
        
        signals = []
        current_pos = 0
        for i in range(len(df)):
            if pd.isna(df['RSI'].iloc[i]):
                signals.append(0)
                continue
            rsi = df['RSI'].iloc[i]
            obv_acc = df['OBV_Accumulating'].iloc[i]
            buy_condition = (rsi < 30) and obv_acc
            sell_condition = (rsi > 70) or (df['Close'].iloc[i] < df['SMA_50'].iloc[i] and not obv_acc)
            
            if buy_condition and current_pos == 0:
                signals.append(1)
                current_pos = 1
            elif sell_condition and current_pos == 1:
                signals.append(-1)
                current_pos = 0
            else:
                signals.append(0)
        df['Signal'] = signals
        
        df, trades = backtest(df)
        metrics = calculate_metrics(df, trades, 10000)
        
        report_text += f"📊 **{symbol} {years}年回测报告 (默认参数)**\n\n"
        for k, v in metrics.items():
            report_text += f"- {k}: {v}\n"
        
    # Visualization
    plt.figure(figsize=(14, 7))
    plt.plot(df.index, df['Portfolio_Value'], label='Portfolio Value', color='blue')
    title_suffix = "Optimized" if optimize else "Default"
    plt.title(f"Backtest Results - {symbol} ({years} Years) [{title_suffix}]")
    plt.xlabel('Date')
    plt.ylabel('Portfolio Value ($)')
    plt.legend()
    plt.grid(True)
    
    plot_path = f"backtest_{symbol}_{years}Y_{title_suffix.lower()}.png"
    plt.savefig(plot_path)
    print(f"Saved visualization to {plot_path}")
    plt.close()
    
    return report_text

def run_daily_optimization():
    tickers = ['TSLA', 'TQQQ', 'SOXL']
    full_report = "🤖 **ClawdBot 每日策略自适应升级**\n\n"
    
    for ticker in tickers:
        print(f"Running optimization for {ticker}...")
        report = run_backtest_suite(ticker, years=1, optimize=True)
        full_report += report + "\n"
        
    # Send via Telegram
    try:
        from telegram_notifier import send_telegram_message
        send_telegram_message(full_report)
        print("Successfully sent daily backtest report to Telegram.")
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")
        
    return full_report

if __name__ == "__main__":
    import warnings
    warnings.simplefilter(action='ignore', category=FutureWarning)
    
    # Test Default
    run_backtest_suite("TSLA", 3, optimize=False)
    # Test Optimized
    run_backtest_suite("TSLA", 3, optimize=True)
