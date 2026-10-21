# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""Gold promotion: bronze.ibkr_account_summary → gold.ibkr_account_summary (refresh)"""
import os
import sys
from datetime import datetime, timezone

# Use the canonical pooled connection. db.py is on PYTHONPATH when invoked
# via daily_refresh.sh; the explicit sys.path insert below makes the script
# also runnable directly for ops.
HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(HERE, '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)

from db import get_connection

# Back-compat alias for the rest of this file.
get_conn = get_connection

def promote_ibkr_account_summary():
    """Refresh gold.ibkr_account_summary from bronze (currency-labeled, t_65d96f4a)"""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT account, net_liquidation, cash_hkd, cash_usd,
               available_funds, buying_power, position_count, fetched_at,
               base_currency, net_liquidation_usd, available_funds_usd,
               buying_power_usd, cash_total_usd, fx_rate, fx_date
        FROM bronze.ibkr_account_summary
        WHERE fetched_at = (SELECT MAX(fetched_at) FROM bronze.ibkr_account_summary)
    """)
    row = cur.fetchone()
    if not row:
        print("No bronze data found")
        conn.close()
        return 0

    (account, net_liq, cash_hkd, cash_usd, avail, bp, pos_count, fetched_at,
     base_ccy, net_liq_usd, avail_usd, bp_usd, cash_total_usd,
     fx_rate, fx_date) = row

    try:
        cur.execute("""
            INSERT INTO gold.ibkr_account_summary
                (account, net_liquidation, cash_hkd, cash_usd, available_funds,
                 buying_power, position_count, fetched_at,
                 base_currency, net_liquidation_usd, available_funds_usd,
                 buying_power_usd, cash_total_usd, fx_rate, fx_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                fetched_at = EXCLUDED.fetched_at
        """, (account, net_liq, cash_hkd, cash_usd, avail, bp, pos_count, fetched_at,
              base_ccy, net_liq_usd, avail_usd, bp_usd, cash_total_usd,
              fx_rate, fx_date))
        conn.commit()
        print(f"gold.ibkr_account_summary: upserted for account {account} "
              f"({base_ccy} {net_liq} = USD {net_liq_usd})")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
        return 0
    finally:
        conn.close()

def promote_portfolio_snapshots():
    """Create portfolio snapshot from bronze positions + account summary.

    t_65d96f4a: values are currency-labeled. Native columns hold the account
    base currency (HKD for DUP825942); *_usd columns are converted via the
    shared fx layer (gold.fx_rates). var_95 is computed on BOTH the native and
    the USD value (same ratio, explicit units).
    """
    import fx  # shared conversion layer
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT account, net_liquidation, cash_hkd, cash_usd, fetched_at,
               base_currency, cash_total_usd, net_liquidation_usd, fx_rate, fx_date
        FROM bronze.ibkr_account_summary
        WHERE fetched_at = (SELECT MAX(fetched_at) FROM bronze.ibkr_account_summary)
    """)
    account_row = cur.fetchone()
    if not account_row:
        print("No account summary data")
        conn.close()
        return 0

    (account, net_liq, cash_hkd, cash_usd, fetched_at,
     base_ccy, cash_total_usd, net_liq_usd, fx_rate, fx_date) = account_row
    base_ccy = base_ccy or 'HKD'

    cur.execute("""
        SELECT ticker, quantity, market_price, market_value, unrealized_pnl, currency
        FROM bronze.ibkr_positions_live
        WHERE fetched_at = (SELECT MAX(fetched_at) FROM bronze.ibkr_positions_live)
    """)
    positions = cur.fetchall()

    total_value = float(net_liq) if net_liq else 0
    # native (base-ccy) cash: cash_hkd + cash_usd converted through the layer
    cash_hkd_f = float(cash_hkd) if cash_hkd else 0
    cash_usd_f = float(cash_usd) if cash_usd else 0
    if base_ccy == 'HKD':
        cash_usd_native, rate_u2b, fx_date2 = fx.convert(cur, cash_usd_f, 'USD', base_ccy)
    else:
        cash_hkd_native, rate_u2b, fx_date2 = fx.convert(cur, cash_hkd_f, 'HKD', base_ccy)
        cash_usd_native = cash_usd_f
        cash_hkd_f = cash_hkd_native
    cash_value = cash_hkd_f + cash_usd_native
    # USD mirrors: prefer the ingested values; recompute only if missing
    if cash_total_usd is None or net_liq_usd is None:
        total_value_usd, fx_rate, fx_date = fx.to_usd(cur, total_value, base_ccy)
        cash_value_usd, _, _ = fx.to_usd(cur, cash_value, base_ccy)
    else:
        total_value_usd = float(net_liq_usd)
        cash_value_usd = float(cash_total_usd)
    positions_value = total_value - cash_value            # native ccy
    positions_value_usd = total_value_usd - cash_value_usd
    total_pnl = sum(float(p[4]) if p[4] else 0 for p in positions)  # USD (contract ccy)
    # exposures from position market values (USD contract ccy for the US book)
    gross_exp_usd = sum(abs(float(p[3])) for p in positions if p[3])
    net_exp_usd = sum(float(p[3]) for p in positions if p[3])

    volatility = 0.15
    var_95 = total_value * volatility * 1.645             # native ccy
    var_95_usd = total_value_usd * volatility * 1.645     # USD (t_65d96f4a: was HKD in a USD-assumed column)

    try:
        cur.execute("""
            INSERT INTO gold.portfolio_snapshots
                (snapshot_date, portfolio_type, total_value, cash_value, positions_value,
                 daily_pnl, daily_pnl_pct, mtd_pnl, ytd_pnl, total_pnl,
                 gross_exposure, net_exposure, beta_adjusted_exposure, var_95,
                 currency, total_value_usd, cash_value_usd, positions_value_usd,
                 gross_exposure_usd, net_exposure_usd, var_95_usd,
                 fx_rate, fx_date, calculated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (snapshot_date, portfolio_type) DO UPDATE SET
                total_value = EXCLUDED.total_value,
                cash_value = EXCLUDED.cash_value,
                positions_value = EXCLUDED.positions_value,
                daily_pnl = EXCLUDED.daily_pnl,
                total_pnl = EXCLUDED.total_pnl,
                var_95 = EXCLUDED.var_95,
                currency = EXCLUDED.currency,
                total_value_usd = EXCLUDED.total_value_usd,
                cash_value_usd = EXCLUDED.cash_value_usd,
                positions_value_usd = EXCLUDED.positions_value_usd,
                gross_exposure_usd = EXCLUDED.gross_exposure_usd,
                net_exposure_usd = EXCLUDED.net_exposure_usd,
                var_95_usd = EXCLUDED.var_95_usd,
                fx_rate = EXCLUDED.fx_rate,
                fx_date = EXCLUDED.fx_date,
                calculated_at = NOW()
        """, (
            fetched_at.date() if fetched_at else datetime.now(timezone.utc).date(),
            account,
            total_value,
            cash_value,
            positions_value,
            0,  # daily_pnl
            0,  # daily_pnl_pct
            0,  # mtd_pnl
            0,  # ytd_pnl
            total_pnl,
            gross_exp_usd,   # gross_exposure (USD contract ccy)
            net_exp_usd,     # net_exposure (USD)
            net_exp_usd,     # beta_adjusted_exposure (USD)
            var_95,
            base_ccy,
            total_value_usd,
            cash_value_usd,
            positions_value_usd,
            gross_exp_usd,   # gross_exposure_usd
            net_exp_usd,     # net_exposure_usd
            var_95_usd,
            fx_rate,
            fx_date,
        ))
        conn.commit()
        print(f"gold.portfolio_snapshots: upserted for {account} "
              f"({base_ccy} {total_value:.2f} = USD {total_value_usd:.2f}, "
              f"var_95_usd={var_95_usd:.2f})")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
        return 0
    finally:
        conn.close()

if __name__ == "__main__":
    promote_ibkr_account_summary()
    promote_portfolio_snapshots()
