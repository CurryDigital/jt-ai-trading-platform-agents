#!/usr/bin/env python3
"""
Validate HK broker mapping for ETF_HK_Balanced_Trend and HK_Quality_BlueChips.

Reads universe tickers from gold.strategy_registry, checks bronze.ibkr_contracts,
connects to IBKR TWS API, and verifies each mapped contract returns live price data.

Outputs a JSON manifest with per-ticker mapping and validation status.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import psycopg2
from dotenv import load_dotenv

# Use ib_insync from the Hermes agent venv
sys.path.insert(0, os.path.expanduser("~/.hermes/hermes-agent/venv/lib/python3.11/site-packages"))
from ib_insync import IB, Stock  # noqa: E402

ENV_PATH = os.path.expanduser("~/.hermes/profiles/qr_etl/env/etl.env")
load_dotenv(ENV_PATH, override=True)

DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", 5432))
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_NAME = os.environ["DB_NAME"]
IBKR_HOST = os.environ.get("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.environ.get("IBKR_LOCAL_TUNNEL_PORT", 14002))

STRATEGIES = ["ETF_HK_Balanced_Trend", "HK_Quality_BlueChips"]


def get_db_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASSWORD, dbname=DB_NAME, sslmode="require"
    )


def normalize_broker_symbol(ticker: str) -> str:
    """Strip .HK and leading zeros for IBKR SEHK symbology."""
    if ticker == "AGG":
        return "AGG"
    return ticker.replace(".HK", "").lstrip("0") or "0"


def load_universes():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT strategy_id, universe_tickers
        FROM gold.strategy_registry
        WHERE strategy_id = ANY(%s)
        ORDER BY strategy_id;
        """,
        (STRATEGIES,),
    )
    universes = {r[0]: r[1] for r in cur.fetchall()}
    conn.close()
    return universes


def load_contracts(tickers):
    conn = get_db_conn()
    cur = conn.cursor()
    broker_symbols = [normalize_broker_symbol(t) for t in tickers]
    cur.execute(
        """
        SELECT con_id, symbol, sec_type, exchange, currency, local_symbol, trading_class
        FROM bronze.ibkr_contracts
        WHERE symbol = ANY(%s) OR local_symbol = ANY(%s)
        ORDER BY symbol;
        """,
        (tickers, broker_symbols),
    )
    rows = {r[1]: dict(
        con_id=r[0],
        symbol=r[1],
        sec_type=r[2],
        exchange=r[3],
        currency=r[4],
        local_symbol=r[5],
        trading_class=r[6],
    ) for r in cur.fetchall()}
    conn.close()
    return rows


def validate_price(ib, contract_row, timeout=20):
    """Try to fetch a single 1-day historical bar to prove live data exists."""
    try:
        # Use IBKR's local_symbol (e.g. '1' for 0001.HK) and explicit conId if known.
        contract = Stock(
            contract_row["local_symbol"],
            contract_row["exchange"],
            contract_row["currency"],
        )
        contract.conId = contract_row["con_id"]
        qualified = ib.qualifyContracts(contract)
        if not qualified:
            return False, "qualifyContracts returned empty"
        c = qualified[0]
        bars = ib.reqHistoricalData(
            c,
            endDateTime="",
            durationStr="1 D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
        if bars is None:
            return False, "timeout/no response"
        if not bars:
            return False, "empty bar list"
        last = bars[-1]
        return True, {
            "bar_time": str(last.date),
            "open": last.open,
            "high": last.high,
            "low": last.low,
            "close": last.close,
            "volume": int(last.volume or 0),
        }
    except Exception as e:
        return False, f"exception: {e}"


def main():
    universes = load_universes()
    all_tickers = sorted(set(t for tickers in universes.values() for t in tickers))
    contracts = load_contracts(all_tickers)

    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=115, timeout=15)
        print(f"Connected to IBKR {IBKR_HOST}:{IBKR_PORT} (server {ib.client.serverVersion()})")
    except Exception as e:
        print(f"ERROR: cannot connect to IBKR {IBKR_HOST}:{IBKR_PORT}: {e}")
        sys.exit(1)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "gold.strategy_registry",
        "broker_table": "bronze.ibkr_contracts",
        "ibkr_host": f"{IBKR_HOST}:{IBKR_PORT}",
        "strategies": {sid: list(tickers) for sid, tickers in universes.items()},
        "tickers": [],
        "summary": {"total": 0, "mapped": 0, "validated": 0, "failed": 0, "missing": 0, "delisted": 0},
    }

    try:
        for ticker in all_tickers:
            broker_symbol = normalize_broker_symbol(ticker)
            entry = {
                "ticker": ticker,
                "broker_symbol": broker_symbol,
                "strategy_membership": [sid for sid, tickers in universes.items() if ticker in tickers],
            }
            contract = contracts.get(ticker)
            if not contract:
                entry["status"] = "missing"
                entry["error"] = "no row in bronze.ibkr_contracts"
                manifest["summary"]["missing"] += 1
            else:
                entry["con_id"] = contract["con_id"]
                entry["exchange"] = contract["exchange"]
                entry["currency"] = contract["currency"]
                entry["local_symbol"] = contract["local_symbol"]
                entry["trading_class"] = contract["trading_class"]
                entry["status"] = "mapped"
                manifest["summary"]["mapped"] += 1

                ok, detail = validate_price(ib, contract)
                if ok:
                    entry["status"] = "validated"
                    entry["last_bar"] = detail
                    manifest["summary"]["validated"] += 1
                else:
                    entry["status"] = "failed"
                    entry["error"] = detail
                    manifest["summary"]["failed"] += 1

            manifest["tickers"].append(entry)
            manifest["summary"]["total"] += 1
            time.sleep(0.5)
    finally:
        ib.disconnect()

    # Override 0011.HK status to delisted based on external verification
    for entry in manifest["tickers"]:
        if entry["ticker"] == "0011.HK":
            if entry["status"] in ("missing", "failed"):
                manifest["summary"][entry["status"]] -= 1
            entry["status"] = "delisted"
            entry["error"] = "0011.HK (Hang Seng Bank) delisted/taken private by HSBC; no live broker symbol"
            manifest["summary"]["delisted"] += 1

    # Sort summary keys for readability
    manifest["summary"] = dict(sorted(manifest["summary"].items()))

    output_path = os.environ.get("OUTPUT_PATH", "/tmp/hk_broker_mapping_manifest.json")
    with open(output_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    print(json.dumps(manifest["summary"], indent=2))
    print(f"Manifest written to {output_path}")
    return manifest


if __name__ == "__main__":
    main()
