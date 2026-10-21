#!/usr/bin/env python3
"""
build_regime_forecast.py  (v2, method='nowcast_markov_v2')
==========================================================
Populates gold.regime_forecast for the UI's 7-day risk-on bar charts.

v2 REPLACEMENT LOGIC (per qr_research frame doc regime_forecast_v2_frame_2026-08-06.md
sec 4, empirical results 2026-08-08 — walk-forward OOS, SPY 2019-2026):

US scope:
  1. Day-0 risk_on_pct = 100 * P(fwd 21d SPY return > 0 | current
     gold.hmm_regime_states.hmm_label), fitted on the trailing (expanding)
     history. Min 500 aligned obs; refit quarterly (params cached in
     gold.regime_forecast_params, REUSE_DAYS=92).
     -> fixes the v1 bug where MEAN_REV (conf~1.0) mapped to exactly 50.0 and
        the UI rendered a flat 50/50/../50 bar.
  2. Horizon propagation h=1..6: p_h = e_state * T^h . p_vector, where T is the
     row-normalized transition matrix over (CARRY, MEAN_REV, TREND) fitted on
     the same window and p_vector is the fitted state->prob vector from (1).
     Replaces the hardcoded 12%/day decay (v1 bug: magic constant).
  3. If the fit cannot run (< MIN_FIT_OBS), fall back to the v1 regime_label
     heuristic, logged loudly, method='v1_heuristic_fallback'.

Non-US scopes (HK / CRYPTO / FX / METAL):
  - No fitted state series exists for the scope proxies yet, so the interim
    day-0 is the data-driven 5-day momentum of the proxy (unchanged from v1,
    minus the near-neutral seed override).
  - Horizon: naive persistence (day-0 held flat). No magic decay constant.
  - If proxy data is missing/stale: carry forward the last valid rows for the
    scope and flag is_stale=true. HARD-CODED DISPLAY SEEDS ARE REMOVED — if a
    scope has no proxy data and no prior rows, nothing is written for it
    (a warning is logged) rather than fabricating a number.

HONESTY NOTE (frontend): this is a NOWCAST with persistence dynamics, not a
forecast. Walk-forward OOS AUC < 0.55 in every cell; do not market as a
forecast. News block CANCELLED and composite direction model SHELVED by
research gates (frame doc sec 4) — do not reintroduce.

Auditability: fitted params (T matrix, state probs, fit window, n_obs) are
written to gold.regime_forecast_params on every refit and echoed to the run
log on every run.
"""

import json
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from freshness import mark_source_refreshed

STATES = ['CARRY', 'MEAN_REV', 'TREND']   # canonical order for T / p_vector
FWD_DAYS = 21          # forward-return horizon for the state->prob fit
HORIZON_DAYS = 7       # UI bar length (day_offset 0..6)
MIN_FIT_OBS = 500      # minimum aligned obs to fit on
REFIT_DAYS = 92        # quarterly refit cadence
STALE_HMM_DAYS = 10    # hmm nowcast older than this -> US rows flagged stale
STALE_PROXY_DAYS = 10  # proxy last close older than this -> carry-forward, stale

METHOD_V2 = 'nowcast_markov_v2'
METHOD_MOMENTUM = 'momentum_nowcast'
METHOD_FALLBACK = 'v1_heuristic_fallback'

_NON_US_SCOPE = {
    'HK':     '^HSI',
    'CRYPTO': 'BTC-USD',
    'FX':     'EURUSD',
    'METAL':  'GC=F',
}

# v1 heuristic, retained ONLY as a degraded fallback when the v2 fit cannot
# run (< MIN_FIT_OBS). Not used on the normal output path.
_REGIME_BASE_V1 = {
    'TREND':    lambda c: 50 + 25 * c,
    'CARRY':    lambda c: 50 + 15 * c,
    'MEAN_REV': lambda c: 50.0,
    'EVENT':    lambda c: 50 - 15 * c,
    'FLAT':     lambda c: 50 - 25 * c,
}


# ---------------------------------------------------------------- 3x3 helpers

def _mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
            for i in range(3)]


def _mat_pow(t, h):
    out = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    for _ in range(h):
        out = _mat_mul(out, t)
    return out


