#!/usr/bin/env python3
"""Gold: per-strategy portfolio-level monthly backtest returns.

Writes to: gold.strategy_backtest_monthly_returns
Consumed by: consumption.strategy_monthly_returns (view) ->
             GET /api/strategies/{id}/evaluation -> monthly_returns heatmap.

Source policy (t_d152898f):
  Each published series must be the research backtest engine's own
  portfolio-level output, VERIFIED at ingest time against the latest
  gold.strategy_backtest_runs row:

    * research_curve: compound of the artifact's daily portfolio_value
      returns over the run's OOS window must reproduce returns_oos within
      ROOS_TOL. For strategies flagged in gold.strategy_configs with
      trades_sum_is_book_annual_return=false (research-approved book
      annuals), each calendar year must additionally reproduce
      annual_pnl_YYYY within ANNUAL_TOL.
    * trades_recon_single_position: only for books with max concurrency 1
      (one full-capital position at a time). Monthly return compounds the
      per-trade pnl_pct of trades closed in that month; the whole OOS
      window must compound to returns_oos within ROOS_TOL.

  Strategies whose artifact fails verification publish NOTHING (fail-safe):
  a missing heatmap is better than a wrong one. Sum-of-per-trade-returns
  is NOT a portfolio monthly return and is never served here (banned
  pattern: unweighted SUM(pnl_pct) over concurrent positions, and the old
  median|pnl| unit-sniffing heuristic, cf. t_e8b2c2d6).

  The artifact registry below is curated and explicit — no directory scans
  of the research workspace at runtime.

Idempotent: full DELETE+INSERT rebuild from deterministic inputs.

Credentials: /home/ubuntu/.env via OPENCLAW_DATABASE_URL.
Run with the ETL venv: /home/ubuntu/.hermes/etl-venv/bin/python3
"""

import logging
import os
from decimal import Decimal

