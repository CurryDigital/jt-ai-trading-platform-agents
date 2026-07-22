#!/usr/bin/env python3
"""Refresh annual_pnl_* columns in gold.strategy_backtest_runs from ETL-owned data
and approved research artifacts.

qr_research supplies the strategies and backtest results. ETL ingests those results
and serves them as the dashboard source of truth via gold.v_pipeline_ui_feed.

Sources (in precedence order per year):
1. gold.strategy_backtest_trades (ETL-owned) — computed by exit year.
2. Approved manifest IS annual_return for a calendar-2024 period.
3. US-STK OOS equity curve calendar-year returns (2024-2026).
4. Approved HK LowVol research backtester re-run to derive calendar-2024 from the
   same IS/OOS period that produced the approved 2025/2026 figures.
5. Approved manifest OOS annual_return as a fallback for 2024 when no calendar-year
   source exists.
6. Audit CSV calendar-year annual_pnl_2025 and annual_pnl_2026.

The script is idempotent and never overwrites a non-NULL ETL-computed value with a
research fallback value.
"""

import csv
import json
import logging
import math
import os
import sys
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared", "scripts"))

from db import get_connection  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Approved research artifacts (read-only inputs to ETL).
MANIFEST_PATH = Path("/home/ubuntu/.hermes/profiles/qr_research/workspace/strategy_handoff_manifest_approved_pipeline_2026-07-17.json")
AUDIT_CSV_PATH = Path("/home/ubuntu/.hermes/profiles/qr_research/workspace/pipeline_full_audit_2026-07-18.csv")
US_STK_EQUITY_CURVE_PATH = Path("/home/ubuntu/.hermes/profiles/qr_research/workspace/us_stock_pipeline_10_oos_equity_curves_2026-07-19.csv")

YEARS = ["2024", "2025", "2026"]

# Map display names in the equity curve header to registry strategy_ids.
US_STK_NAME_TO_ID = {
    "Momentum_Leaders": "US_STK_MOM_LDR_01",
    "LowVol_Dividend_Quality": "US_STK_LOWVOL_DIV_02",
    "Value_Reversion_Rates": "US_STK_VAL_REV_03",
    "Credit_Sensitive_Cyclicals": "US_STK_SM_CAP_CRED_08",
    "Gold_Hedge_Rotation": "US_STK_GOLD_HDG_05",
    "AI_Tactical_SOXX": "US_STK_AI_SOXX_06",
    "Quality_ROE_Momentum": "US_STK_QUAL_ROE_07",
    "Small_Cap_Credit_Spread": "US_STK_SM_CAP_CRED_08",
    "Sector_Pairs_Long": "US_STK_SECTOR_PAIR_09",
    "Defensive_Momentum": "US_STK_DEF_MOM_10",
}


def quantize(value: Optional[Decimal]) -> Optional[Decimal]:
    if value is None:
        return None
    if value.is_nan() or value.is_infinite():
        return None
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def annual_pnl_from_trades(cur, strategy_id: str) -> Dict[str, Optional[Decimal]]:
    cur.execute(
        """
        SELECT EXTRACT(YEAR FROM exit_date) AS yr,
               CASE WHEN SUM(pnl_pct) IS NOT DISTINCT FROM 'NaN'::numeric THEN NULL
                    ELSE SUM(pnl_pct) END AS pnl
        FROM gold.strategy_backtest_trades
        WHERE strategy_id = %s
        GROUP BY EXTRACT(YEAR FROM exit_date)
        ORDER BY yr;
        """,
        (strategy_id,),
    )
    by_year = {str(int(row["yr"])): quantize(row["pnl"]) for row in cur.fetchall()}
    return {year: by_year.get(year) for year in YEARS}


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {}
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def annual_pnl_from_manifest(strategy_id: str, manifest: dict) -> Tuple[Dict[str, Optional[Decimal]], Dict[str, Optional[Decimal]]]:
    """Return (is_2024, oos_annualized) sources from the manifest."""
    pnl_is: Dict[str, Optional[Decimal]] = {year: None for year in YEARS}
    pnl_oos: Dict[str, Optional[Decimal]] = {year: None for year in YEARS}

    for strat in manifest.get("strategies", []):
        if strat.get("strategy_id") != strategy_id:
            continue
        for result in strat.get("backtest_results", []):
            try:
                start = date.fromisoformat(result.get("period_start", ""))
                end = date.fromisoformat(result.get("period_end", ""))
            except ValueError:
                continue
            annual_return = result.get("annual_return")
            if annual_return is None:
                continue
            val = quantize(Decimal(str(annual_return)))

            # Calendar-2024 IS period.
            if start.year == 2024 and end.year == 2024:
                pnl_is["2024"] = val
            # OOS annualized return — use as a 2024 fallback only if the OOS period
            # starts in 2024 and we have no better calendar-year source.
            if not result.get("is_oos", False):
                continue
            if start.year == 2024:
                pnl_oos["2024"] = val
        break
    return pnl_is, pnl_oos


