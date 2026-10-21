#!/usr/bin/env python3
"""
deriv.regime_label_wf nightly APPEND builder (series_version from
REGIME_WF_SERIES env, default 'wf_v3')
=====================================================================
Ported 2026-10-07 from qr_research/workspace/derivatives_foundation_v1/
build_regime_wf.py (Amendment A remediation) into the qr_etl ETL tree for
nightly cron operation. Design frozen in AMENDMENT_A_REGIME_PIT.md:

  - 3-state GaussianHMM, same 6 features, scaler fit inside each window.
  - Refit every 63 trading days on trailing <=756 clean rows (data <= refit
    date only). Refit points are ABSOLUTE row indices (756, 819, 882, ...),
    so existing rows never change chunk assignment as data grows.
  - CAUSAL decode: manual forward filter (log-space alpha recursion).
    State at t = argmax filtered posterior. NO Viterbi / backward smoothing.
  - Same assign_regime() rule layer on same-day inputs.

DIFFERENCE FROM THE ONE-OFF BUILDER: this script is APPEND-ONLY. It never
deletes or restates existing rows (the one-off did DELETE+reinsert, which is
fine for a from-scratch build but destroys point-in-time integrity as a
nightly job). It labels only dates > MAX(date) for the active series, fitting
only the chunk(s) those dates belong to. Because refit points are index-fixed
and GaussianHMM is seeded (random_state=42), appended rows are identical to
what a full rebuild would produce for those dates.

CALENDAR GATE (2026-10-16, user directive): before any append, calendar_gate()
hard-fails on (a) SPY/^VIX asymmetry either direction, (b) feature/calendar
mismatch either direction, (c) any NaN-dropped rows, (d) grid-replay mismatch
vs stored model_refit_date. The refit grid is row-offset based, so any of
these silently corrupts future labels if appended through.

Run with the etl-venv python (needs hmmlearn/sklearn/scipy):
  /home/ubuntu/.hermes/etl-venv/bin/python build_regime_wf_daily.py

Exit: 0 on success (including "nothing to append"), 1 on any failure.
Idempotent: a second run on the same data appends 0 rows.
"""
import json
import os
import sys

sys.path.insert(0, "/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts")

import numpy as np
import pandas as pd
from scipy.special import logsumexp
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler

import db  # shared ETL connection (creds from profile env/etl.env)

FEATURES = ["adx14", "hurst_30", "rv5d", "vix_z60", "adx_hurst_cross", "rv5d_change"]
N_COMPONENTS, COVARIANCE_TYPE, N_ITER, RANDOM_STATE = 3, "full", 200, 42
TRAIN_WINDOW, REFIT_EVERY = 756, 63
# Structural warm-up NaN prefix in gold.regime_features (first 30 rows,
# 2019-01-02..2019-02-13) frozen at the wf_v3 one-off build (2026-10-16).
# The calendar gate hard-fails if this changes (see calendar_gate (c)).
WARMUP_PREFIX_DROPS = 30
# Series to append. wf_v3 = rebuilt on healed+split-fixed gold (t_183d8bb1,
# 2026-10-16); wrapper exports REGIME_WF_SERIES explicitly so a future wf_v4
# is an env flip, not an edit.
SERIES_VERSION = os.environ.get("REGIME_WF_SERIES", "wf_v3")
VALID_REGIMES = {'TREND', 'MEAN_REV', 'CARRY', 'EVENT', 'FLAT'}
REPORT_PATH = "/home/ubuntu/.hermes/profiles/qr_etl/workspace/regime_wf/last_append_report.json"


def assign_regime(row):
    if row.get('event_flag') == 1 and (row.get('severity') or 0) >= 2:
        return 'EVENT'
    if pd.notna(row.get('vix_z60')) and row['vix_z60'] > 2.5:
        return 'FLAT'
    if (pd.notna(row.get('adx14')) and row['adx14'] > 22 and
            pd.notna(row.get('hurst_30')) and row['hurst_30'] > 0.55 and
            pd.notna(row.get('rv5d_change')) and row['rv5d_change'] > 0):
        return 'TREND'
    if (pd.notna(row.get('adx14')) and row['adx14'] < 22 and
            pd.notna(row.get('rv5d_change')) and row['rv5d_change'] < 0 and
            pd.notna(row.get('vix_z60')) and row['vix_z60'] < 0.5):
        return 'MEAN_REV'
    if (pd.notna(row.get('rv_iv_ratio')) and row['rv_iv_ratio'] < 0.60 and
            pd.notna(row.get('vix_z60')) and row['vix_z60'] < 0):
        return 'CARRY'
    hmm = row.get('hmm_label')
    return hmm if hmm in VALID_REGIMES else 'CARRY'


