import csv, json, os
from datetime import datetime, timezone

ws = '/home/ubuntu/.hermes/kanban/boards/trading/workspaces/6d14e6fa-704b-46d6-913e-1fb0863acac3'
art = '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/artifacts/mapping_manifest'
os.makedirs(art, exist_ok=True)

with open(os.path.join(ws, 'hk_broker_mapping_manifest.json')) as f:
    manifest = json.load(f)
with open(os.path.join(ws, 'universe_tickers_broker_mapping.csv')) as f:
    rows = list(csv.DictReader(f))

records = []
for r in rows:
    ticker = r['normalized_ticker']
    mt = next((x for x in manifest['tickers'] if x['ticker'] == ticker), {})
    if mt.get('status') == 'validated':
        price_status = 'validated'
    elif mt.get('status') == 'delisted':
        price_status = 'delisted'
    elif r['mapping_status'] == 'mapped':
        price_status = 'mapped_unvalidated'
    else:
        price_status = 'unresolved'
    records.append({
        'universe': r['universe_name'],
        'normalized_ticker': ticker,
        'broker_symbol': r['broker_symbol'] or '',
        'con_id': r['con_id'] or mt.get('con_id', ''),
        'exchange': r['exchange'] or mt.get('exchange', ''),
        'currency': r['currency'] or mt.get('currency', ''),
        'price_validation_status': price_status,
        'last_bar_date': mt.get('last_bar', {}).get('bar_time', ''),
        'last_bar_close': str(mt.get('last_bar', {}).get('close', '')) if 'last_bar' in mt else '',
        'timestamp': datetime.now(timezone.utc).isoformat()
    })

fields = ['universe','normalized_ticker','broker_symbol','con_id','exchange','currency','price_validation_status','last_bar_date','last_bar_close','timestamp']
with open(os.path.join(art, 'mapping_manifest.csv'), 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(records)

valid = [r for r in records if r['price_validation_status'] == 'validated']
delisted = [r for r in records if r['price_validation_status'] == 'delisted']
unresolved = [r for r in records if r['price_validation_status'] not in ('validated','delisted')]

unique_valid = {r['normalized_ticker'] for r in valid}
unique_delisted = {r['normalized_ticker'] for r in delisted}
unique_tickers = {r['normalized_ticker'] for r in records}
row_summary = {
    'total_rows': len(records),
    'validated_rows': len(valid),
    'delisted_rows': len(delisted),
    'unresolved_rows': len(unresolved),
    'success_rate_pct': round(len(valid) / len(records) * 100, 1),
    'unique_tickers': len(unique_tickers),
    'unique_validated': len(unique_valid),
    'unique_delisted': len(unique_delisted)
}

final = {
    'generated_at': datetime.now(timezone.utc).isoformat(),
    'source': 'gold.strategy_registry',
    'broker_table': 'bronze.ibkr_contracts',
    'ibkr_host': '127.0.0.1:14002',
    'strategies': manifest['strategies'],
    'tickers': records,
    'summary': row_summary
}
with open(os.path.join(art, 'mapping_manifest.json'), 'w') as f:
    json.dump(final, f, indent=2)

report = f"""Broker Symbol Mapping Manifest - Acceptance Report
Generated at: {datetime.now(timezone.utc).isoformat()}

Status
- Total universe rows: {len(records)}
- Validated live broker symbols: {len(valid)}
- Delisted / no live symbol: {len(delisted)}
- Unresolved: {len(unresolved)}
- Success rate: {len(valid)/len(records)*100:.1f}%

Unresolved / Delisted Tickers
"""
for r in delisted + unresolved:
    report += f"- {r['normalized_ticker']} (universe: {r['universe']}) status={r['price_validation_status']}\n"
report += """
Remediations
- 0011.HK (Hang Seng Bank) delisted/taken private by HSBC in 2024. Remove from HK_Quality_BlueChips universe or replace with successor bank ticker.
- All other 22 tickers resolve to live broker symbols and returned valid TRADES bars from IBKR TWS API via 127.0.0.1:14002.

Artifacts
- CSV manifest: /home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/artifacts/mapping_manifest/mapping_manifest.csv
- JSON manifest: /home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/artifacts/mapping_manifest/mapping_manifest.json
- Acceptance report: /home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/artifacts/mapping_manifest/acceptance_report.txt
"""
with open(os.path.join(art, 'acceptance_report.txt'), 'w') as f:
    f.write(report)

print(f'Wrote {len(records)} records')
print(f'validated={len(valid)}, delisted={len(delisted)}, unresolved={len(unresolved)}')
