import os
import sys
import socket
from decimal import Decimal, ROUND_FLOOR

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (
    get_futu_opend_host,
    get_futu_opend_port,
    get_futu_trd_env,
    get_futu_default_market,
    get_futu_security_firm,
    is_trading_day,
    is_market_open,
    is_premarket,
)
from logger import get_logger

log = get_logger("MoomooTrader")


def _ensure_opend_reachable(host, port):
    sock = None
    try:
        sock = socket.create_connection((host, int(port)), timeout=1.5)
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass


def to_moomoo_code(symbol, default_market=None):
    if not symbol:
        return None
    s = str(symbol).strip()
    if not s:
        return None
    if "." in s:
        prefix = s.split(".", 1)[0].upper()
        if prefix in {"US", "HK", "SH", "SZ", "SG"}:
            return f"{prefix}.{s.split('.', 1)[1]}"
    if default_market is None:
        default_market = get_futu_default_market()
    market = str(default_market or "US").strip().upper()
    if market not in {"US", "HK", "SH", "SZ", "SG"}:
        market = "US"
    return f"{market}.{s.upper()}"


def _get_quote_ctx():
    from moomoo import OpenQuoteContext

    host = get_futu_opend_host()
    port = get_futu_opend_port()
    _ensure_opend_reachable(host, port)
    return OpenQuoteContext(host=host, port=port, ai_type=1)


def _get_trd_ctx():
    from moomoo import OpenSecTradeContext, SecurityFirm

    host = get_futu_opend_host()
    port = get_futu_opend_port()
    _ensure_opend_reachable(host, port)
    firm = get_futu_security_firm()
    security_firm = SecurityFirm.NONE
    if firm:
        firm_name = str(firm).strip().upper()
        if hasattr(SecurityFirm, firm_name):
            security_firm = getattr(SecurityFirm, firm_name)
    return OpenSecTradeContext(host=host, port=port, security_firm=security_firm, ai_type=1)


def _resolve_trd_env():
    from moomoo import TrdEnv

    env = str(get_futu_trd_env() or "SIMULATE").strip().upper()
    if env == "REAL":
        return TrdEnv.REAL
    return TrdEnv.SIMULATE


def _pick_account_id(trd_ctx, trd_env):
    ret, data = trd_ctx.get_acc_list()
    if ret != 0:
        raise RuntimeError(f"get_acc_list failed: {ret}")
    for acc in data:
        try:
            if acc.get("trd_env") == trd_env:
                return acc.get("acc_id")
        except Exception:
            continue
    return data[0].get("acc_id") if data else None


def _last_price_for_code(quote_ctx, code):
    ret, data = quote_ctx.get_market_snapshot([code])
    if ret != 0 or data is None or len(data) == 0:
        raise RuntimeError(f"get_market_snapshot failed for {code}: {ret}")
    row = data.iloc[0]
    for k in ("last_price", "cur_price", "price"):
        if k in row and row[k] is not None:
            try:
                return float(row[k])
            except Exception:
                continue
    raise RuntimeError(f"Could not read last price for {code}")


def _position_qty(trd_ctx, code, trd_env, acc_id):
    ret, data = trd_ctx.position_list_query(trd_env=trd_env, acc_id=acc_id, refresh_cache=True)
    if ret != 0 or data is None:
        return 0
    if len(data) == 0:
        return 0
    for _, row in data.iterrows():
        try:
            if str(row.get("code")) == str(code):
                qty = row.get("qty")
                return int(float(qty)) if qty is not None else 0
        except Exception:
            continue
    return 0


def execute_moomoo_trade(symbol, action, amount):
    if get_futu_trd_env() == "REAL":
        log.error("REAL auto-execution is disabled. Send suggestions only and confirm orders manually.")
        return False

    from moomoo import TrdSide, OrderType, RET_OK

    trd_env = _resolve_trd_env()
    env_name = "REAL" if str(trd_env).endswith("REAL") else "SIMULATE"

    if not is_trading_day() and env_name == "REAL":
        log.error("Not a trading day. Blocking REAL order placement.")
        return False

    if env_name == "REAL" and not (is_market_open() or is_premarket()):
        log.error("Market closed. Blocking REAL order placement.")
        return False

    code = to_moomoo_code(symbol)
    if not code:
        return False

    side = str(action or "").strip().upper()
    if side not in {"BUY", "SELL"}:
        return False

    try:
        amt = float(amount)
    except Exception:
        return False
    if amt <= 0:
        return False

    quote_ctx = None
    trd_ctx = None
    try:
        quote_ctx = _get_quote_ctx()
        trd_ctx = _get_trd_ctx()

        acc_id = _pick_account_id(trd_ctx, trd_env)
        if not acc_id:
            raise RuntimeError("No trading account available")

        last_price = _last_price_for_code(quote_ctx, code)
        if last_price <= 0:
            raise RuntimeError("Invalid last price")

        qty_decimal = (Decimal(str(amt)) / Decimal(str(last_price))).quantize(Decimal("1"), rounding=ROUND_FLOOR)
        qty = int(qty_decimal)
        if qty <= 0:
            raise RuntimeError(f"Amount too small for {code} at {last_price}")

        if side == "SELL":
            held = _position_qty(trd_ctx, code, trd_env, acc_id)
            if held <= 0:
                return False
            qty = min(qty, held)
            if qty <= 0:
                return False

        trd_side = TrdSide.BUY if side == "BUY" else TrdSide.SELL
        ret, data = trd_ctx.place_order(
            price=float(last_price),
            qty=qty,
            code=code,
            trd_side=trd_side,
            order_type=OrderType.NORMAL,
            trd_env=trd_env,
            acc_id=acc_id,
        )

        if ret != RET_OK:
            log.error(f"place_order failed: ret={ret}")
            return False
        return True
    except Exception as e:
        log.error(f"Moomoo execution error: {e}")
        return False
    finally:
        if quote_ctx:
            try:
                quote_ctx.close()
            except Exception:
                pass
        if trd_ctx:
            try:
                trd_ctx.close()
            except Exception:
                pass