import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv("/home/ubuntu/.env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

RESEARCH_WS = "/home/ubuntu/.hermes/profiles/qr_research/workspace"

ROOS_TOL = 0.005    # abs tolerance on compounded OOS window total vs returns_oos
ANNUAL_TOL = 0.01   # abs tolerance on calendar-year compound vs annual_pnl_YYYY

# --- Curated verified artifact registry -----------------------------------
# Entries through ETF_HK_Balanced_Trend were verified 2026-09-07
# (t_d152898f) to compound to the strategy's published returns_oos to <1e-4
# over the run OOS window, and (for trades_sum-gated strategies) to each
# annual_pnl_YYYY exactly.
# 2026-09-22 additions (t_fdfdf106), all PASS roos + annual gates at ingest:
#   hk_ipo_postlisting_drift_c1  — ipo_pulse_C1_trade_log.csv (2026-09-21
#       post-epsilon re-run, audit_c1_r2 PASS x4; compounds to +1.1077 and
#       annuals 2024/25/26 to 6dp of run ecc87557)
#   COMM_Copper_Trend_VolTarget  — lb126_vt10 DEPLOYED variant per
#       gold.strategy_registry (registry.returns_oos=0.1868 = run d1de795a;
#       the 4-variant grid shares created_at so latest_runs must match the
#       registry, see below)
#   COMM_Gold_Trend_VolTarget    — lb63_vt10 DEPLOYED variant (run 744bb1b5)
#   HK_LowVol_TrendFilter_Weekly — run notes name this exact file as the
#       book-curve source of the corrected annuals
#   HK_LowVol_Weekly             — same batch sibling
# Format: date,portfolio_value,period_return,<per-ticker weights...>
CURVE_SOURCES = {
    "hk_ipo_postlisting_drift_p1":     "hk_ipo_batch/verify_P1_curve.csv",
    "hk_ipo_postlisting_drift_p1_v3":  "hk_ipo_batch/ipo_pulse_V3_trade_log.csv",
    "hk_ipo_postlisting_drift_p2":     "hk_ipo_batch/ipo_pulse_P2_trade_log.csv",
    "hk_ipo_postlisting_drift_c1":     "hk_ipo_batch/ipo_pulse_C1_trade_log.csv",
    "hk_ipo_day1_green_momentum_v1":   "hk_ipo_batch/ipo_day1_green_V1_trade_log.csv",
    # 2026-09-22 (t_24bc8fa6): replaced batch10 trade log with the verified
    # portfolio curve from t_8f944a6a (art +0.8158 == DB exact).
    "hk_stk_52wh_mom_04":              "monthly_returns_unblock_2026-09-22/hk_stk_52wh_mom_04_curve.csv",
    "sg_stk_52wh_mom_13":              "batch11_2026-08-05/sg_stk_52wh_mom_13_trade_log.csv",
    "cn_stk_lowvol_12":                "batch11_2026-08-05/cn_stk_lowvol_12_trade_log.csv",
    "etf_tsmom_basket_07":             "batch10_2026-08-05/etf_tsmom_basket_07_v3_trade_log.csv",
    "etf_comm_trend_basket_15":        "batch12_2026-08-05/etf_comm_trend_basket_15_trade_log.csv",
    "etf_def_sector_rot_12_w":         "batch11_2026-08-05/etf_def_sector_rot_12_w_trade_log.csv",
    "crisis_safe_haven_vt_19":         "batch13_2026-08-06/crisis_safe_haven_vt_19_v2_trade_log.csv",
    "us_stk_lowbeta_14":               "batch11_2026-08-05/us_stk_lowbeta_14_trade_log.csv",
    # 2026-09-22 (t_24bc8fa6): re-based run bf42f373 + registry 0.3764->0.2530;
    # old batch10 trade log no longer matches the canonical run. Verified
    # portfolio curve from t_8f944a6a.
    "us_stk_sue_mom_01_v2":            "monthly_returns_unblock_2026-09-22/us_stk_sue_mom_01_v2_curve.csv",
    "COMM_GoldSilver_Ratio_MeanRev_VolTarget":
        "fx_comm_2026-07-31/COMM_GoldSilver_Ratio_MeanRev_VolTarget_vt10_ze2.0_trade_log_oos.csv",
    "gc_cot_contrarian_inverse":       "expansion_2026-07-30/gc_cot_contrarian_inverse_expanded_trade_log.csv",
    "US_STK_MOM_LDR_01":               "expansion_2026-07-30/US_STK_MOM_LDR_01_expanded_trade_log.csv",
    "US_STK_DEF_MOM_10":               "expansion_2026-07-30/US_STK_DEF_MOM_10_expanded_trade_log.csv",
    "US_STK_QUAL_ROE_07":              "expansion_2026-07-30/US_STK_QUAL_ROE_07_expanded_trade_log.csv",
    "US_STK_SM_CAP_CRED_08":           "expansion_2026-07-30/US_STK_SM_CAP_CRED_08_expanded_trade_log.csv",
    "US_STK_GOLD_HDG_05":              "expansion_2026-07-30/US_STK_GOLD_HDG_05_expanded_trade_log.csv",
    "US_STK_LOWVOL_DIV_02":            "expansion_2026-07-30/US_STK_LOWVOL_DIV_02_expanded_trade_log.csv",
    "ETF_HY_Credit_Carry":             "expansion_2026-07-30/ETF_HY_Credit_Carry_expanded_trade_log.csv",
    "ETF_Defensive_Equity_Income":     "expansion_2026-07-30/ETF_Defensive_Equity_Income_expanded_trade_log.csv",
    "ETF_Dividend_Aristocrats_Treasury_Barbell":
        "expansion_2026-07-30/ETF_Dividend_Aristocrats_Treasury_Barbell_expanded_trade_log.csv",
    "ETF_REIT_Dividend_Momentum":      "expansion_2026-07-30/ETF_REIT_Dividend_Momentum_expanded_trade_log.csv",
    "ETF_Small_Cap_Momentum":          "expansion_2026-07-30/ETF_Small_Cap_Momentum_expanded_trade_log.csv",
    "ETF_HK_Balanced_Trend":           "expansion_2026-07-30/ETF_HK_Balanced_Trend_expanded_trade_log.csv",
    "COMM_Copper_Trend_VolTarget":
        "gapdaily_2026-08-18/postbackfill_rerun/COMM_Copper_Trend_VolTarget_lb126_vt10_trade_log.csv",
    "COMM_Gold_Trend_VolTarget":
        "gapdaily_2026-08-18/postbackfill_rerun/COMM_Gold_Trend_VolTarget_lb63_vt10_trade_log.csv",
    "HK_LowVol_TrendFilter_Weekly":    "HK_LowVol_TrendFilter_Weekly_trade_log.csv",
    "HK_LowVol_Weekly":                "HK_LowVol_Weekly_trade_log.csv",
    # 2026-09-22 additions (t_24bc8fa6 / research t_8f944a6a): all 18
    # verified PUBLISHABLE by the research-side gate mirror
    # (verify_candidate.py, roos tol 0.005, annual tol 0.01) against the
    # canonical run in gold.strategy_backtest_runs. Curves live in
    # monthly_returns_unblock_2026-09-22/{sid}_curve.csv (date,portfolio_value).
    # Re-based strategies (mom12m CAGR-units, SectorRel bar-past-oos_end,
    # MATA/sue/SECTOR_PAIR data drift, AI_SOXX/VAL_REV/H2 re-based to
    # canonical engines, pead_short/vix_carry NULL returns_oos filled from
    # concurrency-1 recon) had run + registry corrected upstream.
    # hk_stk_52wh_mom_04 / us_stk_sue_mom_01_v2 REPLACE their old batch10
    # trade-log paths above with the verified portfolio curves.
    "etf_country_rot_10_v2":
        "monthly_returns_unblock_2026-09-22/etf_country_rot_10_v2_curve.csv",
    "etf_tech_mom_13":
        "monthly_returns_unblock_2026-09-22/etf_tech_mom_13_curve.csv",
    "etf_vix_scaled_11":
        "monthly_returns_unblock_2026-09-22/etf_vix_scaled_11_curve.csv",
    "US_STK_CRED_CYC_04":
        "monthly_returns_unblock_2026-09-22/US_STK_CRED_CYC_04_curve.csv",
    "ETF_Global_Risk_Parity_VolTarget":
        "monthly_returns_unblock_2026-09-22/ETF_Global_Risk_Parity_VolTarget_curve.csv",
    "etf_trend_overlay_mom12m_v1":
        "monthly_returns_unblock_2026-09-22/etf_trend_overlay_mom12m_v1_curve.csv",
    "ETF_US_Sector_Relative_Momentum":
        "monthly_returns_unblock_2026-09-22/ETF_US_Sector_Relative_Momentum_curve.csv",
    "ETF_Multi_Asset_Tactical_Allocation":
        "monthly_returns_unblock_2026-09-22/ETF_Multi_Asset_Tactical_Allocation_curve.csv",
    "ETF_Covered_Call_Income_Rotation":
        "monthly_returns_unblock_2026-09-22/ETF_Covered_Call_Income_Rotation_curve.csv",
    "pead_short_negative_surprise":
        "monthly_returns_unblock_2026-09-22/pead_short_negative_surprise_curve.csv",
    "vix_carry_long_equity":
        "monthly_returns_unblock_2026-09-22/vix_carry_long_equity_curve.csv",
    "US_STK_SECTOR_PAIR_09":
        "monthly_returns_unblock_2026-09-22/US_STK_SECTOR_PAIR_09_curve.csv",
    "US_STK_AI_SOXX_06":
        "monthly_returns_unblock_2026-09-22/US_STK_AI_SOXX_06_curve.csv",
    "US_STK_VAL_REV_03":
        "monthly_returns_unblock_2026-09-22/US_STK_VAL_REV_03_curve.csv",
    "HK_Quality_BlueChips":
        "monthly_returns_unblock_2026-09-22/HK_Quality_BlueChips_curve.csv",
    "H2_QQQ_TECH_MOM_V1":
        "monthly_returns_unblock_2026-09-22/H2_QQQ_TECH_MOM_V1_curve.csv",
}

# Single-position (max concurrency 1) full-capital books with no curve
# artifact; the trade log IS the book. Verified by the same roos gate.
TRADES_RECON_SOURCES = [
    "S9_MACD_Momentum_V2",
    "H3_VIX_TAIL_HEDGE_V1",
    "S14_OIL_SQUEEZE_DISC_V1",
]


def get_dsn():
    dsn = os.environ.get("OPENCLAW_DATABASE_URL")
    if not dsn:
        raise RuntimeError("OPENCLAW_DATABASE_URL not set in /home/ubuntu/.env")
    if dsn.endswith("/airtrading"):
        dsn = dsn.replace("/airtrading", "/aitrading")
    return dsn


def latest_runs(cur):
    # Canonical run per strategy. Multi-variant grids (e.g. the COMM_*
    # lb63/lb126 x vt10/vt15 batches) insert several runs with identical
    # created_at, so created_at alone is non-deterministic. The deployed
    # variant is the one mirrored in gold.strategy_registry.returns_oos
    # (t_fdfdf106): prefer the run matching it, then latest by
    # (created_at, run_number).
    cur.execute("""
        WITH ranked AS (
            SELECT r.strategy_id, r.run_id, r.returns_oos, r.oos_start, r.oos_end,
                   r.annual_pnl_2024, r.annual_pnl_2025, r.annual_pnl_2026,
                   ROW_NUMBER() OVER (
                       PARTITION BY r.strategy_id
                       ORDER BY CASE WHEN reg.returns_oos IS NOT NULL
                                           AND r.returns_oos IS NOT NULL
                                           AND ABS(r.returns_oos - reg.returns_oos) < 0.000001
                                     THEN 0 ELSE 1 END,
                                r.created_at DESC, r.run_number DESC
                   ) rn
            FROM gold.strategy_backtest_runs r
            LEFT JOIN gold.strategy_registry reg
                   ON reg.strategy_id = r.strategy_id)
        SELECT strategy_id, run_id, returns_oos, oos_start, oos_end,
               annual_pnl_2024, annual_pnl_2025, annual_pnl_2026
        FROM ranked WHERE rn = 1
    """)
    out = {}
    for sid, run_id, roos, oos_s, oos_e, a24, a25, a26 in cur.fetchall():
        out[sid] = {
            "run_id": run_id,
            "roos": None if roos is None else float(roos),
            "oos_start": oos_s,
            "oos_end": oos_e,
            "annuals": {2024: a24, 2025: a25, 2026: a26},
        }
    return out


def trades_sum_gate(cur):
    """Strategies whose DB annuals are research-approved book annuals
    (trades_sum_is_book_annual_return=false) must ALSO match annuals."""
    cur.execute("""
        SELECT strategy_id FROM gold.strategy_configs
        WHERE config_key = 'trades_sum_is_book_annual_return'
          AND config_value = 'false'::jsonb
    """)
    return {r[0] for r in cur.fetchall()}


def load_curve_daily_returns(path, oos_start, oos_end):
    """Daily portfolio returns from an equity-curve artifact, sliced to the
    OOS window. Uses portfolio_value pct_change: the first row's
    period_return is pre-baseline and must not be compounded."""
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    pv = pd.to_numeric(df["portfolio_value"], errors="coerce").dropna()
    if oos_start is not None and oos_end is not None:
        w = pv[(pv.index >= pd.Timestamp(oos_start)) & (pv.index <= pd.Timestamp(oos_end))]
        if len(w) >= 5:
            pv = w
    r = pv.pct_change().dropna()
    return r


def compound_by_month(daily):
    monthly = (1 + daily).groupby([daily.index.year, daily.index.month]).prod() - 1
    return [(int(y), int(m), float(v)) for (y, m), v in monthly.items()]


def annual_compounds(daily):
    ann = (1 + daily).groupby(daily.index.year).prod() - 1
    return {int(k): float(v) for k, v in ann.items()}


def verify_window(daily, roos):
    if roos is None or len(daily) < 5:
        return None
    return float((1 + daily).prod() - 1)


def check_annuals(daily, db_annuals):
    parts = []
    art = annual_compounds(daily)
    for yr in (2024, 2025, 2026):
        b = db_annuals.get(yr)
        if b is None:
            continue
        a = art.get(yr)
        if a is None or abs(a - float(b)) > ANNUAL_TOL:
            parts.append(f"{yr}: db={float(b):+.4f} art={'MISSING' if a is None else f'{a:+.4f}'}")
    return parts


def recon_from_trades(cur, sid, oos_start, oos_end):
    """Daily-less reconstruction for max-concurrency-1 books: monthly return
    compounds the per-trade pnl_pct of trades closed in that month."""
    cur.execute("""
        SELECT exit_date, pnl_pct FROM gold.strategy_backtest_trades
        WHERE strategy_id = %s AND exit_date IS NOT NULL AND pnl_pct IS NOT NULL
          AND pnl_pct NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
          AND exit_date >= %s AND exit_date <= %s
        ORDER BY exit_date
    """, (sid, oos_start, oos_end))
    rows = cur.fetchall()
    if len(rows) < 2:
        return None, None
    by_month = {}
    total = 1.0
    for exit_date, pnl in rows:
        pnl = float(pnl)
        total *= (1 + pnl)
        key = (exit_date.year, exit_date.month)
        by_month[key] = by_month.get(key, 1.0) * (1 + pnl)
    monthly = [(y, m, v - 1.0) for (y, m), v in sorted(by_month.items())]
    return monthly, total - 1.0


def max_concurrency(cur, sid):
    cur.execute("""
        WITH ev AS (
            SELECT entry_date d, 1 delta FROM gold.strategy_backtest_trades
            WHERE strategy_id = %s AND entry_date IS NOT NULL
            UNION ALL
            SELECT exit_date d, -1 FROM gold.strategy_backtest_trades
            WHERE strategy_id = %s AND exit_date IS NOT NULL
        ),
        s AS (
            SELECT d, SUM(SUM(delta)) OVER (ORDER BY d) conc FROM ev GROUP BY d
        )
        SELECT MAX(conc) FROM s
    """, (sid, sid))
    return cur.fetchone()[0]


def main():
    conn = psycopg2.connect(get_dsn())
    conn.autocommit = False
    cur = conn.cursor()

    runs = latest_runs(cur)
    gated = trades_sum_gate(cur)

    published = {}   # sid -> (monthly_rows, source, artifact, window_return, run_id)
    rejected = []

    for sid, rel in CURVE_SOURCES.items():
        run = runs.get(sid)
        path = os.path.join(RESEARCH_WS, rel)
        if not run or run["roos"] is None:
            rejected.append((sid, "no strategy_backtest_runs row / returns_oos"))
            continue
        if not os.path.exists(path):
            rejected.append((sid, f"artifact missing: {rel}"))
            continue
        daily = load_curve_daily_returns(path, run["oos_start"], run["oos_end"])
        win = verify_window(daily, run["roos"])
        if win is None or abs(win - run["roos"]) > ROOS_TOL:
            rejected.append((sid, f"roos gate: art={win} db={run['roos']}"))
            continue
        if sid in gated:
            bad = check_annuals(daily, run["annuals"])
            if bad:
                rejected.append((sid, "annual gate: " + " ".join(bad)))
                continue
        published[sid] = (compound_by_month(daily), "research_curve", rel, win, run["run_id"])

    for sid in TRADES_RECON_SOURCES:
        run = runs.get(sid)
        if not run or run["roos"] is None:
            rejected.append((sid, "no strategy_backtest_runs row / returns_oos"))
            continue
        mc = max_concurrency(cur, sid)
        if mc != 1:
            rejected.append((sid, f"trades recon requires max_concurrency=1, got {mc}"))
            continue
        monthly, win = recon_from_trades(cur, sid, run["oos_start"], run["oos_end"])
        if monthly is None or abs(win - run["roos"]) > ROOS_TOL:
            rejected.append((sid, f"roos gate: recon={win} db={run['roos']}"))
            continue
        published[sid] = (monthly, "trades_recon_single_position", None, win, run["run_id"])

    # Full deterministic rebuild
    cur.execute("DELETE FROM gold.strategy_backtest_monthly_returns")
    n = 0
    for sid, (rows, source, artifact, win, run_id) in sorted(published.items()):
        for y, m, r in rows:
            cur.execute("""
                INSERT INTO gold.strategy_backtest_monthly_returns
                    (strategy_id, year, month, return_pct, source, artifact,
                     window_return, run_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (sid, y, m, round(r, 10), source, artifact, round(win, 6), run_id))
            n += 1
        logger.info("PUBLISHED %-40s %3d months  src=%s  window=%+.4f",
                    sid, len(rows), source, win)
    conn.commit()

    logger.info("Total: %d rows across %d strategies", n, len(published))
    for sid, why in rejected:
        logger.warning("REJECTED %s: %s", sid, why)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