# ------------------------------------------------------------------ data load

def _load_fit_series(conn):
    """Aligned (date, hmm_label, spy_close) series, ascending by date."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT h.date, h.hmm_label, s.close
            FROM   gold.hmm_regime_states h
            JOIN   gold.daily_ohlcv s
              ON   s.ticker = 'SPY' AND s.date = h.date
            WHERE  h.hmm_label = ANY(%s)
              AND  s.close IS NOT NULL
            ORDER  BY h.date
        """, (STATES,))
        return cur.fetchall()


def _fit_params(rows):
    """
    Fit T (row-normalized transitions over STATES) and
    p_vector (P(fwd FWD_DAYS SPY return > 0 | state)) on the aligned series.
    Returns (params_dict, n_prob_obs) or None if below MIN_FIT_OBS.
    """
    if len(rows) < MIN_FIT_OBS:
        return None, 0
    idx = {s: i for i, s in enumerate(STATES)}

    counts = [[0] * 3 for _ in range(3)]
    for (d0, s0, _), (d1, s1, _) in zip(rows, rows[1:]):
        counts[idx[s0]][idx[s1]] += 1
    t_matrix = []
    for r in counts:
        tot = sum(r)
        t_matrix.append([c / tot if tot else 1.0 / 3.0 for c in r])

    wins = {s: 0 for s in STATES}
    tot = {s: 0 for s in STATES}
    for i in range(len(rows) - FWD_DAYS):
        _, s0, c0 = rows[i]
        c1 = rows[i + FWD_DAYS][2]
        if c0 and c1:
            tot[s0] += 1
            if float(c1) > float(c0):
                wins[s0] += 1
    n_prob_obs = sum(tot.values())
    if n_prob_obs < MIN_FIT_OBS:
        return None, n_prob_obs
    state_probs = {s: (wins[s] / tot[s] if tot[s] else 0.5) for s in STATES}

    params = {
        'fit_window_start': str(rows[0][0]),
        'fit_window_end':   str(rows[-1][0]),
        'n_obs':            n_prob_obs,
        'state_order':      STATES,
        'state_probs':      state_probs,
        'transition_matrix': t_matrix,
    }
    return params, n_prob_obs


def _load_or_fit_params(conn, today):
    """
    Reuse cached params from gold.regime_forecast_params if fitted within
    REFIT_DAYS (quarterly cadence); otherwise refit on the full trailing
    window and persist. Returns params dict or None.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT fit_date, fit_window_start, fit_window_end, n_obs,
                   state_probs, transition_matrix, created_at
            FROM   gold.regime_forecast_params
            ORDER  BY fit_date DESC, id DESC
            LIMIT  1
        """)
        row = cur.fetchone()
        # The upstream HMM pipeline periodically RESTATES the whole label
        # history (wholesale recompute, e.g. 2026-08-10). A cached fit made
        # against the pre-restatement labels is then inconsistent with the
        # live series — invalidate it regardless of the quarterly cadence.
        cur.execute("SELECT max(computed_at) FROM gold.hmm_regime_states")
        hmm_recomputed = cur.fetchone()[0]
    cache_fresh = row and (today - row[0]).days < REFIT_DAYS
    if cache_fresh and hmm_recomputed and hmm_recomputed > row[6]:
        print(f"⚠️  hmm_regime_states restated at {hmm_recomputed} after "
              f"cached fit ({row[6]}) — forcing refit on restated labels")
        cache_fresh = False
    if cache_fresh:
        print(f"ℹ️  reusing cached fit from {row[0]} "
              f"(window {row[1]}..{row[2]}, n={row[3]})")
        return {
            'fit_window_start': str(row[1]),
            'fit_window_end':   str(row[2]),
            'n_obs':            row[3],
            'state_order':      STATES,
            'state_probs':      {k: float(v) for k, v in row[4].items()},
            'transition_matrix': [[float(x) for x in r] for r in row[5]],
        }

    rows = _load_fit_series(conn)
    params, n_prob_obs = _fit_params(rows)
    if params is None:
        print(f"⚠️  v2 fit skipped: only {len(rows)} aligned obs "
              f"({n_prob_obs} with fwd returns) < {MIN_FIT_OBS}")
        return None

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO gold.regime_forecast_params
                (fit_date, fit_window_start, fit_window_end, n_obs,
                 state_order, state_probs, transition_matrix, method)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (today, params['fit_window_start'], params['fit_window_end'],
              params['n_obs'], json.dumps(params['state_order']),
              json.dumps(params['state_probs']),
              json.dumps(params['transition_matrix']), METHOD_V2))
    print(f"✅ refit params (quarterly): window {params['fit_window_start']}.."
          f"{params['fit_window_end']}, n={params['n_obs']} -> "
          f"gold.regime_forecast_params")
    return params


