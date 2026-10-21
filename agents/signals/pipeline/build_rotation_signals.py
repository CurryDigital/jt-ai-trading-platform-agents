"""
Generic rotation signal engine for paused paper strategies.
Reads gold.strategy_registry, computes point-in-time signals from
silver.unified_prices, and writes target weights to gold.strategy_ticker_scores.

2026-08-05 (t_82a67ac5): emit `signal_strength` — a continuous 0-100
cross-sectional composite strength (midpoint percentile of the strategy's
rank metric across its universe). `score` remains the portfolio target
weight (load-bearing for rebuild_paper_positions.py sizing:
weight = score / total_score) and must NOT be repurposed. The UI-facing
consumption.signal_setups.potential is derived from signal_strength by
build_signal_redesign.py; previously it read `score` verbatim, surfacing
raw weights in mixed units (0.33 vs 50.00 for the same 0.5 weight) and
0.00 for every SELL row.
"""
import os, sys, json, math, psycopg2, pandas as pd, numpy as np
from datetime import datetime, timedelta

# Connection: prefer explicit ROTATION_DB_* override, then the standard ETL
# DB_* env (sourced from env/etl.env by run_signal_cycle.sh -> direct RDS,
# no tunnel dependency), then the legacy OPENCLAW_DB_* + local 5433 tunnel.
_db_user = os.environ.get('OPENCLAW_DB_USER') or os.environ['DB_USER']
_db_pw = os.environ.get('OPENCLAW_DB_PASSWORD') or os.environ['DB_PASSWORD']
_db_host = os.environ.get('ROTATION_DB_HOST') or os.environ.get('DB_HOST', '127.0.0.1')
_db_port = os.environ.get('ROTATION_DB_PORT') or os.environ.get('DB_PORT', '5433')
DB_URL = f"postgresql://{_db_user}:{_db_pw}@{_db_host}:{_db_port}/aitrading"

LOOKBACKS = {'1w': 5, '2w': 10, '4w': 21, '12w': 63, '13w': 65, '26w': 126, '50w': 252, '12m': 252}

