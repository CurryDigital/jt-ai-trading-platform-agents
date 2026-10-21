#!/usr/bin/env python3
"""
regime_features v2 build + preheal reconstruction diff (user directive 2026-10-15).

Step A: compute features from CURRENT (healed) gold, write gold.regime_features_v2
        (append-only, ON CONFLICT DO NOTHING, build_tag='gapfix_v1_20261014').
Step B: recompute against a PRE-HEAL VIEW (gold.daily_ohlcv minus the healed rows),
        write scratch table gold.regime_features_recon_preheal, then diff by month.
Step C: diff v2 vs v1 by month (expected ~identical: v1 was already restated by
        the 2026-10-14 22:32 gold_builder run — verified separately).

build_regime_features.compute_features() upserts gold.regime_features and closes
the connection as side effects; a connection proxy rewrites the write target and
swallows close(). Engine code is NOT modified.
"""
import os, re, sys, json, importlib.util

ETL = os.path.expanduser("~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl")
sys.path.insert(0, os.path.join(ETL, 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
import db

spec = importlib.util.spec_from_file_location(
    "build_regime_features", os.path.join(ETL, 'gold', 'build_regime_features.py'))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

TAG = 'gapfix_v1_20261014'
UPSERT_FIX = re.compile(r"ON CONFLICT \(date\) DO UPDATE SET.*?computed_at = NOW\(\)",
                        re.DOTALL)


class ProxyCursor:
    def __init__(self, cur, write_target, read_source=None):
        self._cur = cur
        self._wt = write_target
        self._rs = read_source
    def execute(self, sql, params=None):
        sql = sql.replace('gold.regime_features', self._wt)
        sql = UPSERT_FIX.sub("ON CONFLICT (date) DO NOTHING", sql)
        if self._rs:
            sql = sql.replace('gold.daily_ohlcv', self._rs)
        return self._cur.execute(sql, params)
    def __getattr__(self, k):
        return getattr(self._cur, k)


class ProxyConn:
    def __init__(self, conn, write_target, read_source=None):
        self._conn = conn
        self._wt = write_target
        self._rs = read_source
    def cursor(self):
        return ProxyCursor(self._conn.cursor(), self._wt, self._rs)
    def commit(self):
        return self._conn.commit()
    def close(self):
        pass  # compute_features closes the conn; we keep it


def ensure_tables(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gold.regime_features_v2 (
            date date PRIMARY KEY, adx14 float8, hurst_30 float8, rv5d float8,
            rv_iv_ratio float8, vix_z60 float8, spy_above_200 int2,
            breadth_50 float8, funding_z float8, event_flag int2,
            adx_hurst_cross float8, rv5d_change float8,
            computed_at timestamp, build_tag text)""")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gold.regime_features_recon_preheal (
            date date PRIMARY KEY, adx14 float8, hurst_30 float8, rv5d float8,
            rv_iv_ratio float8, vix_z60 float8, spy_above_200 int2,
            breadth_50 float8, funding_z float8, event_flag int2,
            adx_hurst_cross float8, rv5d_change float8,
            computed_at timestamp)""")
    cur.execute("DELETE FROM gold.regime_features_recon_preheal")
    # pre-heal view: gold minus every row the heal inserted (incl. the 7 whose
    # tag was later overwritten by the nightly 14d mirror, dated 2026-10-12)
    cur.execute("""
        CREATE OR REPLACE VIEW gold.daily_ohlcv_preheal_v AS
        SELECT * FROM gold.daily_ohlcv
        WHERE primary_source NOT LIKE 'gapfix_v1_20261014%%'
          AND (ticker, date) NOT IN (
              ('1641.HK','2026-10-12'::date), ('2512.HK','2026-10-12'),
              ('2529.HK','2026-10-12'), ('2545.HK','2026-10-12'),
              ('2549.HK','2026-10-12'), ('5JS.SI','2026-10-12'),
              ('6959.HK','2026-10-12'))""")


def main():
    conn = db.get_connection()
    cur = conn.cursor()
    ensure_tables(cur)
    conn.commit()

    print("== STEP A: v2 from healed gold ==", flush=True)
    feats = mod.compute_features(ProxyConn(conn, 'gold.regime_features_v2'))
    conn.commit()
    cur.execute("UPDATE gold.regime_features_v2 SET build_tag=%s WHERE build_tag IS NULL", (TAG,))
    conn.commit()
    cur.execute("SELECT count(*), min(date), max(date) FROM gold.regime_features_v2")
    print("  v2:", cur.fetchone(), flush=True)

    print("== STEP B: preheal reconstruction ==", flush=True)
    mod.compute_features(ProxyConn(conn, 'gold.regime_features_recon_preheal',
                                   read_source='gold.daily_ohlcv_preheal_v'))
    conn.commit()
    cur.execute("SELECT count(*) FROM gold.regime_features_recon_preheal")
    print("  recon:", cur.fetchone(), flush=True)

    print("== STEP C1: diff v2 vs v1 by month ==", flush=True)
    cur.execute("""
        SELECT date_trunc('month', a.date)::date, count(*),
               round(avg(abs(a.rv5d - b.rv5d))::numeric, 8) AS rv5d_mad,
               round(avg(abs(a.adx14 - b.adx14))::numeric, 6) AS adx_mad,
               round(avg(abs(a.breadth_50 - b.breadth_50))::numeric, 8) AS br_mad
        FROM gold.regime_features_v2 a JOIN gold.regime_features b USING (date)
        GROUP BY 1 HAVING avg(abs(a.rv5d - b.rv5d)) > 0
                    OR avg(abs(a.adx14 - b.adx14)) > 0
                    OR avg(abs(a.breadth_50 - b.breadth_50)) > 0
        ORDER BY 1""")
    rows = cur.fetchall()
    print(f"  months with any v2-vs-v1 drift: {len(rows)}")
    for r in rows[:12]:
        print("   ", r)

    print("== STEP C2: diff v2 (healed) vs preheal recon, by month ==", flush=True)
    cur.execute("""
        SELECT date_trunc('month', a.date)::date AS m, count(*) n,
               round(avg(abs(a.rv5d - b.rv5d))::numeric, 8) AS rv5d_mad,
               round(avg(abs(a.adx14 - b.adx14))::numeric, 6) AS adx_mad,
               round(avg(abs(a.breadth_50 - b.breadth_50))::numeric, 8) AS br_mad,
               round(avg(abs(a.hurst_30 - b.hurst_30))::numeric, 6) AS hurst_mad
        FROM gold.regime_features_v2 a
        JOIN gold.regime_features_recon_preheal b USING (date)
        GROUP BY 1 ORDER BY 1""")
    rows = cur.fetchall()
    out = []
    print("   month        n    rv5d_mad    adx_mad    breadth_mad  hurst_mad")
    for r in rows:
        flag = (r[2] or 0) > 0 or (r[3] or 0) > 0 or (r[4] or 0) > 0 or (r[5] or 0) > 0
        out.append({"month": str(r[0]), "n": r[1], "rv5d_mad": float(r[2] or 0),
                    "adx_mad": float(r[3] or 0), "breadth_mad": float(r[4] or 0),
                    "hurst_mad": float(r[5] or 0), "changed": flag})
        if flag:
            print(f"   {r[0]}  {r[1]:4d}  {r[2]}  {r[3]}  {r[4]}  {r[5]}")
    changed = [o for o in out if o["changed"]]
    print(f"  months changed by the heal: {len(changed)} of {len(out)}")

    rep = os.path.expanduser(
        "~/.hermes/profiles/qr_etl/workspace/ohlcv_gap_audit_v1/regime_features_v2_month_diff.json")
    with open(rep, "w") as f:
        json.dump({"v2_rows_tag": TAG, "month_diff_vs_preheal": out}, f, indent=1)
    print("  wrote", rep)
    conn.close()

if __name__ == '__main__':
    main()