def _latest_hmm_state(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT date, hmm_label
            FROM   gold.hmm_regime_states
            WHERE  hmm_label = ANY(%s)
            ORDER  BY date DESC
            LIMIT  1
        """, (STATES,))
        return cur.fetchone()  # (date, label) or None


def _latest_us_regime_v1(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT regime, confidence
            FROM   gold.regime_label
            WHERE  date = (SELECT MAX(date) FROM gold.regime_label)
        """)
        row = cur.fetchone()
    if not row:
        return None, None
    return row[0], float(row[1]) if row[1] is not None else 0.5


# --------------------------------------------------------------- row builders

def _us_markov_rows(params, cur_label, is_stale, today):
    """p_h = e_state * T^h . p_vector for h=0..HORIZON_DAYS-1."""
    idx = STATES.index(cur_label)
    p_vec = [params['state_probs'][s] for s in STATES]
    t = params['transition_matrix']
    rows = []
    for h in range(HORIZON_DAYS):
        th = _mat_pow(t, h)
        p_h = sum(th[idx][j] * p_vec[j] for j in range(3))
        risk_on = round(max(0.0, min(100.0, 100.0 * p_h)), 2)
        rows.append(('US', h, risk_on, today + timedelta(days=h),
                     METHOD_V2, is_stale))
    return rows


def _momentum_day0(conn, ticker, today, lookback=5):
    """
    Data-driven 5-day momentum day-0: return clipped to +/-5%, mapped so
    -5% -> 40, 0% -> 50, +5% -> 60. Returns None if the proxy data is missing
    or stale (last close older than STALE_PROXY_DAYS) — caller carries forward
    last valid rows instead. NO fallback seeds.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT date, close FROM gold.daily_ohlcv
            WHERE ticker = %s ORDER BY date DESC LIMIT 1 OFFSET %s
        """, (ticker, lookback))
        older_row = cur.fetchone()
        cur.execute("""
            SELECT date, close FROM gold.daily_ohlcv
            WHERE ticker = %s ORDER BY date DESC LIMIT 1
        """, (ticker,))
        latest_row = cur.fetchone()
    if not older_row or not latest_row:
        return None
    if (today - latest_row[0]).days > STALE_PROXY_DAYS:
        print(f"⚠️  {ticker}: last close {latest_row[0]} stale "
              f"(>{STALE_PROXY_DAYS}d) — treating as no data")
        return None
    older, latest = older_row[1], latest_row[1]
    if older is None or latest is None or float(older) == 0:
        return None
    ret = (float(latest) - float(older)) / float(older)
    ret = max(-0.05, min(0.05, ret))
    return 50.0 + (ret / 0.05) * 10.0


def _carry_forward_rows(conn, scope, today):
    """Last valid batch for the scope, re-dated from today, is_stale=true."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (day_offset)
                   day_offset, risk_on_pct, method
            FROM   gold.regime_forecast
            WHERE  scope = %s
            ORDER  BY day_offset, forecast_date DESC
        """, (scope,))
        prev = cur.fetchall()
    if not prev:
        return []
    return [(scope, int(d), float(r), today + timedelta(days=int(d)),
             m or METHOD_MOMENTUM, True) for d, r, m in prev]


# ---------------------------------------------------------------------- build

