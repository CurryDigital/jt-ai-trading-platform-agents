#!/usr/bin/env python3
"""
Derivatives pipeline dead-man's switch (01:00 UTC daily).

Alerts (exit 1, ALERT lines on stdout -> Telegram via no_agent failure
delivery) when the previous night's expected runs did NOT land data —
absence of a run alerts, not just a failed run.

Checks:
  1. OPTIONS (deriv_thetadata_refresh, 22:45 UTC Mon-Fri; window ends T-1 ET
     by design): silver.option_eod_quotes must have rows for exp_opts, where
     exp_opts = last SPY trading day <= (today_ET - 1 day).
     On Tue-Sat mornings the latest SUCCESS eod ingest run must be <26h old
     (proves last night's cron fired; Mon/Sun mornings exempt — last
     scheduled run was Friday night).
  2. REGIME WF (regime_wf_daily, 23:15 UTC Mon-Fri): deriv.regime_label_wf
     max(date) must equal exp_wf = last SPY trading day <= today_ET.
     If gold.regime_features itself lags exp_wf, alert names the upstream
     stall instead (builder cannot outrun its inputs).
  3. ORACLE GUARD: the SPY trading-day calendar (gold.daily_ohlcv) must be
     fresh (max date >= today_ET - 4 days) or the expected-date math itself
     is untrustworthy -> alert instead of silently passing.

Trading-day oracle: gold.daily_ohlcv ticker='SPY' (handles holidays).

Account-value deadman (kanban t_5cac69f2, currency audit 2026-10-09):
  4. ACCT SUMMARY STALENESS: bronze/gold.ibkr_account_summary fetched_at must
     be fresh (bronze <= ACCT_BRONZE_MAX_AGE_H, gold <= ACCT_GOLD_MAX_AGE_H,
     enforced Tue-Sat UTC mornings — writers run on the Mon-Fri pipeline A /
     EC2 ingest cadence, so Sun/Mon mornings are exempt). gold currently holds
     a single snapshot row; its writer (pipeline A 08:30 UTC sync) gets a
     liveness check here.
  5. NAV DAY-OVER-DAY JUMP: gold.account_nav_daily book='live' latest
     transition must not exceed ACCT_NAV_JUMP_MAX_PCT (default 20%). The
     HKD/USD confusion signature is a 7.8x (680%) jump; historical max abs
     DoD move is 1.5%, so 20% cannot false-positive on this book.
  6. CROSS-SOURCE SANITY: gold.ibkr_account_summary.net_liquidation vs the
     latest live NAV row must agree within ACCT_SUMMARY_NAV_TOL_PCT (default
     15%) — catches a wrong-unit writer landing in either table.
  7. CURRENCY SANITY: gold.ibkr_positions_live rows with NULL/empty currency
     alert. gold.ibkr_account_summary label validation activates automatically
     once a currency column exists (conversion-layer card): NULL label alerts;
     a USD-labeled net_liquidation must be consistent with the HKD base within
     ACCT_FX_TOL_PCT (default 10%) of the USDHKD=X fx oracle. DUP825942 base
     currency is HKD (ACCT_BASE_CCY).

All thresholds are environment settings (see below), not buried constants.
Exit 0 + empty stdout = silent pass.
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, "/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts")
import db  # noqa: E402

ALERTS = []

# ── account-value deadman settings (env-overridable) ─────────────────────────
ACCT_BRONZE_MAX_AGE_H = float(os.environ.get("ACCT_BRONZE_MAX_AGE_H", "30"))
ACCT_GOLD_MAX_AGE_H = float(os.environ.get("ACCT_GOLD_MAX_AGE_H", "26"))
ACCT_NAV_JUMP_MAX_PCT = float(os.environ.get("ACCT_NAV_JUMP_MAX_PCT", "20"))
ACCT_SUMMARY_NAV_TOL_PCT = float(os.environ.get("ACCT_SUMMARY_NAV_TOL_PCT", "15"))
ACCT_FX_TOL_PCT = float(os.environ.get("ACCT_FX_TOL_PCT", "10"))
ACCT_BASE_CCY = os.environ.get("ACCT_BASE_CCY", "HKD")
FX_TICKER = os.environ.get("ACCT_FX_TICKER", "USDHKD=X")


def alert(msg):
    ALERTS.append(msg)


# ── account-value deadman: fetch + pure-check split (testable) ───────────────

def fetch_account_state(cur):
    """Read every account-value input once. Returns a plain-data dict so the
    check logic can be replayed against synthetic states in tests."""
    state = {}

    cur.execute("""
        SELECT account, net_liquidation, cash_hkd, cash_usd, available_funds,
               buying_power, fetched_at
        FROM bronze.ibkr_account_summary ORDER BY fetched_at DESC LIMIT 1
    """)
    r = cur.fetchone()
    state['bronze_summary'] = (
        {'account': r[0], 'net_liquidation': float(r[1]) if r[1] is not None else None,
         'fetched_at': r[6]} if r else None)

    cur.execute("""
        SELECT account, net_liquidation, cash_hkd, cash_usd, available_funds,
               buying_power, fetched_at
        FROM gold.ibkr_account_summary ORDER BY fetched_at DESC LIMIT 1
    """)
    r = cur.fetchone()
    state['gold_summary'] = (
        {'account': r[0], 'net_liquidation': float(r[1]) if r[1] is not None else None,
         'fetched_at': r[6]} if r else None)

    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'gold' AND table_name = 'ibkr_account_summary'
    """)
    state['gold_summary_cols'] = {row[0] for row in cur.fetchall()}
    ccy_col = next((c for c in ('currency', 'net_liquidation_ccy', 'base_currency')
                    if c in state['gold_summary_cols']), None)
    state['gold_summary_ccy_col'] = ccy_col
    if ccy_col:
        cur.execute(f"SELECT {ccy_col} FROM gold.ibkr_account_summary "
                    "ORDER BY fetched_at DESC LIMIT 1")
        state['gold_summary_ccy'] = cur.fetchone()[0]
    else:
        state['gold_summary_ccy'] = None

    cur.execute("""
        SELECT as_of_date, equity FROM gold.account_nav_daily
        WHERE book = 'live' ORDER BY as_of_date DESC LIMIT 2
    """)
    state['nav_live'] = [
        {'as_of_date': r[0], 'equity': float(r[1]) if r[1] is not None else None}
        for r in cur.fetchall()]

    cur.execute("""
        SELECT COUNT(*) FROM gold.ibkr_positions_live
        WHERE currency IS NULL OR btrim(currency) = ''
    """)
    state['positions_null_ccy'] = cur.fetchone()[0]

    cur.execute("""
        SELECT date, close FROM bronze.yf_prices
        WHERE ticker = %s ORDER BY date DESC LIMIT 1
    """, (FX_TICKER,))
    r = cur.fetchone()
    state['fx'] = {'date': r[0], 'close': float(r[1])} if r else None

    return state