def forward_filter(model, X_scaled):
    """Causal filtered posteriors. Returns (states, confidence) per row."""
    framelogprob = model._compute_log_likelihood(X_scaled)
    T, N = framelogprob.shape
    log_alpha = np.empty((T, N))
    with np.errstate(divide='ignore'):
        log_start = np.log(model.startprob_)
        log_trans = np.log(model.transmat_)
    log_alpha[0] = log_start + framelogprob[0]
    for t in range(1, T):
        log_alpha[t] = logsumexp(log_alpha[t - 1][:, None] + log_trans, axis=0) + framelogprob[t]
    post = np.exp(log_alpha - logsumexp(log_alpha, axis=1, keepdims=True))
    return post.argmax(axis=1), post.max(axis=1)


def fit_chunk_model(clean, rp):
    """Fit scaler+HMM on clean.iloc[rp-TRAIN_WINDOW:rp]; return (model, scaler, label_map)."""
    train_df = clean.iloc[rp - TRAIN_WINDOW:rp]
    scaler = StandardScaler()
    X_train = scaler.fit_transform(train_df[FEATURES].values)
    model = GaussianHMM(n_components=N_COMPONENTS, covariance_type=COVARIANCE_TYPE,
                        n_iter=N_ITER, random_state=RANDOM_STATE, verbose=False)
    model.fit(X_train)
    means_orig = scaler.inverse_transform(model.means_)
    rv_idx = FEATURES.index("rv5d")
    order = sorted(range(N_COMPONENTS), key=lambda i: means_orig[i, rv_idx])
    label_map = {order[0]: "CARRY", order[1]: "MEAN_REV", order[2]: "TREND"}
    return model, scaler, label_map


def calendar_gate(cur, feat, clean, existing_max):
    """Hard-fail calendar-completeness gate (resume precondition, user directive
    2026-10-16). The refit grid is row-offset based: any row added to or removed
    from the clean frame shifts every subsequent refit index and silently
    changes future labels. Verify BEFORE any append:
      (a) SPY vs ^VIX in gold.daily_ohlcv, BOTH directions, over the feature span
      (b) gold.regime_features vs the SPY calendar, both directions
      (c) NaN audit: dropna must remove zero rows
      (d) grid-consistency replay: every stored SERIES_VERSION row's
          model_refit_date must match its position in TODAY's clean frame
    Exit 1 (FATAL) on any violation; the wrapper mirrors ALERT to Telegram."""
    import bisect
    span_lo = str(feat.index.min().date())
    span_hi = str(feat.index.max().date())
    fails = []

    # (a) SPY vs ^VIX, both directions
    for a, b in (("SPY", "^VIX"), ("^VIX", "SPY")):
        cur.execute("""
            SELECT d.date FROM gold.daily_ohlcv d
            WHERE d.ticker = %s AND d.date BETWEEN %s AND %s
              AND NOT EXISTS (SELECT 1 FROM gold.daily_ohlcv e
                              WHERE e.ticker = %s AND e.date = d.date)
            ORDER BY 1""", (a, span_lo, span_hi, b))
        miss = [str(r[0]) for r in cur.fetchall()]
        if miss:
            fails.append(f"{a} days missing from {b}: "
                         f"{miss[:10]}{'...' if len(miss) > 10 else ''}")

    # (b) features vs SPY calendar, both directions
    cur.execute("""
        SELECT d.date FROM gold.daily_ohlcv d
        WHERE d.ticker='SPY' AND d.date BETWEEN %s AND %s
          AND NOT EXISTS (SELECT 1 FROM gold.regime_features f WHERE f.date=d.date)
        ORDER BY 1""", (span_lo, span_hi))
    m = [str(r[0]) for r in cur.fetchall()]
    if m:
        fails.append(f"SPY days missing from gold.regime_features: {m}")
    cur.execute("SELECT date FROM gold.daily_ohlcv WHERE ticker='SPY' "
                "AND date BETWEEN %s AND %s", (span_lo, span_hi))
    spy_dates = {str(r[0]) for r in cur.fetchall()}
    extra = [str(d.date()) for d in feat.index
             if str(d.date()) not in spy_dates]
    if extra:
        fails.append(f"regime_features rows on non-SPY days: {extra}")

    # (c) NaN audit: the ONLY tolerable NaN-dropped rows are the structural
    #     warm-up prefix (first 30 rows, 2019-01-02..2019-02-13: hurst_30 /
    #     adx_hurst_cross need 30 obs). wf_v3's grid was built with exactly
    #     this prefix dropped. FATAL if (i) any INTERIOR row is dropped
    #     (mid-history NaN hole) or (ii) the prefix length changes — a
    #     warm-up backfill inserts rows before refit point 0 and shifts the
    #     entire grid.
    dropped_dates = [d for d in feat.index if d not in clean.index]
    interior = [str(d.date()) for d in dropped_dates
                if d >= clean.index[0]]
    if interior:
        fails.append(f"{len(interior)} INTERIOR regime_features rows dropped "
                     f"by NaN filter (mid-history hole): {interior[:10]}")
    n_prefix = len(dropped_dates) - len(interior)
    if n_prefix != WARMUP_PREFIX_DROPS:
        fails.append(f"warm-up NaN prefix is {n_prefix} rows, expected "
                     f"{WARMUP_PREFIX_DROPS} (frozen at wf_v3 build "
                     f"2026-10-16) — a warm-up backfill would shift the "
                     f"entire refit grid")

    # (d) grid-consistency replay: stored model_refit_date must equal the chunk
    #     refit date implied by each row's position in TODAY's clean frame.
    if existing_max is not None:
        refit_points = list(range(TRAIN_WINDOW, len(clean), REFIT_EVERY))
        cur.execute("SELECT date, model_refit_date FROM deriv.regime_label_wf "
                    "WHERE series_version=%s", (SERIES_VERSION,))
        bad = []
        for d, mrd in cur.fetchall():
            pos = clean.index.searchsorted(pd.Timestamp(d))
            if pos >= len(clean) or clean.index[pos] != pd.Timestamp(d):
                bad.append((str(d), "not in clean frame"))
                continue
            k = bisect.bisect_right(refit_points, pos) - 1
            exp = clean.index[refit_points[k] - 1].date() if k >= 0 else None
            if exp != mrd:
                bad.append((str(d), f"stored {mrd} vs grid {exp}"))
        if bad:
            fails.append(f"grid replay mismatch on {len(bad)} rows: {bad[:5]}")

    if fails:
        for f in fails:
            print(f"FATAL CALENDAR GATE: {f}", file=sys.stderr)
        sys.exit(1)
    print(f"calendar gate PASS ({SERIES_VERSION}): SPY<->^VIX symmetric, "
          f"features==SPY calendar, NaN prefix == {WARMUP_PREFIX_DROPS} "
          f"(warm-up, 0 interior), grid replay clean "
          f"({span_lo}..{span_hi})")