STRATEGY_CONFIGS = {
    # --- ETF monthly strategies ---
    'ETF_Covered_Call_Income_Rotation': {
        'freq': 'monthly', 'rank': 'momentum_12w', 'top_n': 3, 'weight': 'equal',
        'cash_if_negative': True, 'universe': ['JEPI','JEPQ','QYLD','XYLD','PBP'],
    },
    'ETF_Defensive_Equity_Income': {
        'freq': 'monthly', 'filter': 'spy_26w_sma', 'rank': 'momentum_12w', 'top_n': 3,
        # universe expanded 2026-07-30 (registry logic: top 3 of 6 defensive ETFs)
        'weight': 'equal', 'universe': ['VYM','SCHD','XLU','XLP','JEPI','JEPQ'],
    },
    'ETF_Dividend_Aristocrats_Treasury_Barbell': {
        'freq': 'monthly', 'rank': 'momentum_12w_vol', 'top_n': 4,
        # universe expanded 2026-07-30 (registry logic: 2 per sleeve, 25% each)
        'weight': 'equal', 'universe': ['SCHD','VYM','JEPI','TLT','IEF','AGG','BND','GOVT'],
        'sleeves': [('SCHD','VYM','JEPI'), ('TLT','IEF','AGG','BND','GOVT')],
        'sleeve_top_n': 2,  # 2 equity + 2 bond
    },
    'ETF_Global_Risk_Parity_VolTarget': {
        'freq': 'monthly', 'rank': 'inverse_vol_12w', 'top_n': 'all',
        'weight': 'risk_parity_voltarget', 'target_vol': 0.10, 'universe': ['QQQ','VTI','VNQ','GLD','TLT','AGG'],
    },
    'ETF_HK_Balanced_Trend': {
        # universe expanded 2026-07-30 (registry logic: top 2 equal-weight, no regime filter)
        'freq': 'monthly', 'rank': 'momentum_12w', 'top_n': 2,
        'weight': 'equal', 'universe': ['2800.HK','EEM','EFA','AGG','IEF','TLT','BND','GOVT'],
    },
    'ETF_HY_Credit_Carry': {
        'freq': 'monthly', 'rank': 'momentum_13w', 'top_n': 3,
        # universe expanded 2026-07-30 (registry logic: top 3 of 6, negative momentum -> CASH)
        'weight': 'equal', 'cash_if_negative': True, 'drop_to_cash': True,
        'universe': ['HYG','JNK','EMB','LQD','AGG','BND'],
    },
    'ETF_Multi_Asset_Tactical_Allocation': {
        'freq': 'monthly', 'rank': 'momentum_12w', 'top_n': 3,
        'weight': 'inverse_vol', 'cash_if_negative': True,
        # 10-asset universe (EFA/EEM onboarded to silver.unified_prices 2026-07-29,
        # research re-backtest 4-stage audit PASS, manifest 2026-07-29)
        'universe': ['SPY','QQQ','IWM','AGG','TLT','GLD','VNQ','DBC','EFA','EEM'],
    },
    'ETF_REIT_Dividend_Momentum': {
        # universe expanded 2026-07-30 (registry logic: top 3 of 7)
        'freq': 'monthly', 'filter': 'spy_26w_sma', 'rank': 'momentum_12w', 'top_n': 3,
        'weight': 'equal', 'universe': ['VNQ','IYR','XLRE','SCHH','REM','SCHD','VYM'],
    },
    'ETF_Small_Cap_Momentum': {
        # universe expanded 2026-07-30 (registry logic: top 2 equal-weight)
        'freq': 'monthly', 'filter': 'spy_26w_sma', 'rank': 'momentum_12w', 'top_n': 2,
        'weight': 'equal', 'universe': ['IWM','SPY','VOO','QQQ','VTI','DIA','IWB'],
    },
    'ETF_US_Sector_Relative_Momentum': {
        # 2026-09-18 (kanban t_3741eba6): KEEP-TUNED params from
        # gold.strategy_backtest_runs run_number=4 — top_n 3->4, per-name
        # sleeve 0.30->0.225 via cash_residual=0.10 (4x0.225 + 0.10 = 1.0).
        'freq': 'monthly', 'filter': 'spy_26w_sma', 'rank': 'momentum_12w', 'top_n': 4,
        'weight': 'equal', 'cash_residual': 0.10,
        'universe': ['SPY','XLF','XLK','XLE','XLI','XLP','XLU','XLB','SMH','IWM'],
    },
    # --- US stock weekly strategies ---
    'US_STK_DEF_MOM_10': {
        'freq': 'weekly', 'filter': 'spy_50w_sma', 'rank': 'momentum_12w', 'top_n': 5,
        'weight': 'equal', 'universe': ['CAT','CSX','APD','KO','EQIX'],
    },
    'US_STK_GOLD_HDG_05': {
        'freq': 'weekly', 'filter': 'spy_26w_sma_gld', 'rank': 'hold', 'top_n': 1,
        'weight': 'winner_takes_all', 'universe': ['GLD','CASH'],
    },
    'US_STK_LOWVOL_DIV_02': {
        'freq': 'weekly', 'filter': 'spy_26w_sma', 'rank': 'lowvol_63d_positive_momentum', 'top_n': 5,
        # universe expanded 2026-07-30 (registry logic: 52-name dividend/quality universe,
        # 5 lowest 63d vol among positive 12w momentum)
        'weight': 'equal',
        'universe': ['KO','PEP','PG','CL','KMB','GIS','HSY','MKC','SYY','ADM','CPB','MO','PM',
                     'T','VZ','JNJ','MRK','ABBV','BMY','PFE','WMT','COST','MCD','SBUX','YUM',
                     'TRV','CB','AFL','APD','LIN','SHW','ECL','DUK','SO','NEE','EXC','AEP',
                     'XEL','D','PEG','SRE','ED','ES','PPL','CMS','CNP','NI','LNT','EVRG','ATO',
                     'WEC','OKE'],
    },
    'US_STK_MOM_LDR_01': {
        'freq': 'weekly', 'filter': 'spy_26w_sma', 'rank': 'riskadj_momentum_26w', 'top_n': 5,
        'weight': 'equal', 'universe': ['CSX','CAT','JNJ','TXN','MPC'],
    },
    'US_STK_QUAL_ROE_07': {
        # universe expanded 2026-07-30 (registry logic: 46-name quality universe,
        # rank by 26w risk-adjusted momentum among positive 12w momentum, top 5)
        'freq': 'weekly', 'filter': 'spy_26w_sma', 'rank': 'riskadj_26w_positive_momentum', 'top_n': 5,
        'weight': 'equal',
        'universe': ['MSFT','AAPL','NVDA','GOOGL','META','V','MA','UNH','LLY','JNJ','PG','HD',
                     'COST','MCD','NKE','SBUX','TJX','ROST','ACN','IBM','INTU','ADP','PYPL',
                     'FIS','GPN','VRSK','CTSH','ORCL','CSCO','TXN','QCOM','AVGO','AMD','NFLX',
                     'TMO','ISRG','SYK','MDT','BSX','ZTS','GILD','REGN','VRTX','AMGN','ABBV',
                     'MRK'],
    },
    'US_STK_SM_CAP_CRED_08': {
        'freq': 'weekly', 'filter': 'spy_26w_sma_hy', 'rank': 'riskadj_momentum_12w', 'top_n': 5,
        'weight': 'equal', 'universe': ['CSX','CAT','JNJ','TXN','MPC'],
    },
    'US_STK_VAL_REV_03': {
        'freq': 'weekly', 'filter': 'spy_26w_sma_rates', 'rank': 'momentum_12w', 'top_n': 5,
        'weight': 'equal', 'universe': ['ABBV','ADP','AMAT','AMGN','AON','AXP','BAC','BLK','C','CAT','CCI','CI','CL','CME','COF','COST','CSCO','CSX','CVS','DE','DUK','EQIX','FISV','GE','GILD','GOOGL','GS','IBM','ICE','INTU','ISRG','JNJ','JPM','KO','LLY','LMT','MDLZ','MET','META','MMM','MS','MSFT','NOC','NVDA','PM','PYPL','RTX','SBUX','SLB','SO','TGT','TJX','TRV','TSLA','TXN','V','VZ','WMT','XOM'],
    },
    # --- HK monthly/weekly strategies ---
    'HK_Quality_BlueChips': {
        'freq': 'monthly', 'filter': 'hk2800_126d', 'rank': 'riskadj_momentum_12m', 'top_n': 5,
        'weight': 'equal', 'universe': ['0001.HK','0002.HK','0003.HK','0005.HK','0006.HK','0016.HK','0027.HK','0388.HK','0836.HK','0939.HK','0941.HK','1038.HK','1299.HK','1398.HK','1928.HK','2318.HK','2388.HK','2628.HK'],
    },
    # HK_LowVol_Weekly RETIRED 2026-08-05 (kanban t_d223563a): 0.97 OOS corr
    # with HK_LowVol_TrendFilter_Weekly — redundant duplicate, consolidated.
    # Config removed; do not re-add without a new book review.
    'HK_LowVol_TrendFilter_Weekly': {
        'freq': 'weekly', 'filter': 'hk2800_126d', 'rank': 'lowvol_63d', 'top_n': 5,
        'weight': 'equal', 'universe': ['0001.HK','0002.HK','0003.HK','0005.HK','0006.HK','0016.HK','0027.HK','0388.HK','0836.HK','0939.HK','0941.HK','1038.HK','1299.HK','1398.HK','1928.HK','2318.HK','2388.HK','2628.HK'],
    },
    # --- FX/commodity ---
    'gc_cot_contrarian_inverse': {
        'freq': 'daily', 'rank': 'hold', 'top_n': 0, 'weight': 'equal', 'universe': ['GC=F','CASH'],
    },
    'COMM_GoldSilver_Ratio_MeanRev_VolTarget': {
        # 2026-07-31: 4-stage audit PASS (incl. qa_reproduction). Hysteresis
        # state machine (250d ratio z-score, enter |z|>2, exit z crossing 0)
        # + vol-target overlay -- NOT point-in-time ranking, so it uses the
        # custom handler below. Signal logic must mirror the research
        # backtest bt_gs_ratio_voltarget.py exactly.
        'freq': 'monthly', 'custom': 'gs_ratio_meanrev_voltarget',
        'universe': ['GC=F','SI=F'],
        'z_window': 250, 'z_enter': 2.0, 'vol_target': 0.10,
        'vol_lookback': 63, 'entry_lag_days': 5,
    },
    'etf_vix_scaled_11': {
        # 2026-08-06 (t_68846e9c): run_number=3 — supersedes run 2 (t_f7b59c0b)
        # before run 2 ever traded live. 4-stage audit PASS (expansion pass 3,
        # audit_vix_d1.5_g0.3). eq = clip(1 - max(0,vix_z60)/1.5, 0, 1);
        # equity split SPY 0.6*eq / QQQ 0.4*eq; defensive remainder 70/30
        # IEF/GLD; eq<=0.01 -> IEF 0.7 / GLD 0.3. Custom handler mirrors
        # research vix_sig(1.5, 0.3)
        # (expansion_2026-08-06/expansion_pass3.py) exactly;
        # vix_z60 sourced from gold.vix_regime (silver.vix_indicators, 60d
        # rolling z of ^VIX close) — DB-backed, no signal-file dependency.
        # Denom 1.5 came from a 9-point OOS grid (smooth region, IS
        # non-degraded) — regime watch on live paper.
        'freq': 'weekly', 'custom': 'vix_scaled_gld_sleeve',
        'universe': ['SPY','QQQ','IEF','GLD'],
    },
    'crisis_safe_haven_vt_19': {
        # 2026-08-06 (t_ab33144a): batch13 EXPERIMENTAL crisis-alpha sleeve,
        # 4-stage audit PASS (audit_safe_haven_v2; risk stage flagged 60% max
        # single-asset > 50% cap, accepted as intended safe-haven design).
        # Rank GLD/TLT/IEF by 63d momentum; top-2 get 0.6/0.4, each leg
        # requires positive 252d momentum else that leg -> IEF; scale to 10%
        # vol target (63d realized), lev cap 1.5, residual -> IEF. Monthly.
        # Custom handler mirrors research sig_safe_haven_v2
        # (batch13_2026-08-06/batch13_safehaven_v2.py) exactly; prices from
        # silver.unified_prices — DB-backed, no signal-file dependency.
        'freq': 'monthly', 'custom': 'safe_haven_v2',
        'universe': ['GLD', 'TLT', 'IEF'],
    },
    'etf_tech_mom_13': {
        # 2026-08-06 (t_68846e9c): run_number=2 — defensive fallback change
        # only, 4-stage audit PASS (expansion pass 3, audit_tech_mom_gld).
        # Top-2 of SMH/QQQ/XLK/IGV by 63d momentum; each leg passing the
        # 200d-SMA filter gets 0.5, a failing leg goes 50/50 IEF/GLD
        # (was 100% IEF in run 1). 15% vol target, leverage cap 1.3x,
        # monthly. Custom handler mirrors research sig_tech_gld
        # (expansion_2026-08-06/expansion_pass3.py) exactly; prices from
        # silver.unified_prices — DB-backed, no signal-file dependency.
        'freq': 'monthly', 'custom': 'tech_mom_gld_fallback',
        'universe': ['SMH','QQQ','XLK','IGV','IEF','GLD'],
    },
    'etf_trend_overlay_mom12m_v1': {
        # 2026-08-09 (t_63a4a2b7): batch handoff EXPERIMENTAL, 4-stage audit
        # PASS (audit_mom12m/, qa repro byte-identical). Per leg SPY/QQQ/GLD/TLT
        # 25%: risk-on iff month-end close > close 252 trading days ago; else
        # leg -> IEF; IEF 12M momentum <= 0 -> leg -> CASH. Signal at month-end
        # close t earns from t+1 (no same-bar application); weights stand until
        # the next month-end. Custom handler mirrors research
        # trend_overlay_finalize.py (workspace, audit_mom12m qa_reproduce copy)
        # exactly; prices from silver.unified_prices with the research px()
        # per-ticker market-preference dedup — DB-backed, no signal-file
        # dependency.
        'freq': 'monthly', 'custom': 'trend_overlay_mom12m',
        'universe': ['SPY','QQQ','GLD','TLT','IEF','CASH'],
    },
    'etf_comm_trend_basket_15': {
        # 2026-08-13 (t_84d61124): migrated ingested -> computed. Static
        # batch12 signals JSON was 7 days stale and the daily delta
        # rebalancer churned the book mid-month off it (GLD 1-day round
        # trip 08-06 -> 08-07, then BELOW_ONE_LOT re-entry skips).
        # Custom handler mirrors research sig_c2
        # (batch12_2026-08-05/batch12_backtest.py) exactly: GLD/SLV/DBC/USO/
        # UNG 12M TSMOM (hold iff 252d return > 0), inverse-63d-vol weights,
        # lev = min(1.5, 0.10/pv63), residual cash implicit, all-out -> IEF.
        # Monthly: weights set at the most recent COMPLETED month-end and
        # stand until the next one (signal at month-end close t earns from
        # t+1, matching the research 1-period lag). Prices from
        # silver.unified_prices — DB-backed, no signal-file dependency.
        'freq': 'monthly', 'custom': 'comm_trend_tsmom',
        'universe': ['GLD', 'SLV', 'DBC', 'USO', 'UNG', 'IEF'],
    },
    'COMM_Gold_Trend_VolTarget': {
        # 2026-08-18 (t_7ea489c0): WRITE_SIGNAL handoff from qr_research
        # (gapdaily_2026-08-18 batch; 4-stage audit PASS x4 incl.
        # qa_reproduction; manifest strategy_handoff_manifest_20260818.json,
        # variant lb63_vt10). Daily single-asset trend + vol target:
        # long GC=F iff 63d momentum (close/close.shift(63)-1) > 0 else
        # CASH; exposure = min(1, 0.10 / trailing 21d realized vol),
        # point-in-time; signal at close t earns t+1 (paper engine books
        # NEXT_OPEN pending orders = the platform 1-bar execution lag).
        # Custom handler mirrors research w_trend_voltarget
        # (gapdaily_2026-08-18/gapdaily_backtest.py) exactly; prices from
        # silver.unified_prices with the research loader's market-label
        # dedup preferring GLOBAL — DB-backed, no signal-file dependency.
        # max_position_pct overridden to 1.0 in gold.strategy_configs
        # (vol targeting is the risk limiter; the 0.20 default would break
        # backtest parity when exposure reaches 1.0).
        'freq': 'daily', 'custom': 'trend_voltarget_daily',
        'universe': ['GC=F', 'CASH'],
        'asset_ticker': 'GC=F', 'mom_lookback': 63,
        'vol_target': 0.10, 'vol_lookback': 21,
    },
    'COMM_Copper_Trend_VolTarget': {
        # 2026-08-18 (t_580bc43d): WRITE_SIGNAL handoff from qr_research
        # (gapdaily_2026-08-18 batch; 4-stage audit PASS x4 incl.
        # qa_reproduction; manifest strategy_handoff_manifest_20260818.json,
        # variant lb63_vt10). RE-WIRED 2026-08-18 (t_e5d74ef9) to variant
        # lb126_vt10 after the post-backfill re-audit (t_d9a509e6,
        # manifest strategy_handoff_manifest_20260818_postbackfill.json)
        # INVALIDATED lb63_vt10 on filled data (OOS Sharpe 0.59 -> 0.22;
        # stale marks across the Feb-May 2026 hole had flattered 2026 OOS).
        # lb126_vt10 re-approved PASS x4: OOS Sharpe 0.9668, maxDD -6.4%,
        # PF 1.22, 359 trade days, IS 0.49 (regime flag OOS~2xIS ->
        # EXPERIMENTAL sizing). Same w_trend_voltarget logic as the gold
        # sibling above, on HG=F: long iff 126d momentum > 0 else CASH;
        # exposure = min(1, 0.10 / trailing 21d realized vol), point-in-time;
        # 1-bar execution lag via the paper engine's NEXT_OPEN pending
        # orders. HG=F fresh rows live under the blank market tag; the
        # loader's market-label dedup preferring GLOBAL then blank matches
        # the research load_prices() exactly. max_position_pct
        # overridden to 1.0 in gold.strategy_configs (vol targeting is the
        # risk limiter; the 0.20 default would break backtest parity when
        # exposure reaches 1.0).
        'freq': 'daily', 'custom': 'trend_voltarget_daily',
        'universe': ['HG=F', 'CASH'],
        'asset_ticker': 'HG=F', 'mom_lookback': 126,
        'vol_target': 0.10, 'vol_lookback': 21,
    },
    'etf_country_rot_10_v2': {
        # 2026-08-06 (t_55cedb93): run_number=2 — universe expanded 5->14
        # country ETFs, 4-stage audit PASS (expansion2, audit_country_x14).
        # Top-2 of the 14 by 63d momentum, 50/50; each leg requires
        # positive 252d momentum else that leg -> IEF; portfolio vol =
        # std of 63d weighted daily returns * sqrt(252); lev =
        # min(1.3, 0.12/pv) (1.0 when pv unusable); weights *= lev.
        # Monthly, entry at close of signal date. Custom handler mirrors
        # research sig_country_x14
        # (expansion2_2026-08-06/expansion2_backtest.py) exactly; prices
        # from silver.unified_prices — DB-backed, no signal-file
        # dependency.
        'freq': 'monthly', 'custom': 'country_rot_x14',
        'universe': ['SPY','EFA','EEM','FXI','MCHI','EWJ','EZU','EWU','EWC',
                     'INDA','EWY','EWT','EWA','EWZ','IEF'],
    },
    'etf_def_sector_rot_12_w': {
        # 2026-08-17 (t_d733f4c4): migrate ingested -> computed. Static
        # batch11 signals JSON went 12d stale (>8d weekly gate; risk
        # BLOCK t_1d44ee3c set disable_paper_rebuild=TRUE). Custom
        # handler mirrors research sig_e7
        # (batch11_2026-08-05/batch11_backtest.py; qa_reproduce copy
        # byte-identical) exactly: rank SPY/XLU/XLP/XLV by 63d momentum
        # (batch10 mom: per-ticker dropna close, needs >= n+5 obs,
        # last/last-n - 1); top-2 get 0.5 each; each leg needs mom252>0
        # (None/non-positive fails) else that leg -> IEF, legs merge.
        # Weekly: decision date = last trading day of the most recent
        # COMPLETED ISO week (a week counts completed once the wall clock
        # enters a later ISO week, or when its Friday close is already in
        # the DB); weights stand intra-week, reproducing the research
        # 1-period lag (signal at week-end close t earns from t+1).
        # Prices from silver.unified_prices (dedup keep-last, same as the
        # research batch10 loader) — DB-backed, no signal-file dependency.
        'freq': 'weekly', 'custom': 'def_sector_rot_w',
        'universe': ['SPY', 'XLU', 'XLP', 'XLV', 'IEF'],
    },
}


