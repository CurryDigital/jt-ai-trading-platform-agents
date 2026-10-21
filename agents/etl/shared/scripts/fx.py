#!/usr/bin/env python3
"""
fx.py — THE shared currency conversion layer (kanban t_65d96f4a).

Contract:
- gold.fx_rates is the ONLY rate source. Columns: from_ccy, to_ccy, rate
  (1 from_ccy = rate to_ccy), as_of_date, source, fetched_at.
- Rates are written exclusively by bronze/ibkr/ingest_ibkr_tws.py from the
  IBKR account payload ExchangeRate tag (and future dated-rate ingesters).
- No component converts with its own hardcoded rate. All conversions go
  through get_fx_rate()/convert()/to_usd() here.
- Missing or stale rate (older than FX_MAX_AGE_DAYS relative to as_of)
  raises FxRateMissing — no silent defaults. Callers in pipeline scripts
  let it propagate: the step fails loudly (stdout ALERT line => telegram
  via the cron wrapper) rather than writing a wrong number.

Convention on stored columns:
- fx_rate on account/snapshot rows = USD per 1 unit of the row's native
  currency (i.e. the multiplier used to produce the *_usd columns).
"""
from datetime import date, timedelta

FX_MAX_AGE_DAYS = 4  # tolerate weekends; FX rates are only captured on fetch days


class FxRateMissing(Exception):
    """Raised when no usable rate exists in gold.fx_rates. Never swallow."""
    pass


def _latest_pair(cur, from_ccy, to_ccy, as_of):
    cur.execute(
        """
        SELECT rate, as_of_date FROM gold.fx_rates
        WHERE from_ccy = %s AND to_ccy = %s AND as_of_date <= %s
        ORDER BY as_of_date DESC LIMIT 1
        """,
        (from_ccy, to_ccy, as_of),
    )
    row = cur.fetchone()
    return (float(row[0]), row[1]) if row else None


def get_fx_rate(cur, from_ccy, to_ccy, as_of=None, max_age_days=FX_MAX_AGE_DAYS):
    """Return (rate, fx_date): 1 from_ccy = rate to_ccy.

    Tries the direct pair, then the inverse. Raises FxRateMissing if no
    pair exists or the freshest rate is older than max_age_days.
    """
    from_ccy = from_ccy.upper()
    to_ccy = to_ccy.upper()
    as_of = as_of or date.today()
    if from_ccy == to_ccy:
        return 1.0, as_of

    direct = _latest_pair(cur, from_ccy, to_ccy, as_of)
    inverse = _latest_pair(cur, to_ccy, from_ccy, as_of)
    if direct is None and inverse is None:
        msg = (f"ALERT FX_RATE_MISSING: no gold.fx_rates row for "
               f"{from_ccy}/{to_ccy} (either direction) on or before {as_of}")
        print(msg, flush=True)
        raise FxRateMissing(msg)

    # Prefer whichever direction is fresher.
    candidates = []
    if direct:
        candidates.append((direct[1], direct[0], 'direct'))
    if inverse:
        candidates.append((inverse[1], 1.0 / inverse[0], 'inverse'))
    fx_date, rate, _direction = max(candidates, key=lambda c: c[0])

    if fx_date < as_of - timedelta(days=max_age_days):
        msg = (f"ALERT FX_RATE_STALE: freshest {from_ccy}/{to_ccy} rate is dated "
               f"{fx_date}, older than {max_age_days}d relative to {as_of}")
        print(msg, flush=True)
        raise FxRateMissing(msg)
    return rate, fx_date


def convert(cur, value, from_ccy, to_ccy, as_of=None):
    """Convert value from_ccy -> to_ccy. Returns (converted, rate, fx_date)."""
    if value is None:
        return None, None, None
    rate, fx_date = get_fx_rate(cur, from_ccy, to_ccy, as_of)
    return float(value) * rate, rate, fx_date


def to_usd(cur, value, from_ccy, as_of=None):
    """Convert value to USD. Returns (value_usd, rate_usd_per_unit, fx_date)."""
    return convert(cur, value, from_ccy, 'USD', as_of)
