#!/usr/bin/env python3
"""ThetaData free-tier continuity backup (user directive 2026-10-17, item 6).

The free tier is the ONLY options dataset we will ever have (no purchases,
ever). Export every ThetaData-derived table to parquet with row counts and
sha256 checksums in a versioned directory, then run a restore test (read
parquet back, verify row counts + date spans vs the live DB).

No S3 bucket is configured on this host; the versioned local directory is
the sanctioned equivalent.

Memory-safe: streams psycopg2 server-side cursor chunks into a pyarrow
ParquetWriter; restore test uses parquet metadata + column scans, never a
full DataFrame. (v1 OOM-killed on a 6.2M-row concat, 2026-10-17.)

Usage: /usr/bin/python3 export_backup.py [--dest /home/ubuntu/backups/thetadata]
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

ETL = "/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl"
sys.path.insert(0, os.path.join(ETL, "shared", "scripts"))
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
import db
import pyarrow as pa
import pyarrow.parquet as pq

TABLES = [
    # (schema.table, order key or None, date column for span check or None)
    ("bronze.thetadata_option_eod_raw", "trade_date", "trade_date"),
    ("bronze.thetadata_option_greeks_eod_raw", "trade_date", "trade_date"),
    ("bronze.thetadata_option_open_interest_raw", "trade_date", "trade_date"),
    ("bronze.thetadata_stock_eod_raw", "trade_date", "trade_date"),
    ("bronze.thetadata_ingest_runs", None, None),
    ("silver.option_eod_quotes", "trade_date", "trade_date"),
    ("silver.option_eod_greeks", "trade_date", "trade_date"),
    ("silver.option_contracts", None, None),
    ("silver.thetadata_date_completeness", None, "date"),
    ("silver.thetadata_load_ledger", None, None),
    ("deriv.underlying_dividends", None, None),
    ("gold.interbank_rates", None, None),
]
CHUNK = 100_000


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _norm(v):
    # Normalize for stable arrow inference across chunks: Decimal -> float64
    # (numeric precision drifted between chunks otherwise), UUID -> str.
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, UUID):
        return str(v)
    return v


def _pk_cols(conn, table):
    sch, tbl = table.split(".")
    cur = conn.cursor()
    cur.execute("""
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = %s AND tc.table_name = %s
        ORDER BY kcu.ordinal_position""", (sch, tbl))
    cols = [r[0] for r in cur.fetchall()]
    cur.close()
    return cols


def export_table(table, order_key, outdir):
    # Fresh pooled connection per table. Keyset pagination on the PK —
    # server-side (named) cursors don't populate description through the
    # db.py pool, and client-side fetchall OOMs on 6M+ rows (v1 incident).
    conn = db.get_connection()
    fname = table.replace(".", "__") + ".parquet"
    path = os.path.join(outdir, fname)
    cur = conn.cursor()
    cur.execute(f"SELECT count(*) FROM {table}")
    n_db = cur.fetchone()[0]
    if n_db == 0:
        cur.close(); conn.close()
        return {"table": table, "rows_db": 0, "rows_parquet": 0,
                "file": None, "sha256": None, "note": "empty (tier-gated)",
                "count_match": True}
    pk = _pk_cols(conn, table)
    if not pk:
        pk = [order_key] if order_key else None
    if not pk:
        cur.close(); conn.close()
        return {"table": table, "rows_db": n_db, "rows_parquet": 0,
                "file": None, "sha256": None,
                "note": "SKIP: no PK/order key", "count_match": False}
    order = ", ".join(pk)
    writer = None
    schema = None
    n = 0
    last = None
    while True:
        if last is None:
            cur.execute(f"SELECT * FROM {table} ORDER BY {order} LIMIT {CHUNK}")
        else:
            cols_csv = ", ".join(pk)
            placeholders = ", ".join(["%s"] * len(pk))
            cur.execute(
                f"SELECT * FROM {table} WHERE ({cols_csv}) > ({placeholders}) "
                f"ORDER BY {order} LIMIT {CHUNK}", tuple(last))
        rows = cur.fetchall()
        if not rows:
            break
        cols = [d[0] for d in cur.description]
        recs = [{c: _norm(v) for c, v in zip(cols, r)} for r in rows]
        if schema is None:
            batch = pa.RecordBatch.from_pylist(recs)
            schema = batch.schema  # pin: later chunks cast to this (uuid/str drift)
        else:
            batch = pa.RecordBatch.from_pylist(recs, schema=schema)
        if writer is None:
            writer = pq.ParquetWriter(path, schema, compression="snappy")
        writer.write_batch(batch)
        n += len(rows)
        last = [rows[-1][cols.index(c)] for c in pk]
    cur.close()
    if writer is None:
        conn.close()
        return {"table": table, "rows_db": n_db, "rows_parquet": 0,
                "file": None, "sha256": None, "note": "empty at read time",
                "count_match": n_db == 0}
    writer.close()
    conn.close()
    digest = sha256_file(path)
    return {"table": table, "rows_db": n_db, "rows_parquet": n,
            "file": fname, "bytes": os.path.getsize(path),
            "sha256": digest, "count_match": n == n_db}


def restore_test(conn, entry, outdir):
    if not entry["file"]:
        return {"table": entry["table"], "restore": "SKIP_EMPTY"}
    path = os.path.join(outdir, entry["file"])
    pf = pq.ParquetFile(path)
    n_pq = pf.metadata.num_rows
    res = {"table": entry["table"], "rows_readback": n_pq,
           "count_match": n_pq == entry["rows_db"]}
    dc = entry.get("date_col")
    if dc and dc in pf.schema.names:
        col = pf.read(columns=[dc]).column(dc).to_pylist()
        pmin, pmax = min(col), max(col)
        cur = conn.cursor()
        cur.execute(f"SELECT min({dc}), max({dc}) FROM {entry['table']}")
        lo, hi = cur.fetchone()
        cur.close()
        res["db_span"] = [str(lo), str(hi)]
        res["parquet_span"] = [str(pmin), str(pmax)]
        res["span_match"] = str(lo) == str(pmin) and str(hi) == str(pmax)
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
    manifest = {"version": version,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "source_db": "aitrading", "tables": []}
    entries = []
    for table, ok_key, dc in TABLES:
        print(f"exporting {table} ...", flush=True)
        entry = export_table(table, ok_key, outdir)
        entry["date_col"] = dc
        print(f"  -> {entry['rows_db']} rows, "
              f"{entry.get('bytes', 0)/1e6:.1f} MB, match={entry.get('count_match')}",
              flush=True)
        entries.append(entry)
        manifest["tables"].append(entry)

    print("restore test ...", flush=True)
    manifest["restore_test"] = [restore_test(conn, e, outdir) for e in entries]
    for r in manifest["restore_test"]:
        print(f"  {r['table']}: {r['restore']}", flush=True)

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