def fetch_prices(conn, tickers, min_date):
    df = pd.read_sql(
        """SELECT ticker, date, open, high, low, close, volume
           FROM silver.unified_prices
           WHERE ticker = ANY(%s) AND date >= %s
           ORDER BY ticker, date""",
        conn, params=(list(tickers), min_date)
    )
    df['date'] = pd.to_datetime(df['date'])
    return df


def fetch_prices_deduped(conn, tickers):
    """Full history with market labels combined, deduped by date preferring
    GLOBAL. Mirrors bt_gs_ratio_voltarget.py load_data() exactly."""
    df = pd.read_sql(
        """SELECT date, ticker, close, market
           FROM silver.unified_prices
           WHERE ticker = ANY(%s) AND close IS NOT NULL
           ORDER BY ticker, date""",
        conn, params=(list(tickers),)
    )
    pref = {'GLOBAL': 0, '': 1, None: 1, 'US': 2}
    df['pref'] = df['market'].map(lambda m: pref.get(m, 3))
    df = df.sort_values(['ticker', 'date', 'pref']).drop_duplicates(['ticker', 'date'], keep='first')
    df['date'] = pd.to_datetime(df['date'])
    close = df.pivot(index='date', columns='ticker', values='close').sort_index().astype(float)
    return close.dropna()


def gs_ratio_current_state(close, cfg):
    """Replay the GC/SI ratio z-score hysteresis state machine over full
    history and return the effective current position/exposure (honouring
    the 5-trading-day entry lag). Mirrors bt_gs_ratio_voltarget.py
    run_backtest() signal logic exactly:
      flat -> long SI=F if z > +ze ; long GC=F if z < -ze ; exit at z cross 0
      exposure = min(1, vol_target / trailing 63d realized vol of chosen leg),
      fixed between monthly rebalances, vol known at signal date.
    """
    daily_ret = close.pct_change()
    ratio = close['GC=F'] / close['SI=F']
    zw = cfg['z_window']
    z = (ratio - ratio.rolling(zw).mean()) / ratio.rolling(zw).std(ddof=1)
    realized_vol = daily_ret.rolling(cfg['vol_lookback']).std(ddof=1) * np.sqrt(252)
    month_ends = list(close.groupby(close.index.to_period('M')).apply(lambda x: x.index.max()).values)
    all_dates = list(close.index)
    state = 'CASH'
    entries = []  # (signal_date, entry_date, position, exposure)
    for me in month_ends:
        me = pd.Timestamp(me)
        if me not in close.index:
            continue
        zv = z.loc[me]
        if pd.isna(zv):
            entries.append((me, None, state, 0.0))
            continue
        if state == 'CASH':
            if zv > cfg['z_enter']:
                state = 'SI=F'
            elif zv < -cfg['z_enter']:
                state = 'GC=F'
        elif state == 'SI=F' and zv < 0:
            state = 'CASH'
        elif state == 'GC=F' and zv > 0:
            state = 'CASH'
        expo = 0.0
        if state in ('GC=F', 'SI=F'):
            rv = realized_vol.loc[me, state]
            if pd.notna(rv) and rv > 0:
                expo = min(1.0, cfg['vol_target'] / rv)
        idx = all_dates.index(me)
        entry_idx = min(idx + cfg['entry_lag_days'], len(all_dates) - 1)
        entries.append((me, all_dates[entry_idx], state, expo))
    latest_date = all_dates[-1]
    cur_pos, cur_expo, last_sig, last_entry = 'CASH', 0.0, None, None
    pending = None
    for (s, e, st, ex) in entries:
        if e is not None and e <= latest_date:
            cur_pos, cur_expo, last_sig, last_entry = st, float(ex), s, e
        elif e is not None and e > latest_date:
            pending = {'state': st, 'exposure': float(ex),
                       'signal_date': str(s.date()), 'entry_date': str(e.date())}
    return {
        'position': cur_pos, 'exposure': cur_expo,
        'signal_date': str(last_sig.date()) if last_sig is not None else None,
        'entry_date': str(last_entry.date()) if last_entry is not None else None,
        'pending': pending,
        'z_latest': float(z.iloc[-1]) if pd.notna(z.iloc[-1]) else None,
    }


