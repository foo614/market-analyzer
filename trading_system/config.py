"""
Centralized configuration for the ClawdBot Trading System.
Single source of truth for all constants, API keys, and market hours logic.
"""

import os
import re
import json
import time
import requests
import uuid
from datetime import datetime, timedelta
import pytz

# ─── Paths ────────────────────────────────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYSTEM_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_PATH = os.path.join(ROOT_DIR, 'TOOLS.md')
LOCK_FILE = os.path.join(SYSTEM_DIR, 'TRADE_FREEZE.lock')
LOG_DIR = os.path.join(SYSTEM_DIR, 'logs')

# ─── Timezone ─────────────────────────────────────────────────────────────────
ET = pytz.timezone('US/Eastern')

# ─── Polling Intervals (seconds) ─────────────────────────────────────────────
DATA_POLL_INTERVAL = 900       # 15 minutes
SENTIMENT_POLL_INTERVAL = 900  # 15 minutes
TRACKER_POLL_INTERVAL = 3600   # 60 minutes
WATCHDOG_INTERVAL = 30         # 30 seconds

# ─── Risk Thresholds ─────────────────────────────────────────────────────────
MAX_DAILY_LOSS_PCT = 0.01       # 1%
MAX_SYMBOL_ALLOCATION_PCT = 0.40  # 40% of portfolio in one ticker (warn only)
MAX_DAILY_TRADES = 10
DEFAULT_TRADE_AMOUNT = 500

# ─── Strategy Defaults ────────────────────────────────────────────────────────
SIGNAL_COOLDOWN_MINUTES = 60  # Suppress duplicate signals for same symbol

# ─── Fallback Tickers (used if eToro API is unreachable) ─────────────────────
FALLBACK_TICKERS = ['TSLA', 'SOXL', 'TQQQ']

# ─── Ollama ──────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "gemma4:e4b"
OLLAMA_API_URL = f"{OLLAMA_BASE_URL}/v1"

# ─── eToro ───────────────────────────────────────────────────────────────────
ETORO_BASE_URL = "https://public-api.etoro.com/api/v1"
ETORO_REQUEST_TIMEOUT = 15
ETORO_MAX_RETRIES = 3

# ─── Credential Parsing ─────────────────────────────────────────────────────
_credentials_cache = {}