def main():
    conn = db.get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT r.date, r.adx14, r.hurst_30, r.rv5d, r.rv_iv_ratio, r.vix_z60,
               r.event_flag, r.adx_hurst_cross, r.rv5d_change,
               CASE m.severity WHEN 'heavy' THEN 3 WHEN 'medium' THEN 2 WHEN 'light' THEN 1 ELSE 0 END AS severity
        FROM gold.regime_features r
        LEFT JOIN gold.macro_event_flags m ON r.date = m.date
        ORDER BY r.date
    """)
    rows = cur.fetchall()
    cols = ['date', 'adx14', 'hurst_30', 'rv5d', 'rv_iv_ratio', 'vix_z60',
            'event_flag', 'adx_hurst_cross', 'rv5d_change', 'severity']
    feat = pd.DataFrame(rows, columns=cols)
    feat['date'] = pd.to_datetime(feat['date'])
    feat = feat.set_index('date').sort_index()
    for c in cols[1:]:
        feat[c] = pd.to_numeric(feat[c], errors='coerce').astype(float)

    clean = feat.dropna(subset=FEATURES).copy()
    print(f"features: {len(feat)} rows {feat.index.min().date()}..{feat.index.max().date()}; clean: {len(clean)}")

    cur.execute("SELECT MAX(date) FROM deriv.regime_label_wf WHERE series_version = %s",
                (SERIES_VERSION,))
    existing_max = cur.fetchone()[0]
    print(f"existing {SERIES_VERSION} max(date): {existing_max}")

    # Hard-fail calendar-completeness gate — runs BEFORE any append logic.
    calendar_gate(cur, feat, clean, existing_max)

    if len(clean) < TRAIN_WINDOW + REFIT_EVERY:
        print("FATAL: insufficient clean rows for walk-forward", file=sys.stderr)
        sys.exit(1)

    refit_points = list(range(TRAIN_WINDOW, len(clean), REFIT_EVERY))
    X_all = clean[FEATURES].values

    # Indices to label: beyond existing_max, at/after the first refit point.
    if existing_max is None:
        first_new = refit_points[0]
    else:
        ts = pd.Timestamp(existing_max)
        pos = clean.index.searchsorted(ts)
        # pos points at existing_max (it is a clean date, since it was labelled)
        first_new = pos + 1
    if first_new >= len(clean):
        print(f"nothing to append — {SERIES_VERSION} already current through "
              f"{clean.index[-1].date()}")
        conn.close()
        return

    out = []  # (date, hmm_state, hmm_label, confidence, refit_date)
    refits_done = []
    for k, rp in enumerate(refit_points):
        chunk_end = refit_points[k + 1] if k + 1 < len(refit_points) else len(clean)
        lo = max(rp, first_new)
        if lo >= chunk_end:
            continue
        model, scaler, label_map = fit_chunk_model(clean, rp)
        X_chunk = scaler.transform(X_all[:chunk_end])
        states, conf = forward_filter(model, X_chunk)
        refit_date = clean.index[rp - 1]  # last date in training window
        refits_done.append(str(refit_date.date()))
        for j in range(lo, chunk_end):
            out.append((clean.index[j], int(states[j]), label_map[int(states[j])],
                        float(conf[j]), refit_date))
        print(f"  chunk refit_date={refit_date.date()} -> labelled "
              f"{chunk_end - lo} new days ({clean.index[lo].date()}..{clean.index[chunk_end - 1].date()})")

    if not out:
        print("nothing to append after chunk scan")
        conn.close()
        return

    wf = pd.DataFrame(out, columns=['date', 'hmm_state', 'hmm_label', 'confidence', 'model_refit_date'])
    wf = wf.set_index('date').sort_index()

    # ── rules layer (same-day features) ──────────────────────────────────────
    df = wf.join(feat[['adx14', 'hurst_30', 'rv_iv_ratio', 'vix_z60', 'event_flag', 'rv5d_change', 'severity']],
                 how='left')
    df['regime'] = df.apply(assign_regime, axis=1)
    df['override_used'] = (
        (df['event_flag'] == 1) | (df['vix_z60'] > 2.5) |
        ((df['adx14'] > 22) & (df['hurst_30'] > 0.55) & (df['rv5d_change'] > 0)) |
        ((df['adx14'] < 22) & (df['rv5d_change'] < 0) & (df['vix_z60'] < 0.5)) |
        ((df['rv_iv_ratio'] < 0.60) & (df['vix_z60'] < 0))
    )

    # ── append-only store ─────────────────────────────────────────────────────
    db.require_table(conn, 'deriv', 'regime_label_wf')
    ins = 0
    skipped_conflict = 0
    for idx, r in df.reset_index().iterrows():
        cur.execute("""
            INSERT INTO deriv.regime_label_wf
              (date, series_version, regime, hmm_label, override_used, confidence, severity, model_refit_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (date, series_version) DO NOTHING""",
            (pd.Timestamp(r['date']).date(), SERIES_VERSION, r['regime'], r['hmm_label'],
             bool(r['override_used']), float(r['confidence']),
             int(r['severity']) if pd.notna(r['severity']) else 0,
             r['model_refit_date'].date()))
        if cur.rowcount == 1:
            ins += 1
        else:
            skipped_conflict += 1
    conn.commit()
    print(f"appended {ins} rows into deriv.regime_label_wf ({SERIES_VERSION}); "
          f"conflicts skipped: {skipped_conflict}")
    if skipped_conflict:
        # Append-only violation attempt: dates at/below existing_max were relabelled.
        # Not fatal (nothing was overwritten), but flag it loudly in the log.
        print(f"WARNING: {skipped_conflict} rows already existed — check first_new logic",
              file=sys.stderr)

    # ── disagreement report for the NEW rows only (vs smoothed series) ───────
    cur.execute("SELECT date, regime FROM gold.regime_label WHERE date > %s ORDER BY date",
                (existing_max,))
    sm = pd.DataFrame(cur.fetchall(), columns=['date', 'smoothed_regime'])
    report = {
        "series_version": SERIES_VERSION,
        "mode": "append",
        "calendar_gate": "PASS",
        "series_source": "gold.regime_features",
        "previous_max_date": str(existing_max),
        "appended": int(ins),
        "span": [str(df.index.min().date()), str(df.index.max().date())],
        "refit_dates_used": refits_done,
        "regime_counts": df['regime'].value_counts().to_dict(),
    }
    if len(sm):
        sm['date'] = pd.to_datetime(sm['date'])
        cmp_df = df.reset_index()[['date', 'regime']].merge(sm, on='date')
        if len(cmp_df):
            dis = 1 - (cmp_df['regime'] == cmp_df['smoothed_regime']).mean()
            report["new_rows_vs_smoothed"] = {
                "overlap_days": int(len(cmp_df)),
                "disagreement_pct": round(float(dis) * 100, 2),
            }
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))
    conn.close()


if __name__ == '__main__':
    main()