# Set of HK LowVol strategies for which the approved research backtester can
# reproduce a calendar-2024 return from the same IS/OOS period that produced the
# approved 2025/2026 figures.
HK_LOWVOL_BACKTEST_STRATEGIES = {"HK_LowVol_Weekly", "HK_LowVol_TrendFilter_Weekly"}
HK_LOWVOL_BACKTEST_PATH = "/home/ubuntu/.hermes/profiles/qr_research/workspace"


def annual_pnl_from_hk_lowvol_backtest(strategy_id: str) -> Optional[Decimal]:
    """Compute calendar-2024 return by re-running the approved qr_research HK LowVol backtester.

    The backtester reads from /tmp/hk_prices_clean.csv (price cache), so it does not
    require a live DB connection on the standard research port.
    """
    if strategy_id not in HK_LOWVOL_BACKTEST_STRATEGIES:
        return None
    if HK_LOWVOL_BACKTEST_PATH not in sys.path:
        sys.path.insert(0, HK_LOWVOL_BACKTEST_PATH)
    try:
        from hk_backtest import SIGNALS, annual_pnl, backtest, parse_strategy_name  # type: ignore[import-not-found]  # runtime import from qr_research workspace
        rebalance, use_bottom = parse_strategy_name(strategy_id)
        allow_cash = "DualMomentum" in strategy_id
        signal_fn = SIGNALS[strategy_id]
        trade_log = backtest(
            strategy_id,
            signal_fn,
            rebalance=rebalance,
            top_n=5,
            use_bottom=use_bottom,
            allow_cash=allow_cash,
            is_end="2024-12-31",
        )
        val = annual_pnl(trade_log, 2024)
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return None
        return quantize(Decimal(str(val)))
    except Exception as e:
        logger.warning("%s: failed to compute 2024 from hk_backtest: %s", strategy_id, e)
        return None
    finally:
        if HK_LOWVOL_BACKTEST_PATH in sys.path:
            sys.path.remove(HK_LOWVOL_BACKTEST_PATH)


