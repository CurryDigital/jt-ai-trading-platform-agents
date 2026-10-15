#!/usr/bin/env python3
"""
Shared derivatives backtest engine — KAT build (sequencing step 2).

Scope of this build: exactly what the BXM/PUT known-answer test needs,
structured so strategy templates reuse the same primitives later:
- Daily MTM from quoted chains (silver.option_eod_quotes); final-week legs
  marked at intrinsic when quotes are absent (the free-window pull is 7-60
  DTE — see KAT_PLAN.md wedge W6).
- Fill model: fill = mid -/+ f * half_spread (sell at bid when f=1.0).
- IBKR commissions: $0.65/contract, $1.00 minimum per order.
- Roll calendar: standard monthly expiries (3rd Friday; preceding business
  day if that Friday is not listed).
- ATM selection: CALL -> first listed strike >= ref; PUT -> first listed
  strike <= ref (CBOE BXM / PUT conventions, verified 2026-10-02).
- Cash accrues at FRED DTB3 (ACT/360).
- American short legs: for the ~30D ATM index-replication structures the
  engine holds to expiry and settles at intrinsic; early-assignment effects
  are declared as wedge W3. The dedicated early-assignment model
  (ENGINE_SPEC §4) ships with the strategy phase, not the KAT.

Nothing here writes orders, registry entries, or kanban. Output lands in
deriv.kat_runs / kat_daily / kat_trades only.
"""
import datetime as dt
import sys
import os