def midpoint_percentile_strengths(metric_map):
    """Continuous 0-100 cross-sectional strength from a rank-metric map.

    strength = 100 * (N - avg_rank + 0.5) / N   (rank 1 = strongest metric)

    Midpoint percentile: the strongest ticker approaches but never equals 100,
    the weakest approaches but never equals 0, so the setups feed shows a
    continuous distribution with no mass at exactly 0/100. Ties share the
    average rank. Returns {} when no ticker has a valid metric (caller then
    leaves signal_strength NULL).
    """
    valid = [(t, float(v)) for t, v in metric_map.items()
             if v is not None and not pd.isna(v)]
    n = len(valid)
    if n == 0:
        return {}
    valid.sort(key=lambda kv: (-kv[1], kv[0]))
    out = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and valid[j + 1][1] == valid[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-based average rank across the tie block
        s = round(100.0 * (n - avg_rank + 0.5) / n, 2)
        for k in range(i, j + 1):
            out[valid[k][0]] = s
        i = j + 1
    return out


def absolute_strength_fallback(ticker, latest):
    """Degenerate cross-section (single rankable ticker, e.g. 'hold' strategies
    like GC=F/CASH): map risk-adjusted 12w momentum through tanh so strength is
    still continuous and centred at 50 instead of a fixed grid value."""
    ra = latest.get(ticker, {}).get('riskadj_12w')
    if ra is None or pd.isna(ra):
        ra = 0.0
    return round(50.0 + 49.0 * math.tanh(float(ra)), 2)


def generate_gs_ratio_rows(st, cfg):
    """Target-weight rows for the current state-machine position.

    Weights sum to 1 (chosen leg at fixed exposure, residual CASH) so the
    rebalancer's score normalisation reproduces the exposure exactly.

    signal_strength: continuous leg strengths from the ratio z-score,
    strength_SI = 100*Phi(z/z_enter), strength_GC = 100 - strength_SI
    (z > +z_enter favours the SI=F leg per the state machine).
    """
    pos, expo = st['position'], st['exposure']
    weights = {'CASH': 1.0, 'GC=F': 0.0, 'SI=F': 0.0}
    if pos in ('GC=F', 'SI=F') and expo > 0:
        weights[pos] = expo
        weights['CASH'] = 1.0 - expo
    z = st['z_latest'] if st['z_latest'] is not None else 0.0
    ze = cfg.get('z_enter', 2.0) or 2.0
    phi = 0.5 * (1.0 + math.erf((z / ze) / math.sqrt(2.0)))
    leg_strength = {'SI=F': round(100.0 * phi, 2)}
    leg_strength['GC=F'] = round(100.0 - leg_strength['SI=F'], 2)
    rows = []
    for t in ('CASH', 'GC=F', 'SI=F'):
        w = float(weights[t])
        if t == 'CASH':
            action = 'HOLD'
        elif w > 0:
            action = 'BUY'
        else:
            action = 'SELL'
        rows.append({'ticker': t, 'action': action, 'weight': w,
                     'score': float(st['z_latest'] or 0.0),
                     'strength': leg_strength.get(t)})
    return rows


VIX_STALE_DAYS = 10  # refuse to signal off a vix_z60 older than this

def vix_scaled_gld_sleeve_rows(conn, cfg):
    """etf_vix_scaled_11 run 3 (GLD defensive sleeve, denom 1.5) target rows.

    Signal logic mirrors research vix_sig(1.5, 0.3)
    (workspace/expansion_2026-08-06/expansion_pass3.py) exactly:
      eq = clip(1 - max(0, vix_z60)/1.5, 0, 1)
      eq <= 0.01 -> IEF 0.7 / GLD 0.3
      else       -> SPY 0.6*eq, QQQ 0.4*eq, IEF 0.7*(1-eq), GLD 0.3*(1-eq)
    vix_z60 comes from gold.vix_regime (60d rolling z of ^VIX close).
    Weights sum to 1 by construction, so normally no CASH row; a material
    rounding residual would be emitted as CASH with action HOLD (cash is an
    allocation, never a trade signal). score/entry_score carry weight*100
    (batch11 convention; rebalancer weight = score/total_score). Zero-weight
    defensive tickers are HOLD score 0, not SELL — they are standing
    allocations, not exits. Returns (rows, meta); rows=None when the VIX
    feed is missing/stale so the caller skips instead of writing garbage.
    """
    cur = conn.cursor()
    cur.execute("SELECT date, vix, vix_z60 FROM gold.vix_regime "
                "ORDER BY date DESC LIMIT 1")
    row = cur.fetchone()
    meta = {'engine': 'build_rotation_signals', 'custom': 'vix_scaled_gld_sleeve',
            'run_number': 3, 'kanban_task_id': 't_68846e9c',
            'logic': 'eq=clip(1-max(0,vix_z60)/1.5,0,1); SPY60/QQQ40; '
                     'defensive remainder 70/30 IEF/GLD'}
    if not row or row[2] is None:
        meta['error'] = 'gold.vix_regime empty or vix_z60 NULL'
        return None, meta
    vix_date, vix_level, z = row[0], float(row[1]), float(row[2])
    age_days = (datetime.now().date() - vix_date).days
    meta.update({'vix_date': str(vix_date), 'vix': vix_level, 'vix_z60': z})
    if age_days > VIX_STALE_DAYS:
        meta['error'] = f'vix_z60 stale ({age_days}d old, limit {VIX_STALE_DAYS}d)'
        return None, meta
    eq = min(1.0, max(0.0, 1.0 - max(0.0, z) / 1.5))
    if eq <= 0.01:
        weights = {'IEF': 0.7, 'GLD': 0.3}
    else:
        weights = {'SPY': 0.6 * eq, 'QQQ': 0.4 * eq,
                   'IEF': 0.7 * (1.0 - eq), 'GLD': 0.3 * (1.0 - eq)}
    meta['equity_weight'] = round(eq, 6)
    strengths = midpoint_percentile_strengths(weights)
    rows = []
    for t in cfg['universe']:
        w = float(weights.get(t, 0.0))
        rows.append({'ticker': t, 'action': 'BUY' if w > 0 else 'HOLD',
                     'weight': round(w * 100, 4), 'score': round(w * 100, 4),
                     'strength': strengths.get(t)})
    residual = round(1.0 - sum(weights.values()), 6)
    if residual > 0.0005:
        rows.append({'ticker': 'CASH', 'action': 'HOLD',
                     'weight': round(residual * 100, 4), 'score': 0.0,
                     'strength': None})
    return rows, meta


def tech_mom_gld_fallback_rows(conn, cfg):
    """etf_tech_mom_13 run 2 (GLD defensive fallback) target rows.

    Signal logic mirrors research sig_tech_gld
    (workspace/expansion_2026-08-06/expansion_pass3.py) exactly:
      - rank SMH/QQQ/XLK/IGV by 63d momentum (per-ticker dropna close
        series, needs >= 68 obs; mom = last / last-63 - 1), take top 2
      - each top-2 leg passing its 200d-SMA filter (len > 200 and
        last close > mean of last 200) gets 0.5; a failing leg goes
        0.25 IEF / 0.25 GLD (run 1 sent it 100% to IEF)
      - portfolio vol = std of 63d weighted daily returns * sqrt(252);
        lev = min(1.3, 0.15/pv) (1.0 when pv unusable); weights *= lev
    Prices from silver.unified_prices (dedup keep-last, same as the
    research batch10 loader), full history from 2017-06-01 as in the
    research frame. score/entry_score carry weight*100 (rebalancer
    weight = score/total_score). Leverage can take weights above 1
    (sum up to 1.3); a material positive residual is emitted as CASH
    with action HOLD. Zero-weight universe tickers are HOLD score 0,
    not SELL. Returns (rows, meta); rows=None when the signal cannot
    be computed so the caller skips instead of writing garbage.
    """
    tech4 = [t for t in cfg['universe'] if t not in ('IEF', 'GLD')]
    cur = conn.cursor()
    cur.execute("""SELECT date, ticker, close FROM silver.unified_prices
                   WHERE ticker = ANY(%s) AND date >= '2017-06-01'
                   ORDER BY date""", (list(cfg['universe']),))
    recs = cur.fetchall()
    meta = {'engine': 'build_rotation_signals', 'custom': 'tech_mom_gld_fallback',
            'run_number': 2, 'kanban_task_id': 't_68846e9c',
            'logic': 'top2(SMH,QQQ,XLK,IGV by mom63); 200d-SMA fail -> '
                     '50/50 IEF/GLD; vol target 0.15, lev cap 1.3'}
    if not recs:
        meta['error'] = 'silver.unified_prices empty for universe'
        return None, meta
    px = pd.DataFrame(recs, columns=['date', 'ticker', 'close'])
    px = px.sort_values(['ticker', 'date']).drop_duplicates(['ticker', 'date'], keep='last')
    close = px.pivot(index='date', columns='ticker', values='close').sort_index().astype(float)
    close.index = pd.to_datetime(close.index)
    d = close.index.max()
    meta['signal_date'] = str(d.date())
    # 63d momentum per candidate (mirrors batch10 mom(t, d, 63))
    moms = {}
    for t in tech4:
        if t not in close.columns:
            moms[t] = None
            continue
        s = close[t].loc[:d].dropna()
        moms[t] = float(s.iloc[-1] / s.iloc[-1 - 63] - 1) if len(s) >= 68 else None
    meta['mom63'] = {t: (round(v, 6) if v is not None else None) for t, v in moms.items()}
    ms = pd.Series({t: v for t, v in moms.items() if v is not None}).sort_values(ascending=False)
    top2 = list(ms.index[:2])
    meta['top2'] = top2
    if not top2:
        meta['error'] = 'no candidate has a computable 63d momentum'
        return None, meta
    out = {}
    sma_pass = {}
    for t in top2:
        s = close[t].loc[:d].dropna()
        ok = len(s) > 200 and s.iloc[-1] > s.tail(200).mean()
        sma_pass[t] = bool(ok)
        if ok:
            out[t] = out.get(t, 0) + 0.5
        else:
            out['IEF'] = out.get('IEF', 0) + 0.25
            out['GLD'] = out.get('GLD', 0) + 0.25
    meta['sma200_pass'] = sma_pass
    pr = (close[list(out)].pct_change().loc[:d].tail(63) * pd.Series(out)).sum(axis=1)
    pv = pr.std() * np.sqrt(252)
    lev = min(1.3, 0.15 / pv) if pv and pv > 0 else 1.0
    meta['portfolio_vol'] = round(float(pv), 6) if pv and not pd.isna(pv) else None
    meta['leverage'] = round(float(lev), 6)
    weights = {t: float(v * lev) for t, v in out.items()}
    strengths = midpoint_percentile_strengths(moms)
    rows = []
    for t in cfg['universe']:
        w = float(weights.get(t, 0.0))
        rows.append({'ticker': t, 'action': 'BUY' if w > 0 else 'HOLD',
                     'weight': round(w * 100, 4), 'score': round(w * 100, 4),
                     'strength': strengths.get(t)})
    residual = round(1.0 - sum(weights.values()), 6)
    if residual > 0.0005:
        rows.append({'ticker': 'CASH', 'action': 'HOLD',
                     'weight': round(residual * 100, 4), 'score': 0.0,
                     'strength': None})
    return rows, meta


def safe_haven_v2_rows(conn, cfg):
    """crisis_safe_haven_vt_19 (batch13 EXPERIMENTAL) target rows.

    Signal logic mirrors research sig_safe_haven_v2
    (workspace/batch13_2026-08-06/batch13_safehaven_v2.py) exactly:
      - rank GLD/TLT/IEF by 63d momentum (per-ticker dropna close series,
        needs >= n+5 obs; mom = last / last-n - 1), all-IEF if none rankable
      - top-2 get 0.6/0.4; each leg requires positive 252d momentum else
        that leg -> IEF (legs merge when one leg is already IEF)
      - portfolio vol = std of 63d weighted daily returns * sqrt(252);
        lev = min(1.5, 0.10/pv) (1.0 when pv unusable); when lev < 1.0 all
        weights scale by lev and the (1-lev) residual goes to IEF; when
        lev >= 1.0 weights are returned unscaled (no leverage-up, by design)
    Prices from silver.unified_prices (dedup keep-last, same as the research
    batch10 loader), full history from 2017-06-01 as in the research frame.
    score/entry_score carry weight*100 (batch11 convention; rebalancer
    weight = score/total_score). Zero-weight universe tickers are HOLD
    score 0, not SELL — they are standing allocations, not exits. A
    material positive residual (partial rank coverage) is emitted as CASH
    with action HOLD. Returns (rows, meta); rows=None when the signal
    cannot be computed so the caller skips instead of writing garbage.
    """
    cur = conn.cursor()
    cur.execute("""SELECT date, ticker, close FROM silver.unified_prices
                   WHERE ticker = ANY(%s) AND date >= '2017-06-01'
                   ORDER BY date""", (list(cfg['universe']),))
    recs = cur.fetchall()
    meta = {'engine': 'build_rotation_signals', 'custom': 'safe_haven_v2',
            'signal_fn': 'sig_safe_haven_v2', 'run_number': 1,
            'kanban_task_id': 't_ab33144a',
            'logic': 'top2(GLD,TLT,IEF by mom63) 60/40; leg needs mom252>0 '
                     'else IEF; vol target 0.10 (63d), lev cap 1.5, '
                     'residual -> IEF'}
    if not recs:
        meta['error'] = 'silver.unified_prices empty for universe'
        return None, meta
    px = pd.DataFrame(recs, columns=['date', 'ticker', 'close'])
    px = px.sort_values(['ticker', 'date']).drop_duplicates(['ticker', 'date'], keep='last')
    close = px.pivot(index='date', columns='ticker', values='close').sort_index().astype(float)
    close.index = pd.to_datetime(close.index)
    d = close.index.max()
    meta['signal_date'] = str(d.date())

    def mom(t, n):
        if t not in close.columns:
            return None
        s = close[t].loc[:d].dropna()
        if len(s) < n + 5:
            return None
        return float(s.iloc[-1] / s.iloc[-1 - n] - 1)

    mom63 = {t: mom(t, 63) for t in cfg['universe']}
    meta['mom63'] = {t: (round(v, 6) if v is not None else None) for t, v in mom63.items()}
    ms = pd.Series({t: v for t, v in mom63.items() if v is not None}).sort_values(ascending=False)
    if not len(ms):
        weights = {'IEF': 1.0}
        meta.update({'top2': [], 'leverage': None, 'portfolio_vol': None,
                     'fallback': 'no_rankable_momentum'})
    else:
        out = {}
        mom252_gate = {}
        for i, t in enumerate(ms.index[:2]):
            w = 0.6 if i == 0 else 0.4
            m252 = mom(t, 252)
            mom252_gate[t] = round(m252, 6) if m252 is not None else None
            k = t if (m252 is not None and m252 > 0) else 'IEF'
            out[k] = out.get(k, 0) + w
        meta['top2'] = list(ms.index[:2])
        meta['mom252'] = mom252_gate
        pr = (close[list(out)].pct_change().loc[:d].tail(63) * pd.Series(out)).sum(axis=1)
        pv = pr.std() * np.sqrt(252)
        lev = min(1.5, 0.10 / pv) if pv and pv > 0 else 1.0
        meta['portfolio_vol'] = round(float(pv), 6) if pv and not pd.isna(pv) else None
        meta['leverage'] = round(float(lev), 6)
        if lev < 1.0:
            weights = {**{t: float(v * lev) for t, v in out.items()},
                       'IEF': float(out.get('IEF', 0) * lev + (1 - lev))}
        else:
            weights = {t: float(v) for t, v in out.items()}
    strengths = midpoint_percentile_strengths(mom63)
    rows = []
    for t in cfg['universe']:
        w = float(weights.get(t, 0.0))
        rows.append({'ticker': t, 'action': 'BUY' if w > 0 else 'HOLD',
                     'weight': round(w * 100, 4), 'score': round(w * 100, 4),
                     'strength': strengths.get(t)})
    residual = round(1.0 - sum(weights.values()), 6)
    if residual > 0.0005:
        rows.append({'ticker': 'CASH', 'action': 'HOLD',
                     'weight': round(residual * 100, 4), 'score': 0.0,
                     'strength': None})
    return rows, meta


TREND_OVERLAY_RISK_PREF = {'SPY': ['US'], 'QQQ': ['US'],
                           'GLD': ['US', ''], 'TLT': ['US', '']}
TREND_OVERLAY_DEF = ('IEF', ['US'])
TREND_OVERLAY_LOOKBACK = 12 * 21  # 252 trading days, matches trend_overlay_finalize.py
TREND_OVERLAY_W_LEG = 0.25


def trend_overlay_mom12m_rows(conn, cfg):
    """etf_trend_overlay_mom12m_v1 (EXPERIMENTAL) target rows.

    Signal logic mirrors research trend_overlay_finalize.py exactly:
      - per-ticker market-preference dedup (research px(): SPY/QQQ/IEF prefer
        'US'; GLD/TLT prefer 'US' then ''); daily = 4-leg closes dropna();
        IEF reindexed to the risk calendar and ffilled; series trimmed to
        first valid IEF date
      - signal at month-end close t: leg risk-on iff close > close 252
        trading days ago; else leg -> IEF; IEF 12M momentum <= 0 -> CASH
      - new weights earn from t+1 (no same-bar application); weights stand
        until the next month-end, so the live target = weights set at the
        most recent month-end past the 252-day warmup
    Prices from silver.unified_prices — DB-backed, no signal-file dependency.
    score/entry_score carry weight*100 (batch11 convention; rebalancer
    weight = score/total_score). Zero-weight universe tickers are HOLD
    score 0, not SELL — they are standing allocations, not exits. CASH is a
    real allocation of this strategy (IEF risk-off) and is always emitted
    with action HOLD. Returns (rows, meta); rows=None when the signal cannot
    be computed so the caller skips instead of writing garbage.
    """
    meta = {'engine': 'build_rotation_signals', 'custom': 'trend_overlay_mom12m',
            'signal_fn': 'trend_overlay_finalize', 'run_number': 1,
            'kanban_task_id': 't_63a4a2b7',
            'logic': 'per-leg 25% SPY/QQQ/GLD/TLT risk-on iff mom252>0 at '
                     'month-end close else IEF; IEF mom252<=0 -> CASH; '
                     'signal t earns from t+1'}

    def px(ticker, pref):
        df = pd.read_sql(
            "SELECT date::date d, market, close FROM silver.unified_prices "
            "WHERE ticker=%s AND close IS NOT NULL ORDER BY date", conn,
            params=(ticker,))
        df['prio'] = df['market'].apply(lambda m: pref.index(m) if m in pref else 9)
        df = df.sort_values(['d', 'prio']).drop_duplicates('d', keep='first')
        return df.set_index(pd.to_datetime(df['d']))['close'].astype(float).sort_index()

    lb = TREND_OVERLAY_LOOKBACK
    daily = pd.DataFrame({t: px(t, p) for t, p in TREND_OVERLAY_RISK_PREF.items()})
    ief = px(TREND_OVERLAY_DEF[0], TREND_OVERLAY_DEF[1])
    daily = daily.dropna()
    if daily.empty:
        meta['error'] = 'silver.unified_prices empty for risk legs'
        return None, meta
    ief = ief.reindex(daily.index).ffill()
    daily = daily.loc[ief.dropna().index.min():]

    sig_risk = daily > daily.shift(lb)          # True = risk-on
    sig_ief = ief > ief.shift(lb)
    # month-end rebalance dates (last trading day of each month), warmup-gated
    me = [g.index[-1] for _, g in daily.resample('ME')]
    me_valid = [d for d in me if daily.index.get_loc(d) > lb]
    meta['price_latest'] = str(daily.index[-1].date())
    if not me_valid:
        meta['error'] = 'no month-end past 252-day warmup'
        return None, meta
    me_last = me_valid[-1]
    s = sig_risk.loc[me_last]
    s_ief = bool(sig_ief.loc[me_last])
    w = {t: 0.0 for t in list(TREND_OVERLAY_RISK_PREF) + ['IEF', 'CASH']}
    for t in TREND_OVERLAY_RISK_PREF:
        if bool(s[t]):
            w[t] = TREND_OVERLAY_W_LEG
        elif s_ief:
            w['IEF'] += TREND_OVERLAY_W_LEG
        else:
            w['CASH'] += TREND_OVERLAY_W_LEG
    mom252 = {t: float(daily[t].loc[me_last] / daily[t].shift(lb).loc[me_last] - 1)
              for t in TREND_OVERLAY_RISK_PREF}
    mom252['IEF'] = float(ief.loc[me_last] / ief.shift(lb).loc[me_last] - 1)
    meta.update({'signal_date': str(me_last.date()),
                 'mom252': {t: round(v, 6) for t, v in mom252.items()},
                 'ief_risk_on': s_ief,
                 'weights': {t: round(v, 6) for t, v in w.items()}})
    strengths = midpoint_percentile_strengths(mom252)
    rows = []
    for t in cfg['universe']:
        wt = float(w.get(t, 0.0))
        action = 'HOLD' if t == 'CASH' else ('BUY' if wt > 0 else 'HOLD')
        rows.append({'ticker': t, 'action': action,
                     'weight': round(wt * 100, 4), 'score': round(wt * 100, 4),
                     'strength': strengths.get(t)})
    return rows, meta


COMM_TREND_COMM5 = ['GLD', 'SLV', 'DBC', 'USO', 'UNG']


def comm_trend_tsmom_rows(conn, cfg):
    """etf_comm_trend_basket_15 target rows.

    Signal logic mirrors research sig_c2
    (workspace/batch12_2026-08-05/batch12_backtest.py, helpers from
    batch10_backtest.py) exactly:
      - decision date = most recent COMPLETED month-end (last trading day
        of a fully-elapsed month; the current partial month is never used,
        so weights stand intra-month and the research 1-period lag — signal
        at month-end close t earns from t+1 — is reproduced live)
      - sel = COMM5 tickers with mom252 > 0 (per-ticker dropna close series
        .loc[:d], needs >= 252+5 obs; mom = last / last-252 - 1); missing /
        short history excludes the leg (research `(mom or -1) > 0`)
      - no positive-momentum leg (or no usable vol) -> IEF 1.0 (all-out)
      - weights = inverse vol63 (vol63 = close[t].loc[:d].pct_change()
        .tail(63).std() * sqrt(252), needs len > 30), normalised over sel
      - pv = std of 63d weighted portfolio daily returns * sqrt(252);
        lev = min(1.5, 0.10/pv) (1.0 when pv unusable); weights *= lev;
        the (1 - lev) residual is implicit CASH (research keeps it as cash,
        NOT IEF — only a full all-out routes to IEF)
    Prices from silver.unified_prices, dedup keep-last on (ticker, date)
    sorted by (ticker, date), same as the research batch10 loader.
    score/entry_score carry weight*100 (batch11 convention; rebalancer
    weight = score/total_score). Zero-weight universe tickers are HOLD
    score 0, not SELL — they are standing allocations, not exits. The CASH
    residual is emitted as a HOLD row so the rebalancer's budget respects
    the undeployed fraction. Returns (rows, meta); rows=None when the
    signal cannot be computed so the caller skips instead of writing
    garbage.
    """
    meta = {'engine': 'build_rotation_signals', 'custom': 'comm_trend_tsmom',
            'signal_fn': 'sig_c2', 'run_number': 1,
            'kanban_task_id': 't_84d61124',
            'logic': 'COMM5 12M TSMOM (hold iff mom252>0), inv-vol63 '
                     'weights, lev=min(1.5, 0.10/pv63), residual -> CASH, '
                     'all-out -> IEF; monthly (completed month-end)'}
    tickers = list(COMM_TREND_COMM5) + ['IEF']
    px = pd.read_sql(
        "SELECT date, ticker, close FROM silver.unified_prices "
        "WHERE ticker = ANY(%s) AND date >= '2017-06-01' ORDER BY date",
        conn, params=(tickers,))
    if px.empty:
        meta['error'] = 'silver.unified_prices empty for universe'
        return None, meta
    px = px.sort_values(['ticker', 'date']).drop_duplicates(['ticker', 'date'], keep='last')
    close = px.pivot(index='date', columns='ticker', values='close').sort_index().astype(float)
    close.index = pd.to_datetime(close.index)
    latest = close.index.max()
    meta['price_latest'] = str(latest.date())

    # Completed month-ends only: group (year, month) max, drop the group of
    # the latest date's own month (partial or not-yet-confirmed month-end).
    s = pd.Series(close.index, index=close.index)
    me = [pd.Timestamp(d) for d in s.groupby([s.index.year, s.index.month]).max()]
    me_completed = [d for d in me if (d.year, d.month) < (latest.year, latest.month)]
    if not me_completed:
        meta['error'] = 'no completed month-end in price history'
        return None, meta
    d = me_completed[-1]
    meta['signal_date'] = str(d.date())

    def mom(t, n):
        if t not in close.columns:
            return None
        ser = close[t].loc[:d].dropna()
        if len(ser) < n + 5:
            return None
        return float(ser.iloc[-1] / ser.iloc[-1 - n] - 1)

    def vol63(t):
        if t not in close.columns:
            return None
        r = close[t].loc[:d].pct_change().tail(63)
        if len(r) <= 30:
            return None
        v = r.std() * np.sqrt(252)
        return float(v) if not pd.isna(v) else None

    mom252 = {t: mom(t, 252) for t in COMM_TREND_COMM5}
    meta['mom252'] = {t: (round(v, 6) if v is not None else None) for t, v in mom252.items()}
    sel = [t for t in COMM_TREND_COMM5 if (mom252[t] if mom252[t] is not None else -1) > 0]
    meta['selected'] = sel
    if not sel:
        weights = {'IEF': 1.0}
        meta.update({'leverage': None, 'portfolio_vol': None, 'fallback': 'all_out_to_ief'})
    else:
        vols = {t: vol63(t) for t in sel}
        meta['vol63'] = {t: (round(v, 6) if v is not None else None) for t, v in vols.items()}
        iv = {t: 1.0 / v for t, v in vols.items() if v is not None and v > 0}
        if not iv:
            weights = {'IEF': 1.0}
            meta.update({'leverage': None, 'portfolio_vol': None, 'fallback': 'no_usable_vol_to_ief'})
        else:
            tot = sum(iv.values())
            w = {t: v / tot for t, v in iv.items()}
            pr = (close[list(w)].pct_change().loc[:d].tail(63) * pd.Series(w)).sum(axis=1)
            pv = pr.std() * np.sqrt(252)
            lev = min(1.5, 0.10 / pv) if pv and pv > 0 else 1.0
            meta['portfolio_vol'] = round(float(pv), 6) if pv and not pd.isna(pv) else None
            meta['leverage'] = round(float(lev), 6)
            weights = {t: float(v * lev) for t, v in w.items()}
    meta['weights'] = {t: round(v, 6) for t, v in weights.items()}

    strengths = midpoint_percentile_strengths(mom252)
    rows = []
    for t in cfg['universe']:
        wt = float(weights.get(t, 0.0))
        rows.append({'ticker': t, 'action': 'BUY' if wt > 0 else 'HOLD',
                     'weight': round(wt * 100, 4), 'score': round(wt * 100, 4),
                     'strength': strengths.get(t)})
    residual = round(1.0 - sum(weights.values()), 6)
    if residual > 0.0005:
        rows.append({'ticker': 'CASH', 'action': 'HOLD',
                     'weight': round(residual * 100, 4), 'score': 0.0,
                     'strength': None})
    return rows, meta


def trend_voltarget_daily_rows(conn, cfg):
    """Single-asset daily trend + vol-target rows (COMM_Gold_Trend_VolTarget
    lb63_vt10, t_7ea489c0; generic via cfg keys for the gapdaily 2026-08-18
    family).

    Signal logic mirrors research w_trend_voltarget
    (qr_research workspace/gapdaily_2026-08-18/gapdaily_backtest.py)
    exactly, evaluated point-in-time at the latest close:
      mom  = close / close.shift(mom_lookback) - 1
      vol  = close.pct_change().rolling(vol_lookback).std(ddof=1)*sqrt(252)
      expo = min(1, vol_target / vol) when mom > 0 else 0
    A mom > 0 with unusable vol resolves to expo 0, matching the backtest
    (NaN target weight -> fillna(0.0) in simulate()). The research 1-bar
    execution lag is reproduced by the paper engine's NEXT_OPEN pending
    orders (signal_date = latest bar date, settle at the next bar open).
    Prices come from fetch_prices_deduped (market labels combined, dedupe
    by date preferring GLOBAL) — identical to the research load_prices()
    loader for futures.

    Row convention (batch11): weight and entry_score carry weight*100; the
    rebalancer's weight = score/total_score, and the CASH row's DB score
    (its weight) counts in total_score so the undeployed fraction is
    respected. A zero-exposure asset ticker is HOLD score 0 (standing
    allocation, not an exit); CASH is always HOLD. signal_strength is a
    continuous UI-facing tanh map of risk-adjusted momentum centred at 50.
    Returns (rows, meta); rows=None when the price history is unusable so
    the caller skips instead of writing garbage.
    """
    t = cfg['asset_ticker']
    mom_lb = cfg['mom_lookback']
    vol_lb = cfg['vol_lookback']
    vt = cfg['vol_target']
    meta: dict = {'engine': 'build_rotation_signals', 'custom': 'trend_voltarget_daily',
            'signal_fn': 'w_trend_voltarget',
            'kanban_task_id': 't_7ea489c0',
            'logic': f'long {t} iff mom{mom_lb}>0 else CASH; '
                     f'expo=min(1, {vt}/vol{vol_lb}d) point-in-time; daily, '
                     '1-bar execution lag via NEXT_OPEN pending orders'}
    close_df = fetch_prices_deduped(conn, [t])
    if close_df.empty or t not in close_df.columns:
        meta['error'] = f'silver.unified_prices empty for {t}'
        return None, meta
    c = close_df[t].dropna()
    need = mom_lb + vol_lb + 5
    if len(c) < need:
        meta['error'] = f'insufficient history for {t}: {len(c)} rows < {need}'
        return None, meta
    d = c.index[-1]
    mom = float(c.iloc[-1] / c.iloc[-1 - mom_lb] - 1)
    vol = float(c.pct_change().rolling(vol_lb).std(ddof=1).iloc[-1] * math.sqrt(252))
    vol_ok = not math.isnan(vol) and vol > 0
    expo = min(1.0, vt / vol) if (mom > 0 and vol_ok) else 0.0
    meta.update({'signal_date': str(pd.Timestamp(d).date()),
                 'price_latest': str(pd.Timestamp(d).date()),
                 'mom': round(mom, 6),
                 'realized_vol': round(vol, 6) if vol_ok else None,
                 'exposure': round(expo, 6),
                 'mom_lookback': mom_lb, 'vol_target': vt,
                 'vol_lookback': vol_lb})
    strength = None
    if vol_ok:
        strength = round(50.0 + 49.0 * math.tanh(mom / vol), 2)
    w = round(expo * 100, 4)
    rows = [
        {'ticker': t, 'action': 'BUY' if expo > 0 else 'HOLD',
         'weight': w, 'score': w, 'strength': strength},
        {'ticker': 'CASH', 'action': 'HOLD',
         'weight': round((1.0 - expo) * 100, 4), 'score': 0.0,
         'strength': None},
    ]
    return rows, meta


def country_rot_x14_rows(conn, cfg):
    """etf_country_rot_10_v2 run 2 (14-ETF universe) target rows.

    Signal logic mirrors research sig_country_x14
    (workspace/expansion2_2026-08-06/expansion2_backtest.py) exactly:
      - rank the 14 country ETFs by 63d momentum (batch10 mom(t, d, 63):
        per-ticker dropna close series, needs >= n+5 obs;
        mom = last / last-n - 1), take top 2, 0.5 each
      - each leg requires positive 252d momentum else that leg -> IEF
        (None/0/negative mom252 all route to IEF, legs merge in IEF)
      - portfolio vol = std of 63d weighted daily returns * sqrt(252);
        lev = min(1.3, 0.12/pv) (1.0 when pv unusable); weights *= lev
      - no rankable momentum -> empty target (all CASH)
    Prices from silver.unified_prices (dedup keep-last, same as the
    research batch10 loader), full history from 2017-06-01 as in the
    research frame. score/entry_score carry weight*100 (batch11
    convention; rebalancer weight = score/total_score). Leverage can
    take weights above 1 (sum up to 1.3); a material positive residual
    is emitted as CASH with action HOLD. Zero-weight universe tickers
    are HOLD score 0, not SELL. Returns (rows, meta); rows=None when
    the signal cannot be computed so the caller skips instead of
    writing garbage.
    """
    cur = conn.cursor()
    cur.execute("""SELECT date, ticker, close FROM silver.unified_prices
                   WHERE ticker = ANY(%s) AND date >= '2017-06-01'
                   ORDER BY date""", (list(cfg['universe']),))
    recs = cur.fetchall()
    meta = {'engine': 'build_rotation_signals', 'custom': 'country_rot_x14',
            'signal_fn': 'sig_country_x14', 'run_number': 2,
            'kanban_task_id': 't_55cedb93',
            'logic': 'top2(14 country ETFs by mom63) 50/50; leg needs '
                     'mom252>0 else IEF; vol target 0.12 (63d), lev cap 1.3'}
    if not recs:
        meta['error'] = 'silver.unified_prices empty for universe'
        return None, meta
    px = pd.DataFrame(recs, columns=['date', 'ticker', 'close'])
    px = px.sort_values(['ticker', 'date']).drop_duplicates(['ticker', 'date'], keep='last')
    close = px.pivot(index='date', columns='ticker', values='close').sort_index().astype(float)
    close.index = pd.to_datetime(close.index)
    d = close.index.max()
    meta['signal_date'] = str(d.date())

    def mom(t, n):
        if t not in close.columns:
            return None
        s = close[t].loc[:d].dropna()
        if len(s) < n + 5:
            return None
        return float(s.iloc[-1] / s.iloc[-1 - n] - 1)

    cand = [t for t in cfg['universe'] if t != 'IEF']
    mom63 = {t: mom(t, 63) for t in cand}
    meta['mom63'] = {t: (round(v, 6) if v is not None else None) for t, v in mom63.items()}
    ms = pd.Series({t: v for t, v in mom63.items() if v is not None}).sort_values(ascending=False)
    out = {}
    mom252_gate = {}
    for t in ms.index[:2]:
        m252 = mom(t, 252)
        mom252_gate[t] = round(m252, 6) if m252 is not None else None
        k = t if (m252 is not None and m252 > 0) else 'IEF'
        out[k] = out.get(k, 0) + 0.5
    meta['top2'] = list(ms.index[:2])
    meta['mom252'] = mom252_gate
    if out:
        pr = (close[list(out)].pct_change().loc[:d].tail(63) * pd.Series(out)).sum(axis=1)
        pv = pr.std() * np.sqrt(252)
        lev = min(1.3, 0.12 / pv) if pv and pv > 0 else 1.0
        meta['portfolio_vol'] = round(float(pv), 6) if pv and not pd.isna(pv) else None
        meta['leverage'] = round(float(lev), 6)
        weights = {t: float(v * lev) for t, v in out.items()}
    else:
        meta.update({'leverage': None, 'portfolio_vol': None,
                     'fallback': 'no_rankable_momentum'})
        weights = {}
    strengths = midpoint_percentile_strengths(mom63)
    rows = []
    for t in cfg['universe']:
        w = float(weights.get(t, 0.0))
        rows.append({'ticker': t, 'action': 'BUY' if w > 0 else 'HOLD',
                     'weight': round(w * 100, 4), 'score': round(w * 100, 4),
                     'strength': strengths.get(t)})
    residual = round(1.0 - sum(weights.values()), 6)
    if residual > 0.0005:
        rows.append({'ticker': 'CASH', 'action': 'HOLD',
                     'weight': round(residual * 100, 4), 'score': 0.0,
                     'strength': None})
    return rows, meta

DEF_SECTOR_ROT_DEF4 = ['SPY', 'XLU', 'XLP', 'XLV']

def def_sector_rot_w_rows(conn, cfg):
    """etf_def_sector_rot_12_w (batch11 EXPERIMENTAL) target rows.

    Signal logic mirrors research sig_e7
    (workspace/batch11_2026-08-05/batch11_backtest.py, helpers from
    batch10_backtest.py) exactly:
      - decision date = last trading day of the most recent COMPLETED ISO
        week (elapsed per wall clock, or Friday close already in the DB);
        weights stand intra-week so the research 1-period lag — signal at
        week-end close t earns from t+1 — is reproduced live
      - rank SPY/XLU/XLP/XLV by 63d momentum (batch10 mom(t, d, 63):
        per-ticker dropna close series .loc[:d], needs >= n+5 obs;
        mom = last / last-n - 1), take top 2, 0.5 each
      - each leg requires positive 252d momentum (research
        `(mom or -1) > 0`: None/NaN/non-positive all fail) else that
        leg -> IEF; legs merge in IEF (both fail -> IEF 1.0)
      - no rankable momentum -> empty target (research {} -> all CASH)
    Prices from silver.unified_prices, dedup keep-last on (ticker, date)
    sorted by (ticker, date), same as the research batch10 loader, full
    history from 2017-06-01 as in the research frame.
    score/entry_score carry weight*100 (batch11 convention; rebalancer
    weight = score/total_score). Zero-weight universe tickers are HOLD
    score 0, not SELL — they are standing allocations, not exits.
    Returns (rows, meta); rows=None when the signal cannot be computed so
    the caller skips instead of writing garbage.
    """
    meta = {'engine': 'build_rotation_signals', 'custom': 'def_sector_rot_w',
            'signal_fn': 'sig_e7', 'run_number': 1,
            'kanban_task_id': 't_d733f4c4',
            'logic': 'top2(SPY,XLU,XLP,XLV by mom63) 50/50; leg needs '
                     'mom252>0 else IEF; weekly (completed ISO week-end)'}
    px = pd.read_sql(
        "SELECT date, ticker, close FROM silver.unified_prices "
        "WHERE ticker = ANY(%s) AND date >= '2017-06-01' ORDER BY date",
        conn, params=(list(cfg['universe']),))
    if px.empty:
        meta['error'] = 'silver.unified_prices empty for universe'
        return None, meta
    px = px.sort_values(['ticker', 'date']).drop_duplicates(['ticker', 'date'], keep='last')
    close = px.pivot(index='date', columns='ticker', values='close').sort_index().astype(float)
    close.index = pd.to_datetime(close.index)
    meta['price_latest'] = str(close.index.max().date())

    # Completed ISO week-ends: group (iso_year, iso_week) max; a group
    # qualifies once the wall clock is in a later ISO week, or its last
    # trading day in the DB is a Friday (normal US week-end, close in).
    s = pd.Series(close.index, index=close.index)
    iso = close.index.isocalendar()
    groups = s.groupby([iso['year'].values, iso['week'].values]).max()
    cur_y, cur_w, _ = datetime.now().date().isocalendar()
    cand = [pd.Timestamp(dmax) for (y, w), dmax in groups.items()
            if (y, w) < (cur_y, cur_w) or pd.Timestamp(dmax).weekday() == 4]
    if not cand:
        meta['error'] = 'no completed ISO week-end in price history'
        return None, meta
    d = max(cand)
    meta['signal_date'] = str(d.date())

    def mom(t, n):
        if t not in close.columns:
            return None
        ser = close[t].loc[:d].dropna()
        if len(ser) < n + 5:
            return None
        return float(ser.iloc[-1] / ser.iloc[-1 - n] - 1)

    mom63 = {t: mom(t, 63) for t in DEF_SECTOR_ROT_DEF4}
    meta['mom63'] = {t: (round(v, 6) if v is not None else None) for t, v in mom63.items()}
    ms = pd.Series({t: v for t, v in mom63.items() if v is not None}).sort_values(ascending=False)
    weights = {}
    mom252_gate = {}
    for t in ms.index[:2]:
        m252 = mom(t, 252)
        mom252_gate[t] = round(m252, 6) if m252 is not None else None
        k = t if (m252 is not None and m252 > 0) else 'IEF'
        weights[k] = weights.get(k, 0) + 0.5
    meta['top2'] = list(ms.index[:2])
    meta['mom252'] = mom252_gate
    meta['weights'] = {t: round(v, 6) for t, v in weights.items()}
    if not weights:
        meta['fallback'] = 'no_rankable_momentum_to_cash'

    strengths = midpoint_percentile_strengths(mom63)
    rows = []
    for t in cfg['universe']:
        w = float(weights.get(t, 0.0))
        rows.append({'ticker': t, 'action': 'BUY' if w > 0 else 'HOLD',
                     'weight': round(w * 100, 4), 'score': round(w * 100, 4),
                     'strength': strengths.get(t)})
    residual = round(1.0 - sum(weights.values()), 6)
    if not weights or residual > 0.0005:
        rows.append({'ticker': 'CASH', 'action': 'HOLD',
                     'weight': round((residual if weights else 1.0) * 100, 4),
                     'score': 0.0, 'strength': None})
    return rows, meta

def insert_score_rows(cur, sid, rows, extra_meta, position_status):
    """Delete + reinsert this strategy's computed rows (engine convention)."""
    cur.execute("DELETE FROM gold.strategy_ticker_scores WHERE strategy_id = %s", (sid,))
    for r in rows:
        cur.execute("""INSERT INTO gold.strategy_ticker_scores
            (strategy_id, ticker, score, signal_action, entry_score, exit_score,
             criteria_met, position_status, deployed_at, updated_at, signal_source,
             signal_strength)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, NOW(), NOW(), %s, %s)""",
            (sid, r['ticker'], r['weight'], r['action'], r['score'], 0.0,
             json.dumps(extra_meta),
             position_status,
             'computed',
             r.get('strength')))


def compute_metrics(df):
    """Add return/vol metrics per ticker; robust to missing close values."""
    df = df.sort_values(['ticker','date']).copy()
    # Drop rows with missing close before computing rolling metrics
    df = df.dropna(subset=['close'])
    # Compute metrics per ticker on clean data
    for weeks, days in LOOKBACKS.items():
        df[f'return_{weeks}'] = df.groupby('ticker')['close'].transform(lambda x: x.pct_change(days))
    df['vol_12w'] = df.groupby('ticker')['close'].transform(
        lambda x: np.log(x / x.shift(1)).rolling(63, min_periods=30).std() * np.sqrt(252))
    df['sma_26w'] = df.groupby('ticker')['close'].transform(lambda x: x.rolling(126, min_periods=60).mean())
    df['sma_50w'] = df.groupby('ticker')['close'].transform(lambda x: x.rolling(252, min_periods=120).mean())
    df['sma_126d'] = df['sma_26w']
    df['riskadj_12w'] = df['return_12w'] / df['vol_12w'].replace(0, np.nan)
    df['riskadj_26w'] = df['return_26w'] / df['vol_12w'].replace(0, np.nan)
    df['riskadj_12m'] = df['return_12m'] / df['vol_12w'].replace(0, np.nan)
    df['above_26w_sma'] = df['close'] > df['sma_26w']
    df['above_50w_sma'] = df['close'] > df['sma_50w']
    df['above_126d_sma'] = df['above_26w_sma']
    # Composite momentum rank (OVERLAY_RESTATE_DECISION_MEMO §6, 2026-10-18):
    # per-row mean of the four CALENDAR-day returns. Behind a config switch —
    # live stays momentum_12w until the user cuts over (decision 2026-10-31).
    df['composite_30_91_182_365d'] = np.nan
    for t, g in df.groupby('ticker'):
        px = g.set_index('date')['close'].sort_index()
        vals = {D: composite_30_91_182_365d_score(px, D) for D in px.index}
        df.loc[g.index, 'composite_30_91_182_365d'] = (
            pd.Series(vals).reindex(g['date'].values).values)
    return df


COMPOSITE_LOOKBACK_DAYS = (30, 91, 182, 365)


def composite_30_91_182_365d_score(px, D):
    """Composite momentum at date D: mean of the 30/91/182/365 CALENDAR-day
    returns using ON-OR-BEFORE closes (px.asof). px = close Series indexed by
    date, sorted. ALL FOUR lookbacks must resolve or the score is NaN —
    matches the authoritative definition (qr_research
    sector_mom_composite_rerun.py composite_row: a lookback is never
    fabricated and never dropped).
    Rank-function hash (sha256 of this function's source) is recorded per the
    signal-definition-hash spec at cutover."""
    rets = []
    for k in COMPOSITE_LOOKBACK_DAYS:
        ref = px.asof(D - pd.Timedelta(days=k))
        if pd.isna(ref) or ref <= 0:
            return np.nan
        rets.append(px.loc[D] / ref - 1.0)
    return sum(rets) / len(rets)


def latest_values(df, tickers):
    """Return dict of latest metrics per ticker."""
    # Use the overall latest date in the dataset; tickers with stale data will not be in latest
    overall_max = df['date'].max()
    latest = df[df['date'] == overall_max].groupby('ticker').last().to_dict('index')
    # fallback: if a ticker is not on the latest date, use its last available row
    last_per_ticker = df.groupby('ticker').last().to_dict('index')
    out = {}
    for t in tickers:
        if t == 'CASH':
            out[t] = {'close': 1.0, 'return_12w': 0.0, 'return_13w': 0.0, 'return_26w': 0.0,
                      'return_12m': 0.0, 'vol_12w': 0.0, 'above_26w_sma': True, 'above_50w_sma': True,
                      'above_126d_sma': True, 'riskadj_12w': 0.0, 'riskadj_26w': 0.0, 'riskadj_12m': 0.0,
                      'return_1w': 0.0}
        else:
            d = latest.get(t)
            if d is None:
                d = last_per_ticker.get(t, {})
            out[t] = d
    return out


def regime_filter_ok(cfg, latest, spy, hyg, agg, tlt, ief, gld, hk2800):
    """Return True if strategy-specific regime filter passes."""
    f = cfg.get('filter')
    if f is None:
        return True
    if f == 'spy_26w_sma':
        return bool(spy.get('above_26w_sma', False))
    if f == 'spy_50w_sma':
        return bool(spy.get('above_50w_sma', False))
    if f == 'spy_26w_sma_gld':
        return bool(spy.get('above_26w_sma', False)) and bool(gld.get('return_13w', 0) > 0)
    if f == 'spy_26w_sma_hy':
        hyg_agg = (hyg.get('return_13w', 0) - agg.get('return_13w', 0)) if hyg and agg else 0
        return bool(spy.get('above_26w_sma', False)) and bool(hyg_agg > 0)
    if f == 'spy_26w_sma_rates':
        tlt_ief = (tlt.get('return_13w', 0) + ief.get('return_13w', 0)) / 2 if tlt and ief else 0
        return bool(spy.get('above_26w_sma', False)) and bool(tlt_ief > 0)
    if f == 'hk2800_126d':
        return bool(hk2800.get('above_126d_sma', False)) and bool(hk2800.get('return_26w', 0) > 0)
    return True


def rank_tickers(cfg, latest, tickers):
    """Return sorted list of (ticker, score)."""
    rank = cfg['rank']
    scores = []
    for t in tickers:
        if t == 'CASH':
            continue
        d = latest.get(t, {})
        if rank == 'momentum_12w':
            score = d.get('return_12w', np.nan)
        elif rank == 'momentum_13w':
            score = d.get('return_13w', np.nan)
        elif rank == 'momentum_26w':
            score = d.get('return_26w', np.nan)
        elif rank == 'riskadj_momentum_12w':
            score = d.get('riskadj_12w', np.nan)
        elif rank == 'riskadj_momentum_26w':
            score = d.get('riskadj_26w', np.nan)
        elif rank == 'riskadj_26w_positive_momentum':
            # 26w risk-adjusted momentum, only among names with positive 12w momentum
            score = d.get('riskadj_26w', np.nan) if d.get('return_12w', 0) > 0 else np.nan
        elif rank == 'riskadj_momentum_12m':
            score = d.get('riskadj_12m', np.nan)
        elif rank == 'lowvol_63d':
            score = -d.get('vol_12w', np.nan)  # lower vol = higher score
        elif rank == 'lowvol_63d_positive_momentum':
            score = -d.get('vol_12w', np.nan) if d.get('return_12w', 0) > 0 else np.nan
        elif rank == 'lowvol_positive_momentum':
            score = -d.get('vol_12w', np.nan) if d.get('return_12w', 0) > 0 else np.nan
        elif rank == 'momentum_12w_vol':
            score = d.get('return_12w', np.nan) / (d.get('vol_12w', np.nan) + 1e-6)
        elif rank == 'composite_30_91_182_365d':
            # OVERLAY_RESTATE_DECISION_MEMO §6: mean of 30/91/182/365
            # calendar-day returns, on-or-before closes. Behind the sleeve's
            # strategy_configs rank switch — default OFF (momentum_12w).
            score = d.get('composite_30_91_182_365d', np.nan)
        elif rank == 'inverse_vol_12w':
            score = 1.0 / (d.get('vol_12w', np.nan) + 1e-6)
        elif rank == 'hold':
            score = 0.0
        else:
            score = np.nan
        if not pd.isna(score):
            scores.append((t, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores


def compute_weights(cfg, selected, latest):
    """Return dict ticker->target weight."""
    if not selected:
        return {'CASH': 1.0}
    weight = cfg.get('weight', 'equal')
    if weight == 'equal':
        # cash_residual (e.g. 0.10): scale sleeves to (1 - residual) and park
        # the remainder in CASH — mirrors the research handoff book.
        residual = float(cfg.get('cash_residual', 0.0) or 0.0)
        w = (1.0 - residual) / len(selected)
        out = {t: w for t in selected}
        if residual > 0:
            out['CASH'] = residual
        return out
    if weight == 'winner_takes_all':
        return {selected[0]: 1.0}
    if weight == 'inverse_vol':
        vols = {t: max(latest.get(t, {}).get('vol_12w', 0.05) or 0.05, 1e-6) for t in selected}
        inv = {t: 1.0 / v for t, v in vols.items()}
        total = sum(inv.values())
        return {t: inv[t] / total for t in selected}
    if weight == 'risk_parity_voltarget':
        # inverse vol, scaled to target vol
        vols = {t: latest.get(t, {}).get('vol_12w', 0.05) for t in selected}
        inv_vol = {t: 1.0 / max(v, 1e-6) for t, v in vols.items()}
        total = sum(inv_vol.values())
        raw = {t: v / total for t, v in inv_vol.items()}
        # scale to target vol (10%) / portfolio vol
        port_vol = sum((raw[t] * vols[t]) ** 2 for t in selected) ** 0.5
        target = cfg.get('target_vol', 0.10)
        scale = min(target / max(port_vol, 1e-6), 1.0)
        return {t: raw[t] * scale for t in selected}
    return {t: 1.0 / len(selected) for t in selected}


def generate_signals(cfg, latest, spy, hyg, agg, tlt, ief, gld, hk2800):
    """Return list of dicts for strategy_ticker_scores."""
    universe = cfg.get('universe', [])
    no_data = set()  # tickers present but with insufficient history for ranking
    metric_map = {}  # ticker -> raw rank metric (pre-normalisation), for strength
    # filter
    regime_ok = regime_filter_ok(cfg, latest, spy, hyg, agg, tlt, ief, gld, hk2800)
    # handle special sleeves
    if 'sleeves' in cfg:
        selected = []
        sleeve_n = cfg.get('sleeve_top_n', 1)
        for sleeve in cfg['sleeves']:
            sleeve_tickers = [t for t in sleeve if t in universe and t in latest]
            scores = rank_tickers({**cfg, 'rank': cfg['rank']}, latest, sleeve_tickers)
            metric_map.update(dict(scores))
            selected.extend(t for t, s in scores[:sleeve_n])
        weights = compute_weights({**cfg, 'weight': 'equal'}, selected, latest)
    elif cfg.get('rank') == 'hold':
        # special cases: hold first ticker if filter passes, else cash
        hold_candidates = [t for t in universe if t in latest and t != 'CASH']
        metric_map.update(dict(rank_tickers(cfg, latest, hold_candidates)))
        if regime_ok and universe and universe[0] != 'CASH':
            weights = {universe[0]: 1.0}
        else:
            weights = {'CASH': 1.0}
    else:
        # Rank the full universe regardless of the regime gate so SELL rows
        # (regime fail or zero weight) still get a continuous strength score.
        available = [t for t in universe if t in latest and t != 'CASH']
        scores = rank_tickers(cfg, latest, available)
        metric_map.update(dict(scores))
        no_data = set(available) - {t for t, s in scores}
        if not regime_ok:
            weights = {'CASH': 1.0}
        else:
            top_n = cfg['top_n']
            if top_n == 'all':
                selected = [t for t, s in scores]
            else:
                selected = [t for t, s in scores[:top_n]]
            # per-ticker negative-momentum drop: exit rule "drop if momentum < 0"
            if cfg.get('cash_if_negative'):
                score_map = dict(scores)
                kept = [t for t in selected if (score_map.get(t) or 0) >= 0]
                dropped = [t for t in selected if t not in kept]
                if not kept:
                    weights = {'CASH': 1.0}
                elif cfg.get('drop_to_cash'):
                    # registry logic: dropped names' weight moves to CASH;
                    # kept names stay at their 1/top_n equal weight
                    w = 1.0 / cfg['top_n']
                    weights = {t: w for t in kept}
                    weights['CASH'] = 1.0 - w * len(kept)
                else:
                    weights = compute_weights(cfg, kept, latest)
                    if dropped:
                        cash_w = max(0.0, 1.0 - sum(weights.values()))
                        weights['CASH'] = cash_w
            else:
                weights = compute_weights(cfg, selected, latest)
    # continuous 0-100 cross-sectional strength from the rank metric
    strengths = midpoint_percentile_strengths(metric_map)
    n_valid = sum(1 for v in metric_map.values() if v is not None and not pd.isna(v))
    if n_valid == 1:
        # degenerate cross-section (single rankable ticker): absolute fallback
        only_t = next(t for t, v in metric_map.items() if v is not None and not pd.isna(v))
        strengths[only_t] = absolute_strength_fallback(only_t, latest)
    # ensure all universe members get a row
    all_tickers = set(universe) | set(weights.keys()) | {'CASH'}
    rows = []
    for t in sorted(all_tickers):
        w = weights.get(t, 0.0)
        action = 'HOLD'
        if t == 'CASH':
            action = 'HOLD'  # cash is a weight allocation, never a trade signal
        elif w > 0:
            action = 'BUY'
        elif t in no_data:
            action = 'HOLD'  # insufficient history to rank; not an actionable exit
        elif t in latest and t not in weights:
            action = 'SELL'
        score = latest.get(t, {}).get('return_12w', 0.0) if t != 'CASH' else 0.0
        rows.append({'ticker': t, 'action': action, 'weight': w, 'score': score,
                     'strength': strengths.get(t)})
    return rows


def main():
    # Optional scoped run: --only SID[,SID...] restricts the engine to those
    # strategies (manual WRITE_SIGNAL onboarding/verification runs). Cron
    # calls with no args = full sweep, unchanged behaviour.
    only = None
    if '--only' in sys.argv:
        i = sys.argv.index('--only')
        only = {x.strip() for x in sys.argv[i + 1].split(',') if x.strip()}

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # fetch all paper strategies that we have configs for:
    # paused (disable_paper_rebuild=TRUE) or already computed (keep book consistent)
    cur.execute("""SELECT strategy_id, universe_tickers, frequency, execution_mode
                   FROM gold.strategy_registry
                   WHERE status = 'paper'
                     AND (disable_paper_rebuild = TRUE OR signal_mechanism = 'computed')
                   ORDER BY strategy_id""")
    strategies = cur.fetchall()
    if only is not None:
        strategies = [s for s in strategies if s[0] in only]
    if not strategies:
        print('No paused strategies to process.')
        return

    strategy_registry_map = {s[0]: s[3] for s in strategies}

    # Determine all tickers we need data for
    all_tickers = set()
    for sid, universe, freq, em in strategies:
        cfg = STRATEGY_CONFIGS.get(sid, {})
        universe = cfg.get('universe', universe or [])
        all_tickers.update(universe)
    # filter/sentiment tickers
    all_tickers.update(['SPY', 'HYG', 'AGG', 'TLT', 'IEF', 'GLD', '2800.HK'])
    all_tickers.discard('CASH')

    min_date = (datetime.now() - timedelta(days=900)).strftime('%Y-%m-%d')
    df = fetch_prices(conn, list(all_tickers), min_date)
    df = compute_metrics(df)
    latest_global = df.groupby('ticker').last().to_dict('index')
    latest_date = df['date'].max().date()
    print(f"Data latest date: {latest_date}")

    spy = latest_global.get('SPY', {})
    hyg = latest_global.get('HYG', {})
    agg = latest_global.get('AGG', {})
    tlt = latest_global.get('TLT', {})
    ief = latest_global.get('IEF', {})
    gld = latest_global.get('GLD', {})
    hk2800 = latest_global.get('2800.HK', {})

    for sid, universe, freq, em in strategies:
        cfg = STRATEGY_CONFIGS.get(sid)
        if not cfg:
            print(f"[SKIP] {sid}: no engine config")
            continue
        # Rank switch (OVERLAY memo §6, 2026-10-18): gold.strategy_configs
        # config_key='rank' overrides the engine's default rank for the sleeve
        # (e.g. 'composite_30_91_182_365d'). Absent row = engine default, so
        # the composite stays OFF until the user cuts over.
        cfg = dict(cfg)
        cur.execute("""SELECT config_value FROM gold.strategy_configs
                       WHERE strategy_id = %s AND config_key = 'rank'""", (sid,))
        _rk = cur.fetchone()
        if _rk and _rk[0]:
            cfg['rank'] = str(_rk[0]).strip('"')
            print(f"[CONFIG] {sid}: rank override from strategy_configs -> {cfg['rank']}")
        position_status = 'PAPER' if str(strategy_registry_map.get(sid, 'PAPER')).upper() == 'PAPER' else 'SIMULATION'
        if cfg.get('custom') == 'gs_ratio_meanrev_voltarget':
            # Stateful hysteresis strategy: replay full history (dedupe
            # market labels preferring GLOBAL, as in the research backtest).
            close_gs = fetch_prices_deduped(conn, cfg['universe'])
            st = gs_ratio_current_state(close_gs, cfg)
            rows = generate_gs_ratio_rows(st, cfg)
            meta = {'engine': 'build_rotation_signals',
                    'custom': 'gs_ratio_meanrev_voltarget',
                    'strength_method': 'normal_cdf_leg_z',
                    'position': st['position'], 'exposure': st['exposure'],
                    'z_latest': st['z_latest'],
                    'signal_date': st['signal_date'], 'entry_date': st['entry_date'],
                    'pending': st['pending'],
                    'z_window': cfg['z_window'], 'z_enter': cfg['z_enter'],
                    'vol_target': cfg['vol_target'], 'vol_lookback': cfg['vol_lookback'],
                    'entry_lag_days': cfg['entry_lag_days']}
            insert_score_rows(cur, sid, rows, meta, position_status)
            print(f"[DONE] {sid}: pos={st['position']} expo={st['exposure']:.4f} "
                  f"z={st['z_latest']} signal={st['signal_date']} entry={st['entry_date']} "
                  f"pending={st['pending']}")
            continue
        if cfg.get('custom') == 'vix_scaled_gld_sleeve':
            rows, meta = vix_scaled_gld_sleeve_rows(conn, cfg)
            if rows is None:
                print(f"[SKIP] {sid}: {meta.get('error')}")
                continue
            insert_score_rows(cur, sid, rows, meta, position_status)
            buys = {r['ticker']: r['weight'] for r in rows if r['action'] == 'BUY'}
            print(f"[DONE] {sid}: eq={meta['equity_weight']:.4f} "
                  f"z={meta['vix_z60']} vix_date={meta['vix_date']} "
                  f"rows={len(rows)} buys={buys}")
            continue
        if cfg.get('custom') == 'tech_mom_gld_fallback':
            rows, meta = tech_mom_gld_fallback_rows(conn, cfg)
            if rows is None:
                print(f"[SKIP] {sid}: {meta.get('error')}")
                continue
            insert_score_rows(cur, sid, rows, meta, position_status)
            buys = {r['ticker']: r['weight'] for r in rows if r['action'] == 'BUY'}
            print(f"[DONE] {sid}: top2={meta['top2']} lev={meta['leverage']} "
                  f"pv={meta['portfolio_vol']} signal_date={meta['signal_date']} "
                  f"rows={len(rows)} buys={buys}")
            continue
        if cfg.get('custom') == 'safe_haven_v2':
            rows, meta = safe_haven_v2_rows(conn, cfg)
            if rows is None:
                print(f"[SKIP] {sid}: {meta.get('error')}")
                continue
            insert_score_rows(cur, sid, rows, meta, position_status)
            buys = {r['ticker']: r['weight'] for r in rows if r['action'] == 'BUY'}
            print(f"[DONE] {sid}: top2={meta['top2']} lev={meta['leverage']} "
                  f"pv={meta['portfolio_vol']} signal_date={meta['signal_date']} "
                  f"rows={len(rows)} buys={buys}")
            continue
        if cfg.get('custom') == 'trend_overlay_mom12m':
            rows, meta = trend_overlay_mom12m_rows(conn, cfg)
            if rows is None:
                print(f"[SKIP] {sid}: {meta.get('error')}")
                continue
            insert_score_rows(cur, sid, rows, meta, position_status)
            buys = {r['ticker']: r['weight'] for r in rows if r['action'] == 'BUY'}
            print(f"[DONE] {sid}: signal_date={meta['signal_date']} "
                  f"ief_on={meta['ief_risk_on']} weights={meta['weights']} "
                  f"rows={len(rows)} buys={buys}")
            continue
        if cfg.get('custom') == 'comm_trend_tsmom':
            rows, meta = comm_trend_tsmom_rows(conn, cfg)
            if rows is None:
                print(f"[SKIP] {sid}: {meta.get('error')}")
                continue
            insert_score_rows(cur, sid, rows, meta, position_status)
            buys = {r['ticker']: r['weight'] for r in rows if r['action'] == 'BUY'}
            print(f"[DONE] {sid}: sel={meta.get('selected')} lev={meta.get('leverage')} "
                  f"pv={meta.get('portfolio_vol')} signal_date={meta.get('signal_date')} "
                  f"rows={len(rows)} buys={buys}")
            continue
        if cfg.get('custom') == 'country_rot_x14':
            rows, meta = country_rot_x14_rows(conn, cfg)
            if rows is None:
                print(f"[SKIP] {sid}: {meta.get('error')}")
                continue
            insert_score_rows(cur, sid, rows, meta, position_status)
            buys = {r['ticker']: r['weight'] for r in rows if r['action'] == 'BUY'}
            print(f"[DONE] {sid}: top2={meta['top2']} lev={meta['leverage']} "
                  f"pv={meta['portfolio_vol']} signal_date={meta['signal_date']} "
                  f"rows={len(rows)} buys={buys}")
            continue
        if cfg.get('custom') == 'def_sector_rot_w':
            rows, meta = def_sector_rot_w_rows(conn, cfg)
            if rows is None:
                print(f"[SKIP] {sid}: {meta.get('error')}")
                continue
            insert_score_rows(cur, sid, rows, meta, position_status)
            buys = {r['ticker']: r['weight'] for r in rows if r['action'] == 'BUY'}
            print(f"[DONE] {sid}: top2={meta['top2']} mom252={meta['mom252']} "
                  f"signal_date={meta['signal_date']} rows={len(rows)} buys={buys}")
            continue
        if cfg.get('custom') == 'trend_voltarget_daily':
            rows, meta = trend_voltarget_daily_rows(conn, cfg)
            if rows is None:
                print(f"[SKIP] {sid}: {meta.get('error')}")
                continue
            insert_score_rows(cur, sid, rows, meta, position_status)
            buys = {r['ticker']: r['weight'] for r in rows if r['action'] == 'BUY'}
            print(f"[DONE] {sid}: mom={meta.get('mom')} vol={meta.get('realized_vol')} "
                  f"expo={meta.get('exposure')} signal_date={meta.get('signal_date')} "
                  f"rows={len(rows)} buys={buys}")
            continue
        universe = cfg.get('universe', universe or [])
        # get latest metrics for this universe
        latest = latest_values(df, universe)
        rows = generate_signals(cfg, latest, spy, hyg, agg, tlt, ief, gld, hk2800)
        # Delete old computed rows for this strategy and insert new ones
        meta = {'engine': 'build_rotation_signals', 'config_rank': cfg.get('rank'),
                'config_filter': str(cfg.get('filter')),
                'strength_method': 'midpoint_percentile_rank_metric'}
        insert_score_rows(cur, sid, rows, meta, position_status)
        print(f"[DONE] {sid}: {len(rows)} tickers, cash={rows[0]['weight'] if rows[0]['ticker']=='CASH' else 'no'}")

    conn.commit()
    conn.close()

if __name__ == '__main__':
    main()