def check_account_values(state, now_utc, weekday_utc):
    """Pure check logic — appends to ALERTS. `state` may be synthetic (tests)."""
    today_utc = now_utc.date()
    # Writers are on the Mon-Fri pipeline A / EC2 ingest cadence: at the
    # 01:00 UTC run on Sun(6)/Mon(0) mornings the last scheduled write was
    # Friday, so staleness is only enforced Tue(1)-Sat(5) mornings.
    enforce_staleness = 1 <= weekday_utc <= 5

    # ── 4. account summary staleness / writer liveness ───────────────────────
    b = state['bronze_summary']
    if b is None:
        alert("ACCT SUMMARY EMPTY: bronze.ibkr_account_summary has no rows — "
              "EC2 ingest_ibkr_tws account-values write never landed")
    elif enforce_staleness:
        age_h = (now_utc - b['fetched_at'].replace(tzinfo=timezone.utc)).total_seconds() / 3600
        if age_h > ACCT_BRONZE_MAX_AGE_H:
            alert(f"ACCT SUMMARY STALE: bronze.ibkr_account_summary last fetched "
                  f"{b['fetched_at']:%Y-%m-%d %H:%M} UTC ({age_h:.1f}h ago, max "
                  f"{ACCT_BRONZE_MAX_AGE_H}h) — IBKR account-values writer dead")

    g = state['gold_summary']
    if g is None:
        alert("ACCT SUMMARY EMPTY: gold.ibkr_account_summary has no rows — "
              "pipeline A bronze->gold sync never landed")
    elif enforce_staleness:
        age_h = (now_utc - g['fetched_at'].replace(tzinfo=timezone.utc)).total_seconds() / 3600
        if age_h > ACCT_GOLD_MAX_AGE_H:
            alert(f"ACCT SUMMARY STALE: gold.ibkr_account_summary last fetched "
                  f"{g['fetched_at']:%Y-%m-%d %H:%M} UTC ({age_h:.1f}h ago, max "
                  f"{ACCT_GOLD_MAX_AGE_H}h) — pipeline A 08:30 UTC account-summary "
                  "sync absent or failed")

    # ── 5. NAV staleness + day-over-day jump ─────────────────────────────────
    nav = state['nav_live']
    if not nav:
        alert("ACCT NAV EMPTY: gold.account_nav_daily has no book='live' rows — "
              "build_account_nav_daily never wrote the live book")
    else:
        latest = nav[0]
        # pipeline A runs Mon-Fri; at 01:00 UTC the most recent scheduled
        # write is the last weekday strictly before today.
        exp_nav = today_utc - timedelta(days=1)
        while exp_nav.weekday() >= 5:
            exp_nav -= timedelta(days=1)
        if latest['as_of_date'] < exp_nav:
            alert(f"ACCT NAV STALE: gold.account_nav_daily live max={latest['as_of_date']} "
                  f"< expected {exp_nav} (today_UTC={today_utc}) — pipeline A "
                  "build_account_nav_daily absent or failed")
        if latest['equity'] is None or latest['equity'] <= 0:
            alert(f"ACCT NAV BAD VALUE: latest live equity={latest['equity']} "
                  f"as of {latest['as_of_date']} — null/non-positive NAV")
        if len(nav) >= 2 and nav[1]['equity'] and nav[1]['equity'] > 0 \
                and latest['equity'] is not None:
            jump_pct = (latest['equity'] - nav[1]['equity']) / nav[1]['equity'] * 100
            if abs(jump_pct) > ACCT_NAV_JUMP_MAX_PCT:
                alert(f"ACCT NAV JUMP: live NAV {nav[1]['equity']:.2f} ({nav[1]['as_of_date']}) -> "
                      f"{latest['equity']:.2f} ({latest['as_of_date']}) = {jump_pct:+.1f}% "
                      f"day-over-day (max {ACCT_NAV_JUMP_MAX_PCT}%) — "
                      "currency-confusion signature (HKD/USD = 7.8x) or corrupt write")

    # ── 6. cross-source sanity: summary net_liq vs latest NAV ────────────────
    if g and nav and g['net_liquidation'] and nav[0]['equity'] \
            and nav[0]['equity'] > 0:
        dev_pct = abs(g['net_liquidation'] - nav[0]['equity']) / nav[0]['equity'] * 100
        if dev_pct > ACCT_SUMMARY_NAV_TOL_PCT:
            alert(f"ACCT UNIT MISMATCH: gold.ibkr_account_summary.net_liquidation="
                  f"{g['net_liquidation']:.2f} vs account_nav_daily live equity="
                  f"{nav[0]['equity']:.2f} ({nav[0]['as_of_date']}) diverge {dev_pct:.1f}% "
                  f"(max {ACCT_SUMMARY_NAV_TOL_PCT}%) — mixed-unit write "
                  "(HKD vs USD) in one of the two tables")

    # ── 7. currency sanity ───────────────────────────────────────────────────
    if state['positions_null_ccy']:
        alert(f"ACCT CURRENCY NULL: {state['positions_null_ccy']} gold.ibkr_positions_live "
              "rows with NULL/empty currency — unlabeled position values")

    if state['gold_summary_ccy_col']:
        ccy = state['gold_summary_ccy']
        if ccy is None or not str(ccy).strip():
            alert(f"ACCT CURRENCY NULL: gold.ibkr_account_summary "
                  f"{state['gold_summary_ccy_col']} is NULL on the latest row")
        elif str(ccy).upper() == 'USD' and ACCT_BASE_CCY == 'HKD' \
                and g and b and g['net_liquidation'] and b['net_liquidation']:
            # USD label on an HKD-base account: gold_usd * USDHKD must land
            # within fx tolerance of the bronze HKD figure.
            fx = state['fx']
            if fx is None:
                alert(f"ACCT FX ORACLE MISSING: no {FX_TICKER} row in bronze.yf_prices — "
                      "cannot validate USD-labeled account summary")
            else:
                implied_hkd = g['net_liquidation'] * fx['close']
                dev_pct = abs(implied_hkd - b['net_liquidation']) / b['net_liquidation'] * 100
                if dev_pct > ACCT_FX_TOL_PCT:
                    alert(f"ACCT CURRENCY MISLABEL: gold.ibkr_account_summary labeled USD "
                          f"(net_liq={g['net_liquidation']:.2f}) but x{fx['close']:.4f} "
                          f"USDHKD ({fx['date']}) = {implied_hkd:.0f} HKD vs bronze HKD "
                          f"{b['net_liquidation']:.2f} — off {dev_pct:.1f}% "
                          f"(max {ACCT_FX_TOL_PCT}%); label is wrong (HKD value "
                          "labeled USD — the 2026-10-02 incident signature)")
    # else: no currency column yet (conversion-layer card pending) — nothing
    # to validate; staleness/jump/unit checks above still guard the values.