def _parse_tools_md():
    """Parse TOOLS.md once and cache all credentials."""
    global _credentials_cache
    if _credentials_cache:
        return _credentials_cache

    creds = {}
    if not os.path.exists(TOOLS_PATH):
        return creds

    try:
        with open(TOOLS_PATH, 'r', encoding='utf-8') as f:
            content = f.read()

        patterns = {
            'telegram_bot_token': r'\*\*Bot Token:\*\*\s*`([^`]+)`',
            'telegram_chat_id': r'\*\*Chat ID:\*\*\s*`([^`]+)`',
            'alpha_vantage_key': r'\*\*Alpha Vantage API Key:\*\*\s*`([^`]+)`',
            'openai_key': r'\*\*OpenAI API Key:\*\*\s*`([^`]+)`',
            'nvidia_key': r'\*\*NVIDIA API Key:\*\*\s*`([^`]+)`',
            'etoro_pub_key': r'\*\*Public Key:\*\*\s*`([^`]+)`',
            'etoro_demo_key': r'\*\*Demo User Key:\*\*\s*`([^`]+)`',
            'etoro_real_key': r'\*\*Real User Key:\*\*\s*`([^`]+)`',
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                creds[key] = match.group(1).strip()

        _credentials_cache = creds
    except Exception:
        pass

    return creds


def get_credential(key, env_var=None):
    """Get a credential by key, checking env vars first, then TOOLS.md."""
    if env_var:
        val = os.environ.get(env_var)
        if val:
            return val
    creds = _parse_tools_md()
    return creds.get(key)


# ─── eToro Headers ───────────────────────────────────────────────────────────

def get_etoro_headers(is_real=False):
    """Build eToro API headers for Demo or Real account."""
    pub_key = get_credential('etoro_pub_key')
    user_key = get_credential('etoro_real_key' if is_real else 'etoro_demo_key')

    return {
        "x-request-id": str(uuid.uuid4()),
        "x-api-key": pub_key or "",
        "x-user-key": user_key or "",
        "Content-Type": "application/json"
    }


# ─── eToro API Helpers with Retry ────────────────────────────────────────────

def etoro_request(endpoint, method='GET', headers=None, json_data=None):
    """Make an eToro API request with retry logic."""
    if headers is None:
        headers = get_etoro_headers(is_real=False)

    url = f"{ETORO_BASE_URL}{endpoint}"

    for attempt in range(ETORO_MAX_RETRIES):
        try:
            if method == 'GET':
                r = requests.get(url, headers=headers, timeout=ETORO_REQUEST_TIMEOUT)
            else:
                r = requests.post(url, headers=headers, json=json_data, timeout=ETORO_REQUEST_TIMEOUT)

            if r.status_code in [200, 201]:
                return r.json()
            elif r.status_code >= 500:
                # Server error, retry
                wait = 2 ** (attempt + 1)
                time.sleep(wait)
                continue
            else:
                # Client error, don't retry
                return None
        except requests.exceptions.Timeout:
            wait = 2 ** (attempt + 1)
            time.sleep(wait)
        except Exception:
            break

    return None


# ─── Dynamic Ticker Discovery ────────────────────────────────────────────────
_ticker_cache = {'symbols': None, 'instrument_map': {}, 'last_refresh': 0}

def _resolve_instrument_id(instrument_id, headers):
    """Resolve an eToro instrumentID to a ticker symbol."""
    try:
        url = f"{ETORO_BASE_URL}/market-data/search?instrumentId={instrument_id}&fields=instrumentId,internalSymbolFull,displayname"
        r = requests.get(url, headers=headers, timeout=ETORO_REQUEST_TIMEOUT)
        if r.status_code == 200:
            items = r.json().get('items', [])
            if items:
                sym = items[0].get('internalSymbolFull', '')
                # Normalize: TSLA.RTH -> TSLA (RTH = regular trading hours variant)
                base_sym = sym.split('.')[0] if '.' in sym else sym
                return base_sym
    except Exception:
        pass
    return None


def get_portfolio_tickers(force_refresh=False):
    """
    Discover tickers dynamically from the eToro Real portfolio.
    Caches results for 60 minutes. Falls back to FALLBACK_TICKERS.
    """
    now = time.time()
    if not force_refresh and _ticker_cache['symbols'] and (now - _ticker_cache['last_refresh'] < 3600):
        return _ticker_cache['symbols']

    try:
        headers = get_etoro_headers(is_real=True)
        data = etoro_request('/trading/info/portfolio', headers=headers)
        if not data:
            raise ValueError("No portfolio data")

        portfolio = data.get('clientPortfolio', data)
        positions = portfolio.get('positions', portfolio.get('Positions', []))

        # Extract unique instrument IDs
        inst_ids = set()
        for p in positions:
            iid = p.get('instrumentID', p.get('InstrumentID'))
            if iid:
                inst_ids.add(iid)

        # Resolve to symbols
        symbols = set()
        for iid in inst_ids:
            if iid in _ticker_cache['instrument_map']:
                symbols.add(_ticker_cache['instrument_map'][iid])
            else:
                sym = _resolve_instrument_id(iid, headers)
                if sym:
                    _ticker_cache['instrument_map'][iid] = sym
                    symbols.add(sym)

        if symbols:
            _ticker_cache['symbols'] = sorted(symbols)
            _ticker_cache['last_refresh'] = now
            return _ticker_cache['symbols']

    except Exception:
        pass

    # Fallback
    if _ticker_cache['symbols']:
        return _ticker_cache['symbols']
    return FALLBACK_TICKERS


def get_portfolio_equity(is_real=True):
    """
    Fetch live portfolio equity from eToro.
    Equity = sum(position amounts) + credit.
    """
    try:
        headers = get_etoro_headers(is_real=is_real)
        data = etoro_request('/trading/info/portfolio', headers=headers)
        if not data:
            return None

        portfolio = data.get('clientPortfolio', data)
        positions = portfolio.get('positions', portfolio.get('Positions', []))
        credit = portfolio.get('credit', 0)

        total_invested = sum(p.get('amount', p.get('Amount', 0)) for p in positions)
        return total_invested + credit

    except Exception:
        return None


# ─── Market Hours ─────────────────────────────────────────────────────────────

def _get_nyse_holidays(year):
    """
    NYSE holidays for a given year.
    Returns a set of (month, day) tuples for fixed-date holidays,
    plus computed dates for floating holidays.
    """
    from datetime import date
    import calendar

    holidays = set()

    # Fixed-date holidays
    holidays.add(date(year, 1, 1))    # New Year's Day
    holidays.add(date(year, 6, 19))   # Juneteenth
    holidays.add(date(year, 7, 4))    # Independence Day
    holidays.add(date(year, 12, 25))  # Christmas Day

    # MLK Day: 3rd Monday of January
    c = calendar.Calendar(firstweekday=calendar.MONDAY)
    jan_mondays = [d for d in c.itermonthdates(year, 1) if d.month == 1 and d.weekday() == 0]
    if len(jan_mondays) >= 3:
        holidays.add(jan_mondays[2])

    # Presidents' Day: 3rd Monday of February
    feb_mondays = [d for d in c.itermonthdates(year, 2) if d.month == 2 and d.weekday() == 0]
    if len(feb_mondays) >= 3:
        holidays.add(feb_mondays[2])

    # Good Friday: 2 days before Easter Sunday
    # Using anonymous-algorithm for Easter
    a = year % 19
    b = year // 100
    cc = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = cc // 4
    k = cc % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    easter = date(year, month, day)
    good_friday = easter - timedelta(days=2)
    holidays.add(good_friday)

    # Memorial Day: Last Monday of May
    may_mondays = [d for d in c.itermonthdates(year, 5) if d.month == 5 and d.weekday() == 0]
    if may_mondays:
        holidays.add(may_mondays[-1])

    # Labor Day: 1st Monday of September
    sep_mondays = [d for d in c.itermonthdates(year, 9) if d.month == 9 and d.weekday() == 0]
    if sep_mondays:
        holidays.add(sep_mondays[0])

    # Thanksgiving: 4th Thursday of November
    nov_thursdays = [d for d in c.itermonthdates(year, 11) if d.month == 11 and d.weekday() == 3]
    if len(nov_thursdays) >= 4:
        holidays.add(nov_thursdays[3])

    # If holiday falls on Saturday → observed Friday
    # If holiday falls on Sunday → observed Monday
    observed = set()
    for h in holidays:
        if h.weekday() == 5:  # Saturday
            observed.add(h - timedelta(days=1))
        elif h.weekday() == 6:  # Sunday
            observed.add(h + timedelta(days=1))
        else:
            observed.add(h)

    return observed


# Pre-compute holiday cache
_holiday_cache = {}


def _is_nyse_holiday(dt):
    """Check if a date is an NYSE holiday."""
    from datetime import date
    year = dt.year
    if year not in _holiday_cache:
        _holiday_cache[year] = _get_nyse_holidays(year)
    check_date = date(dt.year, dt.month, dt.day)
    return check_date in _holiday_cache[year]


def is_market_open():
    """
    Check if US stock market is currently open.
    Regular hours: Mon-Fri, 9:30 AM - 4:00 PM Eastern.
    Accounts for NYSE holidays.
    """
    now = datetime.now(ET)

    # Weekend check
    if now.weekday() >= 5:
        return False

    # Holiday check
    if _is_nyse_holiday(now):
        return False

    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)

    return market_open <= now <= market_close


