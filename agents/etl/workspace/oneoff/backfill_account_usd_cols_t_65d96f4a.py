#!/usr/bin/env python3
"""One-off backfill (t_65d96f4a): populate currency/USD columns on the CURRENT
bronze + gold ibkr_account_summary rows via the shared fx layer.

Values are NOT rewritten — native columns stay as-is; we add labels and
converted columns only. Ongoing writes come from ingest_ibkr_tws.py.
"""
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection
import fx

BASE_CCY = 'HKD'
conn = get_connection(); cur = conn.cursor()

for schema in ('bronze', 'gold'):
    cur.execute(f"""
        SELECT account, net_liquidation, COALESCE(cash_hkd,0), COALESCE(cash_usd,0),
               COALESCE(available_funds,0), COALESCE(buying_power,0)
        FROM {schema}.ibkr_account_summary
    """)
    rows = cur.fetchall()
    for account, net_liq, cash_hkd, cash_usd, avail, bp in rows:
        net_liq_usd, rate, fx_date = fx.to_usd(cur, float(net_liq), BASE_CCY)
        avail_usd, _, _ = fx.to_usd(cur, float(avail), BASE_CCY)
        bp_usd, _, _ = fx.to_usd(cur, float(bp), BASE_CCY)
        cash_hkd_usd, _, _ = fx.to_usd(cur, float(cash_hkd), 'HKD')
        cash_total_usd = cash_hkd_usd + float(cash_usd)
        cur.execute(f"""
            UPDATE {schema}.ibkr_account_summary SET
                base_currency = %s,
                net_liquidation_usd = %s,
                available_funds_usd = %s,
                buying_power_usd = %s,
                cash_total_usd = %s,
                fx_rate = %s,
                fx_date = %s
            WHERE account = %s
        """, (BASE_CCY, net_liq_usd, avail_usd, bp_usd, cash_total_usd,
              rate, fx_date, account))
        print(f"{schema}: {account} net_liq {float(net_liq):.2f} {BASE_CCY} = "
              f"{net_liq_usd:.2f} USD @ {rate:.6f} ({fx_date})")
conn.commit()
conn.close()
print('backfill done')