sys.path.insert(0, os.path.expanduser(
    '~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
import db  # noqa: E402

COMMISSION_PER_CONTRACT = 0.65
MIN_COMMISSION = 1.00
MULT = 100

# EEP-1 (2026-10-02): early-assignment model per ENGINE_SPEC section 4 and the
# user directive of 2026-10-02. Cited as the bug fix in deriv.kat_runs params.
# EEP-2 (2026-10-07): post-assignment lifecycle per ENGINE_SPEC §4 ("Assignment
# creates the synthetic STOCK leg") — assigned stock is HELD to the next
# scheduled roll, never liquidated at the assignment-day close (the old
# liquidate-and-re-establish path locked losses and broke path attribution
# vs the European reference). Implemented in kat_bxm_put.py.
BUGFIX_TAG = 'EEP2_ASSIGN_HOLD_TO_ROLL_2026-10-07'


def early_assignment(is_call: bool, strike: float, S: float, mid: float,
                     expiry: dt.date, d: dt.date, rate: float,
                     div_tomorrow: float | None):
    """Deterministic early-assignment rule for American SHORT legs.

    Call: ITM and the dividend capturable by exercising (ex-date = next
          trading day) exceeds the call's remaining time value.
    Put:  ITM and remaining time value < carry on the strike at DTB3
          (strike * r * T_remaining): the holder earns more by exercising
          now and collecting the strike early than by keeping the time value.
    Returns (event_type, trigger_value) or None. Time value from the quoted
    mid (negative time value => exercise is strictly better => assign).
    """
    intrinsic = max(S - strike, 0.0) if is_call else max(strike - S, 0.0)
    if intrinsic <= 0:
        return None
    tv = mid - intrinsic
    if is_call:
        if div_tomorrow is not None and div_tomorrow > tv:
            return ('ASSIGN_CALL_EXDIV', div_tomorrow)
    else:
        T = (expiry - d).days / 365.0
        carry = strike * rate * T
        if tv < carry:
            return ('ASSIGN_PUT_CARRY', carry)
    return None


def third_friday(year: int, month: int) -> dt.date:
    d = dt.date(year, month, 15)
    while d.weekday() != 4:
        d += dt.timedelta(days=1)
    return d


class Engine:
    def __init__(self, fill_frac: float = 1.0, mark_mode: str = 'mid',
                 symbol: str = 'SPY'):
        assert mark_mode in ('mid', 'conservative')
        self.fill_frac = fill_frac
        self.mark_mode = mark_mode
        self.symbol = symbol
        self.conn = db.get_connection()
        self._closes = None
        self._rates = None
        self._expiries = None
        self._quote_cache = {}

    # ---- data access ------------------------------------------------------
    def closes(self) -> dict:
        if self._closes is None:
            cur = self.conn.cursor()
            cur.execute(
                """SELECT DISTINCT ON (trade_date) trade_date, payload->>'close'
                   FROM bronze.thetadata_stock_eod_raw
                   WHERE symbol = %s ORDER BY trade_date, ingested_at DESC""",
                (self.symbol,))
            self._closes = {d: float(c) for d, c in cur.fetchall()}
            cur.close()
        return self._closes

    def rates(self) -> list:
        if self._rates is None:
            cur = self.conn.cursor()
            cur.execute("""SELECT date, value FROM bronze.fred_macro_indicators
                           WHERE series_id='DTB3' ORDER BY date""")
            self._rates = [(d, float(v) / 100.0) for d, v in cur.fetchall()]
            cur.close()
        return self._rates

    def monthly_expiries(self) -> list:
        """Listed standard monthly expirations (3rd Friday, or the preceding
        Thursday when the Friday is an exchange holiday)."""
        if self._expiries is None:
            cur = self.conn.cursor()
            cur.execute("""SELECT DISTINCT expiry FROM silver.option_contracts
                           WHERE underlying = %s ORDER BY 1""", (self.symbol,))
            all_exp = {r[0] for r in cur.fetchall()}
            cur.close()
            out = []
            for e in sorted(all_exp):
                tf = third_friday(e.year, e.month)
                if e == tf or (e == tf - dt.timedelta(days=1)
                               and tf not in all_exp):
                    out.append(e)
            self._expiries = out
        return self._expiries

    def chain(self, trade_date: dt.date, expiry: dt.date,
              option_right: str) -> list:
        """All quotes for one (date, expiry, right), strikes ascending."""
        key = (trade_date, expiry, option_right)
        if key not in self._quote_cache:
            cur = self.conn.cursor()
            cur.execute(
                """SELECT c.contract_id, c.strike, q.bid, q.ask, q.mid
                   FROM silver.option_eod_quotes q
                   JOIN silver.option_contracts c USING (contract_id)
                   WHERE c.underlying = %s AND q.trade_date = %s
                     AND c.expiry = %s AND c.option_right = %s
                   ORDER BY c.strike""",
                (self.symbol, trade_date, expiry, option_right))
            self._quote_cache[key] = [
                {'contract_id': cid, 'strike': float(k),
                 'bid': float(b) if b is not None else None,
                 'ask': float(a) if a is not None else None,
                 'mid': float(m) if m is not None else None}
                for cid, k, b, a, m in cur.fetchall()]
            cur.close()
        return self._quote_cache[key]

    def quote_series(self, contract_id: int) -> dict:
        """date -> quote row for one contract (all dates)."""
        key = ('series', contract_id)
        if key not in self._quote_cache:
            cur = self.conn.cursor()
            cur.execute(
                """SELECT trade_date, bid, ask, mid FROM silver.option_eod_quotes
                   WHERE contract_id = %s ORDER BY trade_date""", (contract_id,))
            self._quote_cache[key] = {
                d: {'bid': float(b) if b is not None else None,
                    'ask': float(a) if a is not None else None,
                    'mid': float(m) if m is not None else None}
                for d, b, a, m in cur.fetchall()}
            cur.close()
        return self._quote_cache[key]

    # ---- mechanics --------------------------------------------------------
    def rate_on(self, d: dt.date) -> float:
        best = None
        for rd, rv in self.rates():
            if rd > d:
                break
            best = (rd, rv)
        if best is None or (d - best[0]).days > 5:
            return self._last_rate if hasattr(self, '_last_rate') else 0.0
        self._last_rate = best[1]
        return best[1]

    def sell_fill(self, q: dict) -> float | None:
        """Fill for SELLING one contract under the fill model."""
        mid, bid, ask = q['mid'], q['bid'], q['ask']
        if bid is None or bid <= 0:
            return None
        if mid is None or ask is None or ask < bid:
            return bid  # one-sided or crossed: bid is the honest sell price
        half = (ask - bid) / 2.0
        return mid - self.fill_frac * half

    def mark(self, q: dict | None, side: int, intrinsic: float) -> tuple:
        """Mark-to-market value per share for a leg. side=-1 short.
        Returns (value, note)."""
        if q is None:
            return intrinsic, 'INTRINSIC_MARK'
        mid, bid, ask = q['mid'], q['bid'], q['ask']
        if self.mark_mode == 'mid':
            if mid is not None:
                return mid, ''
            return intrinsic, 'INTRINSIC_MARK'
        # conservative: short legs at ask, long legs at bid
        px = ask if side < 0 else bid
        if px is None or px <= 0:
            return intrinsic, 'INTRINSIC_MARK'
        return px, ''

    def select_atm(self, trade_date: dt.date, expiry: dt.date,
                   option_right: str, ref: float, max_hops: int = 5):
        """CALL: first strike >= ref; PUT: first strike <= ref. Walks further
        OTM up to max_hops looking for a sellable quote (bid > 0)."""
        chain = self.chain(trade_date, expiry, option_right)
        if not chain:
            return None, 'NO_CHAIN'
        if option_right == 'C':
            cands = [c for c in chain if c['strike'] >= ref][:1 + max_hops]
        else:
            cands = [c for c in chain if c['strike'] <= ref][::-1][:1 + max_hops]
        if not cands:
            return None, 'NO_ATM_STRIKE'
        for c in cands:
            f = self.sell_fill(c)
            if f is not None and f > 0:
                return c, ''
        return None, 'NO_SELLABLE_QUOTE'

    def close(self):
        self.conn.close()