def annual_pnl_from_audit_csv(strategy_id: str) -> Dict[str, Optional[Decimal]]:
    pnl: Dict[str, Optional[Decimal]] = {year: None for year in YEARS}
    if not AUDIT_CSV_PATH.exists():
        return pnl

    with open(AUDIT_CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("strategy_id") != strategy_id:
                continue
            for year in ["2025", "2026"]:
                raw = row.get(f"annual_pnl_{year}")
                if raw:
                    try:
                        pnl[year] = quantize(Decimal(raw.strip()))
                    except Exception:
                        pass
    return pnl


def annual_pnl_from_us_stk_equity_curve() -> Dict[str, Dict[str, Optional[Decimal]]]:
    """Compute calendar-year returns from the US-STK OOS equity curve CSV."""
    result: Dict[str, Dict[str, Optional[Decimal]]] = {}
    if not US_STK_EQUITY_CURVE_PATH.exists():
        return result

    with open(US_STK_EQUITY_CURVE_PATH, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return result

    header = rows[0].keys()
    # First column is date; remaining columns are strategy display names.
    name_cols = [col for col in header if col != "date"]

    for name in name_cols:
        strategy_id = US_STK_NAME_TO_ID.get(name)
        if not strategy_id:
            continue

        # Collect year-end values.
        year_start: Dict[str, Decimal] = {}
        year_end: Dict[str, Decimal] = {}
        for row in rows:
            d = row.get("date", "")
            try:
                dt = date.fromisoformat(d)
            except ValueError:
                continue
            val = Decimal(row[name])
            yr = str(dt.year)
            if yr not in year_start:
                year_start[yr] = val
            year_end[yr] = val

        pnl: Dict[str, Optional[Decimal]] = {year: None for year in YEARS}
        for year in YEARS:
            if year in year_start and year in year_end:
                pnl[year] = quantize((year_end[year] / year_start[year]) - Decimal("1"))
        result[strategy_id] = pnl

    return result


def existing_annual_pnl(cur, strategy_id: str) -> Dict[str, Optional[Decimal]]:
    cur.execute(
        """
        SELECT annual_pnl_2024, annual_pnl_2025, annual_pnl_2026
        FROM gold.strategy_backtest_runs
        WHERE strategy_id = %s
        ORDER BY created_at DESC
        LIMIT 1;
        """,
        (strategy_id,),
    )
    row = cur.fetchone()
    if not row:
        return {year: None for year in YEARS}
    return {
        "2024": quantize(row["annual_pnl_2024"]),
        "2025": quantize(row["annual_pnl_2025"]),
        "2026": quantize(row["annual_pnl_2026"]),
    }


def resolve_annual_pnl(
    strategy_id: str,
    trades: Dict[str, Optional[Decimal]],
    manifest_is: Dict[str, Optional[Decimal]],
    manifest_oos: Dict[str, Optional[Decimal]],
    audit: Dict[str, Optional[Decimal]],
    us_stk: Dict[str, Optional[Decimal]],
    hk_lowvol: Optional[Decimal],
    existing: Dict[str, Optional[Decimal]],
) -> Tuple[Dict[str, Optional[Decimal]], str]:
    """Merge sources by priority."""
    result: Dict[str, Optional[Decimal]] = {}
    sources = []

    for year in YEARS:
        value = None
        source = None

        if trades.get(year) is not None:
            value = trades[year]
            source = "trades"
        elif year == "2024" and manifest_is.get(year) is not None:
            value = manifest_is[year]
            source = "manifest_2024_is"
        elif us_stk.get(year) is not None:
            value = us_stk[year]
            source = "us_stk_equity_curve"
        elif year == "2024" and hk_lowvol is not None:
            value = hk_lowvol
            source = "hk_lowvol_backtest"
        elif year == "2024" and manifest_oos.get(year) is not None:
            value = manifest_oos[year]
            source = "manifest_2024_oos_approx"
        elif audit.get(year) is not None:
            value = audit[year]
            source = "audit_csv"
        elif existing.get(year) is not None:
            value = existing[year]
            source = "existing_db"

        result[year] = value
        if value is not None:
            sources.append(f"{year}={source}")

    return result, ", ".join(sources) if sources else "none"


def main():
    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        manifest = load_manifest()
        us_stk_by_id = annual_pnl_from_us_stk_equity_curve()

        cur.execute(
            """
            SELECT r.strategy_id
            FROM gold.strategy_registry r
            WHERE r.status NOT IN ('DEPRECATED', 'retired')
            ORDER BY r.strategy_id;
            """
        )
        strategy_ids = [row["strategy_id"] for row in cur.fetchall()]
        logger.info("Found %d non-deprecated strategies to refresh", len(strategy_ids))

        updated = 0
        unchanged = 0
        no_source = 0

        for strategy_id in strategy_ids:
            trades = annual_pnl_from_trades(cur, strategy_id)
            manifest_is, manifest_oos = annual_pnl_from_manifest(strategy_id, manifest)
            audit = annual_pnl_from_audit_csv(strategy_id)
            us_stk = us_stk_by_id.get(strategy_id, {year: None for year in YEARS})
            hk_lowvol = annual_pnl_from_hk_lowvol_backtest(strategy_id)
            existing = existing_annual_pnl(cur, strategy_id)

            resolved, source_summary = resolve_annual_pnl(
                strategy_id, trades, manifest_is, manifest_oos, audit, us_stk, hk_lowvol, existing
            )

            def is_nan(v):
                return isinstance(v, Decimal) and v.is_nan()

            needs_update = any(
                (resolved[year] != existing[year] and not (resolved[year] is None and is_nan(existing[year])))
                or (resolved[year] is None and is_nan(existing[year]))
                for year in YEARS
            )
            if not needs_update:
                logger.info("%s: unchanged (sources: %s)", strategy_id, source_summary)
                unchanged += 1
                continue

            cur.execute(
                """
                UPDATE gold.strategy_backtest_runs
                SET annual_pnl_2024 = %s,
                    annual_pnl_2025 = %s,
                    annual_pnl_2026 = %s,
                    notes = COALESCE(notes, '') || ' | annual_pnl refreshed from ETL: '
                            || COALESCE(%s, '') || ' at '
                            || NOW()::text
                WHERE run_id = (
                    SELECT run_id
                    FROM gold.strategy_backtest_runs
                    WHERE strategy_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                );
                """,
                (
                    resolved["2024"],
                    resolved["2025"],
                    resolved["2026"],
                    source_summary,
                    strategy_id,
                ),
            )
            if cur.rowcount == 0:
                logger.warning("%s: no backtest_runs row to update", strategy_id)
                no_source += 1
                continue

            logger.info(
                "%s: updated -> 2024=%s 2025=%s 2026=%s (sources: %s)",
                strategy_id,
                resolved["2024"],
                resolved["2025"],
                resolved["2026"],
                source_summary,
            )
            updated += 1

        conn.commit()
        logger.info("Done. updated=%d unchanged=%d no_source=%d total=%d", updated, unchanged, no_source, len(strategy_ids))

    except Exception as e:
        conn.rollback()
        logger.error("Refresh failed: %s", e)
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