def build() -> int:
    conn = get_connection()
    try:
        today = date.today()
        all_rows = []
        summary = []

        # ---- US: fitted state->prob + Markov T^h --------------------------
        hmm = _latest_hmm_state(conn)
        params = _load_or_fit_params(conn, today)
        if hmm and params:
            hmm_date, cur_label = hmm
            stale = (today - hmm_date).days > STALE_HMM_DAYS
            if stale:
                print(f"⚠️  hmm nowcast stale ({hmm_date}) — US rows flagged is_stale")
            rows = _us_markov_rows(params, cur_label, stale, today)
            all_rows.extend(rows)
            sp = params['state_probs']
            summary.append(
                f"US: state={cur_label} (hmm {hmm_date}), "
                f"day0={rows[0][2]:.2f}, day6={rows[-1][2]:.2f}, "
                f"fit {params['fit_window_start']}..{params['fit_window_end']} "
                f"n={params['n_obs']}, "
                f"p(CARRY)={sp['CARRY']:.3f} p(MEAN_REV)={sp['MEAN_REV']:.3f} "
                f"p(TREND)={sp['TREND']:.3f}")
            print("   T = " + json.dumps(
                [[round(x, 4) for x in r] for r in params['transition_matrix']]))
        else:
            # degraded fallback: v1 heuristic (fit unavailable or hmm empty)
            regime, confidence = _latest_us_regime_v1(conn)
            if regime is not None:
                day0 = _REGIME_BASE_V1.get(regime, lambda c: 50.0)(confidence)
                day0 = max(0.0, min(100.0, float(day0)))
                for h in range(HORIZON_DAYS):
                    all_rows.append(('US', h, round(day0, 2),
                                     today + timedelta(days=h),
                                     METHOD_FALLBACK, True))
                summary.append(f"US: FALLBACK v1 heuristic regime={regime} "
                               f"conf={confidence:.2f} day0={day0:.1f} (stale)")
                print("⚠️  US rows written with v1_heuristic_fallback — "
                      "investigate fit inputs")
            else:
                print("⚠️  no hmm state and no regime_label — no US rows written")

        # ---- Non-US: data-driven momentum nowcast, persistence horizon ----
        for scope, ticker in _NON_US_SCOPE.items():
            day0 = _momentum_day0(conn, ticker, today)
            if day0 is not None:
                for h in range(HORIZON_DAYS):
                    all_rows.append((scope, h, round(day0, 2),
                                     today + timedelta(days=h),
                                     METHOD_MOMENTUM, False))
                summary.append(f"{scope}: ticker={ticker}, momentum day0="
                               f"{day0:.2f} (persistence over horizon)")
            else:
                carried = _carry_forward_rows(conn, scope, today)
                if carried:
                    all_rows.extend(carried)
                    summary.append(f"{scope}: ticker={ticker} NO DATA — carried "
                                   f"forward last valid values, is_stale=true")
                else:
                    summary.append(f"{scope}: ticker={ticker} NO DATA and no "
                                   f"prior rows — nothing written (no seeds)")
                    print(f"⚠️  {scope}: no proxy data and no prior rows; "
                          f"scope left unwritten rather than seeded")

        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM gold.regime_forecast WHERE forecast_date >= %s
            """, (today,))
            cur.executemany("""
                INSERT INTO gold.regime_forecast
                    (scope, day_offset, risk_on_pct, forecast_date,
                     updated_at, method, is_stale)
                VALUES (%s, %s, %s, %s, NOW(), %s, %s)
                ON CONFLICT (scope, day_offset, forecast_date) DO UPDATE SET
                    risk_on_pct = EXCLUDED.risk_on_pct,
                    updated_at  = NOW(),
                    method      = EXCLUDED.method,
                    is_stale    = EXCLUDED.is_stale
            """, all_rows)
        conn.commit()
        print(f"✅ gold.regime_forecast — {len(all_rows)} rows written "
              f"(method={METHOD_V2} US, {METHOD_MOMENTUM} non-US)")
        for s in summary:
            print(f"   {s}")
        return len(all_rows)
    finally:
        conn.close()


def _mark_freshness(error=None):
    try:
        conn = get_connection()
        try:
            mark_source_refreshed(
                conn,
                source='regime_forecast',
                asset_class='macro',
                expected_max_staleness_hours=30,
                error=error,
            )
        finally:
            conn.close()
    except Exception as e:
        print(f"  (freshness write skipped: {e})")


if __name__ == "__main__":
    try:
        build()
        _mark_freshness()
    except Exception as e:
        _mark_freshness(error=str(e))
        raise