def is_premarket():
    """Check if we're in pre-market window (7:00 AM - 9:30 AM ET)."""
    now = datetime.now(ET)
    if now.weekday() >= 5 or _is_nyse_holiday(now):
        return False
    pre_open = now.replace(hour=7, minute=0, second=0, microsecond=0)
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    return pre_open <= now < market_open


def is_postmarket():
    """Check if we're in post-market window (4:00 PM - 8:00 PM ET)."""
    now = datetime.now(ET)
    if now.weekday() >= 5 or _is_nyse_holiday(now):
        return False
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    post_close = now.replace(hour=20, minute=0, second=0, microsecond=0)
    return market_close < now <= post_close


def is_trading_day():
    """Check if today is a trading day (weekday and not an NYSE holiday)."""
    now = datetime.now(ET)
    return now.weekday() < 5 and not _is_nyse_holiday(now)


def seconds_until_market_open():
    """Calculate seconds until next market open. Returns 0 if market is open. Skips holidays."""
    if is_market_open():
        return 0

    now = datetime.now(ET)
    target = now
    while True:
        if target.weekday() < 5 and not _is_nyse_holiday(target):
            market_open = target.replace(hour=9, minute=30, second=0, microsecond=0)
            if market_open > now:
                return (market_open - now).total_seconds()
        target += timedelta(days=1)
        target = target.replace(hour=0, minute=0, second=0, microsecond=0)


def sleep_until_market(logger=None):
    """Sleep until market opens. Logs the wait time."""
    secs = seconds_until_market_open()
    if secs <= 0:
        return

    hours = secs / 3600
    msg = f"Market closed. Sleeping {hours:.1f}h until next open."
    if logger:
        logger.info(msg)
    else:
        print(msg)

    time.sleep(secs)


# ─── Ollama Health Check ─────────────────────────────────────────────────────

def check_ollama_health():
    """Ping Ollama to verify it's running and the model is available."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if r.status_code == 200:
            models = [m.get('name', '') for m in r.json().get('models', [])]
            # Check if our model (or a prefix match) is available
            for m in models:
                if OLLAMA_MODEL.split(':')[0] in m:
                    return True, f"Ollama OK, model '{OLLAMA_MODEL}' available"
            return False, f"Ollama running but model '{OLLAMA_MODEL}' not found. Available: {models}"
        return False, f"Ollama returned status {r.status_code}"
    except requests.exceptions.ConnectionError:
        return False, "Ollama not reachable at localhost:11434"
    except Exception as e:
        return False, f"Ollama health check failed: {e}"
