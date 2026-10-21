# Decision: Unified lot convention for the paper ledger (US = whole shares)

**Date:** 2026-08-17
**Context:** `qr_etl` task t_928a4e7d (findings memo 2026-08-17 §1.1/1.2)
**Decision owner:** ETL Manager

## Problem
Three writers of `gold.paper_trades_synthetic` used two different lot
conventions:

1. `gold/strategy/rebuild_paper_positions.py` — `lot_size_for()` hardcoded
   **100-share** lots for US bare symbols (feasibility check + sizer).
2. `gold/strategy/refresh_paper_trades_synthetic.py` — SQL sizer also floored
   US to **100-share** lots (since the 2026-07-29 fix).
3. `gold/strategy/backfill_paper_trades_from_history.py` — the batch10 ingest
   path — sized `floor(notional/price)` with **no lot rounding** (lot = 1).

Result: the `etf_tsmom_basket_07` OPEN book (written 2026-08-05 via path 3)
holds odd lots (EEM 213, EFA 274, HYG 419, IEF 357, LQD 312, VNQ 319,
DBC 838) that the rebalancer grandfathers forever ("does nothing for a held
ticker"), while every NEW entry was judged against the 100-share rule.
Concrete damage: GLD 51sh / SPY 41sh entered 08-05, were closed 08-06 by the
pre-t_84d61124 rebalancer (BUY unsized at 100-share lots), and BELOW_ONE_LOT
skips fired every day 08-05..08-14 — SPY (~$778/sh → $77.8K/lot > $31.8K
slot) could never re-enter, so tsmom could not hold its core equity leg and
US Sector's SPY-defined regime filter had no SPY in the book.

No code comment, config, or registry row recorded the 100-share rule as a
deliberate platform policy; `silver.asset_registry.lot_size` is NULL for all
1,156 rows (US/SI/HK/FUT), so the hardcoded fallback was the only convention
in force.

## Decision
**US-listed equities/ETFs (bare symbols) size in WHOLE SHARES — lot = 1.**
The 100-share round-lot rule is retired.

Rationale:
- IBKR — the execution venue this paper engine mirrors — supports fractional
  US shares; a 1-share minimum is conservative-realistic, not optimistic.
- The strategy designs' slot math (weight × assigned capital) assumes
  share-level granularity; the 100-share floor silently vetoed high-priced
  core legs (SPY, AVGO, CIEN) and redistributed their slots, distorting the
  book away from the approved designs.
- One convention in feasibility check AND sizer removes the
  three-writers/two-conventions split.

Rejected alternative:
- **Keep 100-share lots as a deliberate rule** — no record of it ever being
  deliberate; it contradicts the approved strategy slot math and IBKR
  reality. Would also require rounding down (or cash-parking) every existing
  odd-lot row, realizing turnover the strategies never signalled.

## Convention now in force (both engine files, registry-first)
| Instrument | Lot | Source |
|---|---|---|
| US bare symbols | 1 | code default; `silver.asset_registry.lot_size` overrides when populated |
| `.HK` | board lot | `silver.asset_registry.lot_size`, fallback 1 (registry currently unpopulated — separate defect) |
| `.SI` | 100 | SGX board lot since 2015; registry override when populated |
| `=` futures | 1 | not lot-rounded (no contract multiplier in paper ledger) |

## Migration of existing rows
- **tsmom grandfathered odd lots (7 open rows): NO share-count change.**
  Under lot = 1 they are conformant as-is. The rebalancer never resizes held
  positions, so they persist until their tickers drop out of the BUY set.
  Rewriting them to 100-share multiples would fabricate trades the strategy
  never signalled.
- **GLD/SPY legs (closed 08-06 by the pre-fix rebalancer): re-opened by the
  engine, not by hand.** A scoped `rebuild_paper_positions.py
  --strategy-id etf_tsmom_basket_07` run re-enters them at the latest
  available close with correct whole-share sizing — same mechanics and price
  basis as any daily cycle entry. Backdating fills to 08-05 prices was
  rejected: it would fabricate fills. The 08-05→08-06 churn round-trips
  (GLD +789.48, SPY -63.14) remain in the closed ledger as historical fact
  (their contamination of WR/PF is tracked separately under memo §2.3).

## Implementation
1. `rebuild_paper_positions.py` `lot_size_for()`: US fallback 100 → 1,
   explicit `.SI` → 100 branch, registry-first for all share classes.
2. `refresh_paper_trades_synthetic.py`: both SQL sizers (closed + open
   inserts) — `ELSE 100` → `ELSE COALESCE(NULLIF(ar.lot_size,0), 1)`, plus
   explicit `%.SI` → 100 branch (preserves SGX board-lot status quo).
3. `backfill_paper_trades_from_history.py`: already lot = 1; comment added
   tying it to this decision.
4. Scoped rebuild run 2026-08-17 re-opened SPY/GLD in the tsmom book.

## Downstream impact
- BELOW_ONE_LOT now fires only when a slot cannot afford ONE share
  (effectively never for US ETFs at current capital levels); it remains
  meaningful for HK board lots once the registry is populated.
- New US entries are whole-share exact vs slot notional; residual cash per
  slot drops to < 1 share price.
- `gold.paper_trade_skip_log` rows with lot_size=100 for US tickers
  (through 2026-08-14) are historical and should not be compared against
  post-decision rows.
- Out of scope, flagged: `.HK` registry board lots are unpopulated (HK books
  also hold odd lots) and `sg_stk_52wh_mom_13` holds lots that are multiples
  of 50, not 100 — both grandfathered; separate tickets if they are to be
  enforced.

## Verification
- Scoped rebuild output: SPY/GLD opened at latest close, whole shares;
  zero BELOW_ONE_LOT skips for tsmom on the run.
- Post-run `gold.paper_trades_synthetic` spot check: 9 open tsmom rows,
  SPY + GLD present.
