# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Gold Portfolio: Live Positions & Portfolio Snapshots
Reads from: bronze.ibkr_positions_live, gold.paper_strategies,
            gold.strategy_ticker_scores
Writes to:  gold.ibkr_positions_live, gold.portfolio_snapshots
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date

SQL_SYNC_POSITIONS = """
INSERT INTO gold.ibkr_positions_live
  (account, ticker, quantity, avg_cost, market_price, market_value,
   unrealized_pnl, unrealized_pnl_pct, side, asset_class, currency, fetched_at)
SELECT
  account,
  -- Normalise ticker (strip exchange suffix if present)
  SPLIT_PART(ticker, '.', 1) AS ticker,
  quantity,
  avg_cost,
  market_price,
  market_value,
  unrealized_pnl,
  unrealized_pnl_pct,
  CASE WHEN quantity > 0 THEN 'LONG' ELSE 'SHORT' END AS side,
  asset_class,
  currency,
  fetched_at
FROM bronze.ibkr_positions_live
ON CONFLICT (account, ticker) DO UPDATE SET
  quantity          = EXCLUDED.quantity,
  avg_cost          = EXCLUDED.avg_cost,
  market_price      = EXCLUDED.market_price,
  market_value      = EXCLUDED.market_value,
  unrealized_pnl    = EXCLUDED.unrealized_pnl,
  unrealized_pnl_pct = EXCLUDED.unrealized_pnl_pct,
  side              = EXCLUDED.side,
  asset_class       = EXCLUDED.asset_class,
  currency          = EXCLUDED.currency,
  fetched_at        = EXCLUDED.fetched_at;
"""

# t_65d96f4a: native columns carry the account base currency (HKD for
# DUP825942); *_usd columns are converted via shared/scripts/fx.py
# (gold.fx_rates). gross/net exposure and daily_pnl are contract-currency
# (USD for the US book) and are mirrored into *_usd with that made explicit.
SQL_SNAPSHOT_NATIVE = """
SELECT net_liquidation, COALESCE(cash_hkd, 0), COALESCE(cash_usd, 0),
       COALESCE(base_currency, 'HKD')
FROM gold.ibkr_account_summary
ORDER BY fetched_at DESC
LIMIT 1
"""

SQL_SNAPSHOT_POSITIONS = """
SELECT COALESCE(SUM(unrealized_pnl), 0) AS daily_pnl,
       COALESCE(SUM(ABS(market_value)), 0) AS gross_exposure,
       COALESCE(SUM(CASE WHEN side = 'SHORT' THEN -ABS(market_value) ELSE market_value END), 0) AS net_exposure
FROM gold.ibkr_positions_live
"""

SQL_SNAPSHOT_INSERT = """
INSERT INTO gold.portfolio_snapshots
  (snapshot_date, portfolio_type,
   total_value, cash_value, positions_value,
   daily_pnl, daily_pnl_pct,
   gross_exposure, net_exposure,
   currency, total_value_usd, cash_value_usd, positions_value_usd,
   gross_exposure_usd, net_exposure_usd, fx_rate, fx_date,
   calculated_at)
VALUES (%s, 'live', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
ON CONFLICT (snapshot_date, portfolio_type) DO UPDATE SET
  total_value       = EXCLUDED.total_value,
  cash_value        = EXCLUDED.cash_value,
  positions_value   = EXCLUDED.positions_value,
  daily_pnl         = EXCLUDED.daily_pnl,
  daily_pnl_pct     = EXCLUDED.daily_pnl_pct,
  gross_exposure    = EXCLUDED.gross_exposure,
  net_exposure      = EXCLUDED.net_exposure,
  currency          = EXCLUDED.currency,
  total_value_usd   = EXCLUDED.total_value_usd,
  cash_value_usd    = EXCLUDED.cash_value_usd,
  positions_value_usd = EXCLUDED.positions_value_usd,
  gross_exposure_usd = EXCLUDED.gross_exposure_usd,
  net_exposure_usd  = EXCLUDED.net_exposure_usd,
  fx_rate           = EXCLUDED.fx_rate,
  fx_date           = EXCLUDED.fx_date,
  calculated_at     = NOW();
"""


