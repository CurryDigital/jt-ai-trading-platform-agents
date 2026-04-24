# USER.md - Operator

_Fill this in during the first conversation (BOOTSTRAP step 3)._

- **Name:** Jacky
- **Timezone:** _(affects how ETL Manager phrases time references — e.g. "02:00 UTC = 10:00 your time")_
- **Preferred channel:** Telegram
- **Handle / contact ID:** @jac128t (ID: 7852335377)

## Alert preferences

- Source failures: _(yes / no — default: yes — always recommended)_
- Partial refreshes: _(yes / no — default: yes)_
- Successful refreshes: _(yes / no — default: no, silent is fine)_
- Abnormal lock warnings: _(yes / no — default: yes)_

## Active sources

_Mark which sources are enabled and have credentials configured:_

- [x] yfinance (no credentials needed)
- [x] FMP — `FMP_API_KEY` set
- [x] Binance — `BINANCE_API_KEY` + `BINANCE_SECRET` set
- [ ] Coinbase — `COINBASE_API_KEY` + `COINBASE_SECRET` set
- [x] IBKR — `IBKR_HOST` + `IBKR_PORT` + `IBKR_CLIENT_ID` set
- [ ] HKEX (no credentials needed)
- [ ] Manual loads (ad hoc)

## Notes

_(Any source-specific instructions, known data gaps, or operator preferences to remember)_