def main():
    now_utc = datetime.now(timezone.utc)
    today_et = now_utc.astimezone(ZoneInfo("America/New_York")).date()
    weekday_utc = now_utc.date().weekday()  # Mon=0

    conn = db.get_connection()
    cur = conn.cursor()

    # ── oracle: SPY trading days ──────────────────────────────────────────────
    cur.execute("""
        SELECT DISTINCT date FROM gold.daily_ohlcv
        WHERE ticker = 'SPY' AND date >= %s ORDER BY date
    """, (today_et - timedelta(days=400),))
    tdays = [r[0] for r in cur.fetchall()]
    if not tdays:
        alert("ORACLE EMPTY: no SPY rows in gold.daily_ohlcv for 400d — cannot compute expected dates")
        finish(now_utc)
        return
    oracle_max = tdays[-1]
    if oracle_max < today_et - timedelta(days=4):
        alert(f"ORACLE STALE: gold.daily_ohlcv SPY max={oracle_max} (today_ET={today_et}) — "
              "equity pipeline itself is down; deriv expectations unreliable")

    cut_opts = today_et - timedelta(days=1)   # options: T-1 ET lag by design
    cut_wf = today_et                          # regime wf: same-evening via 22:30 topup
    exp_opts = max((d for d in tdays if d <= cut_opts), default=None)
    exp_wf = max((d for d in tdays if d <= cut_wf), default=None)

    # ── 1. options chain ──────────────────────────────────────────────────────
    if exp_opts is None:
        alert("OPTIONS: no expected trade date computable")
    else:
        cur.execute("""
            SELECT c.underlying, COUNT(*)
            FROM silver.option_eod_quotes q
            JOIN silver.option_contracts c USING (contract_id)
            WHERE q.trade_date = %s
            GROUP BY c.underlying
        """, (exp_opts,))
        day_counts = {u: n for u, n in cur.fetchall()}
        cur.execute("""
            SELECT c.underlying, MAX(q.trade_date)
            FROM silver.option_eod_quotes q
            JOIN silver.option_contracts c USING (contract_id)
            GROUP BY c.underlying
        """)
        any_rows = {u for u, _ in cur.fetchall()}
        for U in ('SPY', 'XLE'):
            if U not in any_rows:
                if U == 'SPY':
                    alert("OPTIONS EMPTY: silver.option_eod_quotes has no SPY rows at all")
                continue  # XLE checked only once its chain backfill has landed
            if day_counts.get(U, 0) == 0:
                alert(f"OPTIONS MISSING: silver.option_eod_quotes has 0 {U} rows for expected trade date "
                      f"{exp_opts} (today_ET={today_et}) — 22:45 deriv_thetadata_refresh absent or failed")
        cur.execute("""
            SELECT MAX(finished_at) FROM bronze.thetadata_ingest_runs
            WHERE status = 'SUCCESS' AND source_endpoint = '/v3/option/history/eod'
        """)
        last_ok = cur.fetchone()[0]
        # Tue(1)..Sat(5) UTC mornings: last night's 22:45 run should exist
        if 1 <= weekday_utc <= 5:
            if last_ok is None:
                alert("OPTIONS RUN ABSENT: no SUCCESS eod ingest run in bronze.thetadata_ingest_runs at all")
            else:
                age_h = (now_utc - last_ok).total_seconds() / 3600
                if age_h > 26:
                    alert(f"OPTIONS RUN ABSENT: last SUCCESS eod ingest run finished {last_ok:%Y-%m-%d %H:%M} UTC "
                          f"({age_h:.1f}h ago) — last night's 22:45 cron did not fire or failed")

    # ── 2. regime walk-forward ────────────────────────────────────────────────
    if exp_wf is None:
        alert("REGIME_WF: no expected trade date computable")
    else:
        cur.execute("SELECT MAX(date) FROM gold.regime_features")
        feat_max = cur.fetchone()[0]
        cur.execute("SELECT MAX(date) FROM deriv.regime_label_wf WHERE series_version = 'wf_v1'")
        wf_max = cur.fetchone()[0]
        target = min(exp_wf, feat_max) if feat_max else exp_wf
        if feat_max is None or feat_max < exp_wf:
            alert(f"REGIME_WF UPSTREAM STALE: gold.regime_features max={feat_max} < expected {exp_wf} "
                  "— 22:30 yf_us_postclose_topup gold_builder stages lagging")
        if wf_max is None:
            alert("REGIME_WF EMPTY: deriv.regime_label_wf has no wf_v1 rows")
        elif wf_max < target:
            alert(f"REGIME_WF STALE: deriv.regime_label_wf max={wf_max} < expected {target} "
                  f"(today_ET={today_et}) — 23:15 regime_wf_daily absent or failed")

    # ── 3. option vol features (23:05 UTC Mon-Fri) ────────────────────────────
    # Expected freshness tracks the OPTIONS chain (features dated T are built
    # from T's EOD chain, which lands at the T+1 22:45 run) -> same exp_opts.
    if exp_opts is not None:
        cur.execute("""
            SELECT underlying, MAX(feature_date) FROM gold.option_vol_features_daily
            GROUP BY underlying
        """)
        feat_map = {u: d for u, d in cur.fetchall()}
        for U in ('SPY', 'XLE'):
            if U not in feat_map:
                if U == 'SPY':
                    alert("FEATURES EMPTY: gold.option_vol_features_daily has no SPY rows")
                # XLE: only checked once its chain backfill has landed any rows
                continue
            if feat_map[U] < exp_opts:
                alert(f"FEATURES STALE: gold.option_vol_features_daily {U} max={feat_map[U]} "
                      f"< expected {exp_opts} — 23:05 option_vol_features_daily absent or failed")

    # ── 4-7. account-value deadman (staleness, NAV jump, currency sanity) ────
    acct_state = fetch_account_state(cur)
    check_account_values(acct_state, now_utc, weekday_utc)

    finish(now_utc)


def finish(now_utc):
    if ALERTS:
        for a in ALERTS:
            print(f"ALERT deriv_deadman: {a} [{now_utc:%Y-%m-%dT%H:%M:%SZ}]")
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