def write_snapshot(cur):
    import fx  # shared conversion layer — missing/stale rate raises loudly
    cur.execute(SQL_SNAPSHOT_NATIVE)
    row = cur.fetchone()
    if not row:
        print("⚠️  no gold.ibkr_account_summary row — skipping snapshot")
        return 0
    net_liq, cash_hkd, cash_usd, base_ccy = row
    net_liq = float(net_liq or 0)
    cash_hkd = float(cash_hkd)
    cash_usd = float(cash_usd)
    # native (base-ccy) cash via the layer — never raw-summed across ccys
    if base_ccy == 'HKD':
        cash_usd_native, _, _ = fx.convert(cur, cash_usd, 'USD', base_ccy)
        cash_native = cash_hkd + cash_usd_native
    else:
        cash_hkd_native, _, _ = fx.convert(cur, cash_hkd, 'HKD', base_ccy)
        cash_native = cash_hkd_native + cash_usd
    total_usd, rate, fx_date = fx.to_usd(cur, net_liq, base_ccy)
    cash_usd_total, _, _ = fx.to_usd(cur, cash_native, base_ccy)
    positions_value = net_liq - cash_native
    positions_value_usd = total_usd - cash_usd_total

    cur.execute(SQL_SNAPSHOT_POSITIONS)
    pnl_usd, gross_usd, net_usd = cur.fetchone()
    pnl_usd = float(pnl_usd or 0)
    pnl_pct = (pnl_usd / positions_value_usd * 100) if positions_value_usd else 0

    cur.execute(SQL_SNAPSHOT_INSERT, (
        date.today(),
        net_liq, cash_native, positions_value,
        pnl_usd, pnl_pct,
        float(gross_usd or 0), float(net_usd or 0),
        base_ccy, total_usd, cash_usd_total, positions_value_usd,
        float(gross_usd or 0), float(net_usd or 0), rate, fx_date,
    ))
    return cur.rowcount

def run():
    conn = get_connection()
    cur = conn.cursor()
    
    # Check if target table exists
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'gold' AND table_name = 'ibkr_positions_live'
        );
    """)
    has_positions_table = cur.fetchone()[0]
    
    if has_positions_table:
        cur.execute(SQL_SYNC_POSITIONS)
        print(f"✅ gold.ibkr_positions_live synced: {cur.rowcount} rows upserted")
        n = write_snapshot(cur)
        print(f"✅ gold.portfolio_snapshots updated: {n} rows upserted")
    else:
        print("⚠️  gold.ibkr_positions_live does not exist — skipping position sync")

    # Also sync account summary from bronze to gold (currency-labeled, t_65d96f4a)
    cur.execute("""
        INSERT INTO gold.ibkr_account_summary
            (account, net_liquidation, cash_hkd, cash_usd, available_funds, buying_power,
             position_count, fetched_at,
             base_currency, net_liquidation_usd, available_funds_usd,
             buying_power_usd, cash_total_usd, fx_rate, fx_date)
        SELECT account, net_liquidation, cash_hkd, cash_usd, available_funds, buying_power,
               position_count, fetched_at,
               base_currency, net_liquidation_usd, available_funds_usd,
               buying_power_usd, cash_total_usd, fx_rate, fx_date
        FROM bronze.ibkr_account_summary
        ON CONFLICT (account) DO UPDATE SET
            net_liquidation = EXCLUDED.net_liquidation,
            cash_hkd = EXCLUDED.cash_hkd,
            cash_usd = EXCLUDED.cash_usd,
            available_funds = EXCLUDED.available_funds,
            buying_power = EXCLUDED.buying_power,
            position_count = EXCLUDED.position_count,
            base_currency = EXCLUDED.base_currency,
            net_liquidation_usd = EXCLUDED.net_liquidation_usd,
            available_funds_usd = EXCLUDED.available_funds_usd,
            buying_power_usd = EXCLUDED.buying_power_usd,
            cash_total_usd = EXCLUDED.cash_total_usd,
            fx_rate = EXCLUDED.fx_rate,
            fx_date = EXCLUDED.fx_date,
            fetched_at = EXCLUDED.fetched_at;
    """)
    print(f"✅ gold.ibkr_account_summary synced: {cur.rowcount} rows upserted")
    
    # Check if consumption table exists before writing
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'consumption' AND table_name = 'portfolio_positions_current'
        );
    """)
    has_cons_table = cur.fetchone()[0]
    
    if has_cons_table:
        # Previously this script inserted a synthetic HKD cash row into the
        # positions table.  Cash is now reported from gold.ibkr_account_summary
        # via the consumption.account_summary view, so we no longer pollute
        # the positions table with a cash pseudo-position.
        print("✅ Cash position is sourced from gold.ibkr_account_summary; no synthetic position row inserted")
    else:
        print("⚠️  consumption.portfolio_positions_current does not exist — skipping consumption sync")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
