#!/usr/bin/env python3
"""ThetaData free-tier continuity backup (user directive 2026-10-17, item 6).

The free tier is the ONLY options dataset we will ever have (no purchases,
ever). Export every ThetaData-derived table to parquet with row counts and
sha256 checksums in a versioned directory, then run a restore test (read
parquet back, verify row counts + aggregates vs the live DB).

No S3 bucket is configured on this host; the versioned local directory is
the sanctioned equivalent.

Usage: /usr/bin/python3 export_backup.py [--dest /home/ubuntu/backups/thetadata]
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

ETL = "/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl"
sys.path.insert(0, os.path.join(ETL, "shared", "scripts"))
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
import db
import pandas as pd

TABLES = [
    # (schema.table, order/chunk key or None)
    ("bronze.thetadata_option_eod_raw", "trade_date"),
    ("bronze.thetadata_option_greeks_eod_raw", "trade_date"),
    ("bronze.thetadata_option_open_interest_raw", "trade_date"),
    ("bronze.thetadata_stock_eod_raw", "trade_date"),
    ("bronze.thetadata_ingest_runs", None),
    ("silver.option_eod_quotes", "trade_date"),
    ("silver.option_eod_greeks", "trade_date"),
    ("silver.option_contracts", None),
    ("silver.thetadata_date_completeness", None),
    ("silver.thetadata_load_ledger", None),
    ("deriv.underlying_dividends", None),
    ("gold.interbank_rates", None),
]
CHUNK = 500_000


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def export_table(cur, table, chunk_key, outdir):
    fname = table.replace(".", "__") + ".parquet"
    path = os.path.join(outdir, fname)
    cur.execute(f"SELECT count(*) FROM {table}")
    n_db = cur.fetchone()[0]
    if n_db == 0:
        # write an empty-but-valid marker; nothing to export
        return {"table": table, "rows_db": 0, "rows_parquet": 0,
                "file": None, "sha256": None, "note": "empty (tier-gated)"}
    order = f" ORDER BY {chunk_key}" if chunk_key else ""
    parts = []
    for chunk in pd.read_sql(f"SELECT * FROM {table}{order}", cur.connection,
                             chunksize=CHUNK):
        parts.append(chunk)
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    df.to_parquet(path, compression="snappy", index=False)
    n_pq = len(df)
    digest = sha256_file(path)
    ok = n_pq == n_db
    return {"table": table, "rows_db": n_db, "rows_parquet": n_pq,
            "file": fname, "bytes": os.path.getsize(path),
            "sha256": digest, "count_match": ok}


def restore_test(cur, entry, outdir):
    """Read parquet back; verify count + (for dated tables) min/max date
    against the live DB."""
    if not entry["file"]:
        return {"table": entry["table"], "restore": "SKIP_EMPTY"}
    df = pd.read_parquet(os.path.join(outdir, entry["file"]))
    res = {"table": entry["table"], "rows_readback": len(df),
           "count_match": len(df) == entry["rows_db"]}
    date_cols = [c for c in df.columns if c in ("trade_date", "date", "feature_date")]
    if date_cols:
        dc = date_cols[0]
        cur.execute(f"SELECT min({dc}), max({dc}) FROM {entry['table']}")
        lo, hi = cur.fetchone()
        pmin = pd.to_datetime(df[dc]).min().date()
        pmax = pd.to_datetime(df[dc]).max().date()
        res["db_span"] = [str(lo), str(hi)]
        res["parquet_span"] = [str(pmin), str(pmax)]
        res["span_match"] = (str(lo), str(hi)) == (str(pmin), str(pmax))
    res["restore"] = "PASS" if res["count_match"] and res.get("span_match", True) else "FAIL"
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="/home/ubuntu/backups/thetadata")
    args = ap.parse_args()
    version = "v_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    outdir = os.path.join(args.dest, version)
    os.makedirs(outdir, exist_ok=True)

    conn = db.get_connection()
    cur = conn.cursor()
    manifest = {"version": version,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "source_db": "aitrading",
                "tables": []}
    for table, ck in TABLES:
        print(f"exporting {table} ...", flush=True)
        entry = export_table(cur, table, ck, outdir)
        print(f"  -> {entry['rows_db']} rows, "
              f"{entry.get('bytes', 0)/1e6:.1f} MB, match={entry.get('count_match')}")
        manifest["tables"].append(entry)

    print("restore test ...", flush=True)
    manifest["restore_test"] = [restore_test(cur, e, outdir)
                                for e in manifest["tables"]]
    for r in manifest["restore_test"]:
        print(f"  {r['table']}: {r['restore']}")

    with open(os.path.join(outdir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, default=str)
    conn.close()
    fails = [r for r in manifest["restore_test"] if r["restore"] == "FAIL"]
    mismatches = [e for e in manifest["tables"] if e.get("count_match") is False]
    print(f"DONE version={version} dir={outdir}")
    print(f"restore FAILs: {len(fails)}; count mismatches: {len(mismatches)}")
    sys.exit(1 if (fails or mismatches) else 0)


if __name__ == "__main__":
    main()
