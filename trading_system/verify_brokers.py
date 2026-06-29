"""
Safe broker readiness checks.

Prints configuration presence and connectivity status only. It never prints API
keys and does not place trades.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from broker_providers import probe_socket
from config import (
    get_credential,
    get_execution_broker,
    get_futu_default_market,
    get_futu_opend_host,
    get_futu_opend_port,
    get_futu_trd_env,
)


def _default_module_probe():
    try:
        import moomoo

        return True, getattr(moomoo, "__version__", "unknown"), None
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}"


def check_etoro_credentials():
    return {
        "public_key_configured": bool(get_credential("etoro_pub_key")),
        "demo_key_configured": bool(get_credential("etoro_demo_key")),
        "real_key_configured": bool(get_credential("etoro_real_key")),
    }


def check_moomoo_readiness(socket_probe=probe_socket, module_probe=_default_module_probe):
    host = get_futu_opend_host()
    port = get_futu_opend_port()
    reachable, socket_error = socket_probe(host, port)
    has_module, version, module_error = module_probe()

    return {
        "host": host,
        "port": port,
        "opend_reachable": bool(reachable),
        "opend_error": socket_error,
        "moomoo_module": bool(has_module),
        "moomoo_version": version,
        "moomoo_error": module_error,
        "trd_env": get_futu_trd_env(),
        "default_market": get_futu_default_market(),
    }


def build_report():
    return {
        "execution_broker": get_execution_broker(),
        "etoro": check_etoro_credentials(),
        "moomoo": check_moomoo_readiness(),
        "trade_execution": "disabled in stock_telegram_monitor",
    }


def main():
    parser = argparse.ArgumentParser(description="Verify eToro and moomoo readiness without exposing secrets.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    etoro = report["etoro"]
    moomoo = report["moomoo"]
    print("BROKER READINESS")
    print(f"execution_broker={report['execution_broker']}")
    print(
        "etoro="
        f"public:{etoro['public_key_configured']} "
        f"demo:{etoro['demo_key_configured']} "
        f"real:{etoro['real_key_configured']}"
    )
    print(
        "moomoo="
        f"sdk:{moomoo['moomoo_module']} "
        f"version:{moomoo['moomoo_version']} "
        f"opend:{moomoo['opend_reachable']} "
        f"host:{moomoo['host']}:{moomoo['port']} "
        f"env:{moomoo['trd_env']}"
    )
    if moomoo.get("opend_error"):
        print(f"moomoo_opend_error={moomoo['opend_error']}")
    if moomoo.get("moomoo_error"):
        print(f"moomoo_sdk_error={moomoo['moomoo_error']}")
    print(report["trade_execution"])


if __name__ == "__main__":
    main()
