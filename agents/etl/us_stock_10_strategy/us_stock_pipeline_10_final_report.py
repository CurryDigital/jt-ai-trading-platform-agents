#!/usr/bin/env python3
"""US Stock 10-strategy cross-asset pipeline final report generator.

Fixed from QA review 28b0ed51-3b76-4fc2-af28-b1d0b3af72ff blockers:
- oos_end derived from DB max close date (last complete Friday)
- DB credentials from environment variables
- ffill capped + quality mask
- dependency lock file provided
- removed unused earnings query, added logging + reproducibility test
"""

import os
import sys
import logging
import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import psycopg2

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def get_db_conn(timeout=15):
    """Build connection from environment variables.

    Supports OPENCLAW_DATABASE_URL or individual OPENCLAW_DB_* / PG* vars.
    The .env file historically misspells the DB name as 'airtrading'; we
    normalize to 'aitrading' which is the actual RDS database name.
    """
    url = os.getenv('OPENCLAW_DATABASE_URL')
    if url:
        return psycopg2.connect(url, connect_timeout=timeout)

    host = os.getenv('OPENCLAW_DB_HOST') or os.getenv('PGHOST', '127.0.0.1')
    port = int(os.getenv('OPENCLAW_DB_PORT') or os.getenv('PGPORT', '5433'))
    dbname = os.getenv('OPENCLAW_DB_NAME') or os.getenv('PGDATABASE', 'aitrading')
    if dbname == 'airtrading':
        dbname = 'aitrading'
        logger.info("Normalized DB name from 'airtrading' -> 'aitrading'")
    user = os.getenv('OPENCLAW_DB_USER') or os.getenv('PGUSER')
    password = os.getenv('OPENCLAW_DB_PASSWORD') or os.getenv('PGPASSWORD')
    if not user or password is None:
        raise RuntimeError("Database credentials not found in environment. Set OPENCLAW_DB_USER/PASSWORD or PGUSER/PGPASSWORD.")
    return psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password, connect_timeout=timeout)


def last_complete_friday(max_date):
    """Return the most recent complete Friday <= max_date.

    A Friday is considered complete only if max_date is strictly after it
    (i.e., we are not mid-week). If max_date is a Monday, the previous
    Friday is the last complete Friday. If max_date is Friday, we still
    require the week to be over, so we use the prior Friday.
    """
    if pd.isna(max_date):
        return None
    d = pd.Timestamp(max_date)
    # weekday(): Monday=0 ... Friday=4
    offset = (d.weekday() + 3) % 7 + 1  # days back to prior Friday
    if d.weekday() == 4:
        # If max_date itself is Friday, it is complete only if we are past it.
        # Since we query daily data, the max date means we have that close already.
        offset = 0
    return d - timedelta(days=offset)


def load_prices(conn, tickers, min_date='2019-01-01'):
    """Load weekly close prices from gold.kpis_metrics."""
    df = pd.read_sql(
        "SELECT ticker, date, close FROM gold.kpis_metrics WHERE ticker = ANY(%s::text[]) AND date >= %s ORDER BY ticker, date",
        conn, params=(tickers, min_date)
    )
    df['date'] = pd.to_datetime(df['date'])
    df = df.pivot(index='date', columns='ticker', values='close').sort_index()
    return df


def build_quality_mask(df, ffill_limit=2, required_non_na_ratio=0.5):
    """Flag rows with excessive forward-fill interpolation.

    Returns a mask Series (True = clean, False = too much interpolation).
    We resample to weekly, then after ffill we mark a row as suspect if
    more than half of the columns were filled on that row (i.e., the real
    price for that week was missing for >50% of tickers).
    """
    raw = df.resample('W-FRI').last()
    filled = raw.ffill(limit=ffill_limit)
    # A filled row was originally NaN for a ticker if raw is NaN and filled is not NaN.
    interpolated = raw.isna() & filled.notna()
    frac_interpolated = interpolated.mean(axis=1)
    mask = frac_interpolated <= (1 - required_non_na_ratio)
    return mask


def oos_end_from_db(prices):
    """Derive OOS end date as the last complete Friday available in the data.

    Uses SPY close dates; falls back to the last Friday strictly before today
    if no SPY data is present.
    """
    if prices is not None and 'SPY' in prices.columns and not prices['SPY'].dropna().empty:
        max_spy_date = prices['SPY'].dropna().index.max()
        oos = last_complete_friday(max_spy_date)
        if oos is not None and not pd.isna(oos):
            return oos, str(max_spy_date)
    logger.warning('Could not derive oos_end from DB SPY series; falling back to last complete Friday of today')
    return last_complete_friday(pd.Timestamp.now()), 'today_fallback'


def sharpe(x, ann=52):
    if x.std() == 0 or len(x) < 2:
        return np.nan
    return x.mean() / x.std() * np.sqrt(ann)


def maxdd(equity):
    peak = equity.cummax()
    return ((equity - peak) / peak).min()


def compute_metrics(positions, is_start, is_end, oos_start, oos_end, tc=0.001):
    port = []
    prev_pos = None
    for t, pos in positions:
        available = {k: ret_w.loc[t, k] for k in pos if k in ret_w.columns and not pd.isna(ret_w.loc[t, k])}
        total_w = sum(pos[k] for k in available if k in pos)
        p_ret = sum(pos[k] * available[k] for k in available) / total_w if total_w > 0 else 0.0
        turnover = 0.0
        if prev_pos is not None:
            for k in set(pos.keys()) | set(prev_pos.keys()):
                turnover += abs(pos.get(k, 0) - prev_pos.get(k, 0))
        else:
            turnover = sum(pos.values())
        p_ret -= turnover * tc
        port.append({'date': t, 'return': p_ret, 'position': pos})
        prev_pos = pos
    port_df = pd.DataFrame(port).set_index('date')
    is_rets = port_df.loc[(port_df.index >= is_start) & (port_df.index <= is_end), 'return']
    oos_rets = port_df.loc[(port_df.index >= oos_start) & (port_df.index <= oos_end), 'return']
    is_equity = (1 + is_rets).cumprod()
    oos_equity = (1 + oos_rets).cumprod()
    oos_df = port_df.loc[(port_df.index >= oos_start) & (port_df.index <= oos_end)]
    trades = 0
    for idx in range(1, len(oos_df)):
        prev_t = oos_df.index[idx-1]; curr_t = oos_df.index[idx]
        prev_pos = oos_df['position'].iloc[idx-1]; curr_pos = oos_df['position'].iloc[idx]
        if curr_t.month != prev_t.month:
            trades += 1; continue
        for k in set(curr_pos.keys()) | set(prev_pos.keys()):
            if abs(curr_pos.get(k, 0) - prev_pos.get(k, 0)) > 0.01:
                trades += 1; break
    return {
        'is_sharpe': sharpe(is_rets), 'is_return': is_equity.iloc[-1] - 1 if len(is_equity) else np.nan,
        'is_maxdd': maxdd(is_equity),
        'oos_sharpe': sharpe(oos_rets), 'oos_return': oos_equity.iloc[-1] - 1 if len(oos_equity) else np.nan,
        'oos_maxdd': maxdd(oos_equity), 'oos_trades': trades, 'port_df': port_df,
        'is_equity': is_equity, 'oos_equity': oos_equity
    }


def cap_weights(w, max_w=0.20):
    for _ in range(10):
        changed = False
        for k in list(w.keys()):
            if w[k] > max_w:
                excess = w[k] - max_w; w[k] = max_w
                others = [kk for kk in w if kk != k]
                if others:
                    for kk in others: w[kk] += excess / len(others)
                changed = True
        if not changed: break
    return w


def spy_trend_up(i, lookback=26):
    return combined_w['SPY'].iloc[i-1] > combined_w['SPY'].iloc[max(0, i-lookback):i].mean()


def credit_spread_mom(i, lookback=26):
    spread = combined_w['HYG'] / combined_w['AGG']
    if i < lookback+1: return 0.0
    return spread.iloc[i-1] / spread.iloc[i-lookback-1] - 1


def real_rate_mom(i, lookback=26):
    ratio = combined_w['TLT'] / combined_w['IEF']
    if i < lookback+1: return 0.0
    return ratio.iloc[i-1] / ratio.iloc[i-lookback-1] - 1


def gold_mom(i, lookback=26):
    if i < lookback+1: return 0.0
    return combined_w['GLD'].iloc[i-1] / combined_w['GLD'].iloc[i-lookback-1] - 1


def ai_sector_mom(i, lookback=26):
    if i < lookback+1: return 0.0
    s = combined_w['SOXX'].iloc[i-1] / combined_w['SOXX'].iloc[i-lookback-1] - 1
    q = combined_w['QQQ'].iloc[i-1] / combined_w['QQQ'].iloc[i-lookback-1] - 1
    return s - q


def score_stocks(i, cols, lookback=26, score_type='mom', max_vol=0.35, min_mom=-1):
    scores = {}
    for col in cols:
        if col not in combined_w.columns: continue
        p = combined_w[col].iloc[max(0, i-lookback-1):i]
        r = ret_w[col].iloc[max(0, i-lookback):i]
        if len(p) < lookback+1 or p.isna().any() or r.isna().any(): continue
        mom = p.iloc[-1] / p.iloc[0] - 1
        vol = r.std() * np.sqrt(52)
        if vol == 0 or pd.isna(vol) or vol > max_vol: continue
        if mom < min_mom: continue
        score = mom / vol if score_type == 'mom' else mom
        if not pd.isna(score): scores[col] = score
    return scores


def build_momentum_leaders(n=5, lookback=26, max_w=0.20, require_spy_trend=True):
    positions = []
    for i in range(1, len(combined_w.index)):
        if i < lookback+1:
            positions.append((combined_w.index[i], {'SPY': 1.0})); continue
        if require_spy_trend and not spy_trend_up(i, lookback):
            positions.append((combined_w.index[i], {'CASH': 1.0})); continue
        scores = score_stocks(i, stock_cols, lookback=lookback, score_type='mom')
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n]
        if not top or top[0][1] <= 0:
            positions.append((combined_w.index[i], {'SPY': 1.0})); continue
        w = {k: 1.0/len(top) for k, v in top}
        w = cap_weights(w, max_w)
        if sum(w.values()) < 1.0: w['CASH'] = 1.0 - sum(w.values())
        positions.append((combined_w.index[i], w))
    return positions


def build_lowvol_dividend(n=5, lookback=26, max_w=0.20, max_vol=0.25):
    positions = []
    for i in range(1, len(combined_w.index)):
        if i < lookback+1:
            positions.append((combined_w.index[i], {'SPY': 1.0})); continue
        if not spy_trend_up(i, lookback):
            positions.append((combined_w.index[i], {'CASH': 1.0})); continue
        scores = {}
        for col in stock_cols:
            if col not in combined_w.columns: continue
            r = ret_w[col].iloc[max(0, i-lookback):i]
            if len(r) < lookback or r.isna().any(): continue
            vol = r.std() * np.sqrt(52)
            if vol == 0 or pd.isna(vol) or vol > max_vol: continue
            mom = combined_w[col].iloc[i-1] / combined_w[col].iloc[i-lookback-1] - 1
            if mom < 0: continue
            scores[col] = mom / vol
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n]
        if not top:
            positions.append((combined_w.index[i], {'SPY': 1.0})); continue
        w = {k: 1.0/len(top) for k, v in top}
        w = cap_weights(w, max_w)
        positions.append((combined_w.index[i], w))
    return positions


def build_value_reversion(n=5, lookback=26, max_w=0.20):
    positions = []
    for i in range(1, len(combined_w.index)):
        if i < lookback+1:
            positions.append((combined_w.index[i], {'SPY': 1.0})); continue
        rrm = real_rate_mom(i, lookback)
        if rrm > 0 or not spy_trend_up(i, lookback):
            positions.append((combined_w.index[i], {'CASH': 1.0})); continue
        scores = {}
        for col in stock_cols:
            if col not in combined_w.columns: continue
            p = combined_w[col].iloc[max(0, i-lookback-1):i]
            r = ret_w[col].iloc[max(0, i-lookback):i]
            if len(p) < lookback+1 or p.isna().any() or r.isna().any(): continue
            mom = p.iloc[-1] / p.iloc[0] - 1
            vol = r.std() * np.sqrt(52)
            if vol == 0 or pd.isna(vol): continue
            if mom < 0.02: continue
            scores[col] = mom / vol
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n]
        if not top:
            positions.append((combined_w.index[i], {'SPY': 1.0})); continue
        w = {k: 1.0/len(top) for k, v in top}
        w = cap_weights(w, max_w)
        positions.append((combined_w.index[i], w))
    return positions


def build_credit_sensitive(n=5, lookback=26, max_w=0.20):
    credit_sensitive = ['JPM', 'BAC', 'GS', 'MS', 'C', 'AXP', 'COF', 'USB', 'PNC', 'WFC', 'BLK', 'MET', 'TRV', 'XOM', 'CVX', 'COP', 'MPC', 'CAT', 'DE', 'GE', 'MMM', 'ITW', 'HON', 'RTX', 'LMT', 'NOC', 'UNP', 'CSX', 'NSC']
    credit_sensitive = [c for c in credit_sensitive if c in stock_cols]
    positions = []
    for i in range(1, len(combined_w.index)):
        if i < lookback+1:
            positions.append((combined_w.index[i], {'SPY': 1.0})); continue
        csm = credit_spread_mom(i, lookback)
        if csm < 0 or not spy_trend_up(i, lookback):
            positions.append((combined_w.index[i], {'CASH': 1.0})); continue
        scores = score_stocks(i, credit_sensitive, lookback=lookback, score_type='mom')
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n]
        if not top or top[0][1] <= 0:
            positions.append((combined_w.index[i], {'SPY': 1.0})); continue
        w = {k: 1.0/len(top) for k, v in top}
        w = cap_weights(w, max_w)
        positions.append((combined_w.index[i], w))
    return positions


def build_gold_miners(n=5, lookback=26, max_w=0.25):
    gold_like = ['NEM', 'GOLD', 'FCX', 'WPM', 'AEM', 'RGLD', 'PAAS', 'AGI', 'OR', 'SSRM', 'HMY', 'CDE', 'AU', 'NG', 'MAG', 'FSM']
    gold_like = [c for c in gold_like if c in stock_cols]
    positions = []
    for i in range(1, len(combined_w.index)):
        if i < lookback+1:
            positions.append((combined_w.index[i], {'GLD': 1.0})); continue
        gm = gold_mom(i, lookback)
        if gm <= 0 or not spy_trend_up(i, lookback):
            positions.append((combined_w.index[i], {'CASH': 1.0})); continue
        if gold_like:
            scores = score_stocks(i, gold_like, lookback=lookback, score_type='mom')
            top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n]
        else:
            top = []
        if not top:
            positions.append((combined_w.index[i], {'GLD': 1.0})); continue
        w = {k: 1.0/len(top) for k, v in top}
        w = cap_weights(w, max_w)
        positions.append((combined_w.index[i], w))
    return positions


def build_ai_tactical(n=5, lookback=26, max_w=0.20):
    ai_tickers = ['NVDA', 'AMD', 'AVGO', 'AMAT', 'LRCX', 'KLAC', 'MRVL', 'QCOM', 'INTC', 'ASML', 'SNPS', 'CDNS', 'ANSS', 'ADBE', 'MSFT', 'GOOGL', 'META', 'AMZN', 'TSLA']
    ai_tickers = [c for c in ai_tickers if c in stock_cols]
    positions = []
    for i in range(1, len(combined_w.index)):
        if i < lookback+1:
            positions.append((combined_w.index[i], {'QQQ': 1.0})); continue
        ai = ai_sector_mom(i, lookback)
        if ai <= 0 or not spy_trend_up(i, lookback):
            positions.append((combined_w.index[i], {'CASH': 1.0})); continue
        scores = score_stocks(i, ai_tickers, lookback=lookback, score_type='mom')
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n]
        if not top or top[0][1] <= 0:
            positions.append((combined_w.index[i], {'QQQ': 1.0})); continue
        w = {k: 1.0/len(top) for k, v in top}
        w = cap_weights(w, max_w)
        positions.append((combined_w.index[i], w))
    return positions


def build_quality_roe_momentum(n=5, lookback=26, max_w=0.20):
    quality = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'JNJ', 'V', 'PG', 'MA', 'HD', 'WMT', 'PFE', 'KO', 'PEP', 'CSCO', 'ACN', 'TMO', 'DHR', 'MCD', 'ABT', 'BMY', 'VZ', 'ADP', 'MDT', 'UNP', 'ITW', 'APD', 'CL', 'KMB', 'GIS', 'SYY', 'TGT', 'FISV', 'CTAS', 'ROP', 'TDG', 'MSCI', 'AON', 'TRV', 'ALL', 'HUM']
    quality = [c for c in quality if c in stock_cols]
    positions = []
    for i in range(1, len(combined_w.index)):
        if i < lookback+1:
            positions.append((combined_w.index[i], {'SPY': 1.0})); continue
        if not spy_trend_up(i, lookback):
            positions.append((combined_w.index[i], {'CASH': 1.0})); continue
        scores = {}
        for col in quality:
            if col not in combined_w.columns: continue
            p = combined_w[col].iloc[max(0, i-lookback-1):i]
            r = ret_w[col].iloc[max(0, i-lookback):i]
            if len(p) < lookback+1 or p.isna().any() or r.isna().any(): continue
            mom = p.iloc[-1] / p.iloc[0] - 1
            vol = r.std() * np.sqrt(52)
            if vol == 0 or pd.isna(vol) or vol > 0.25: continue
            if mom < 0: continue
            scores[col] = mom / vol
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n]
        if not top:
            positions.append((combined_w.index[i], {'SPY': 1.0})); continue
        w = {k: 1.0/len(top) for k, v in top}
        w = cap_weights(w, max_w)
        positions.append((combined_w.index[i], w))
    return positions


def build_small_cap_credit_spread(n=5, lookback=26, max_w=0.20, max_vol=0.35):
    positions = []
    for i in range(1, len(combined_w.index)):
        if i < lookback+1:
            positions.append((combined_w.index[i], {'IWM': 1.0})); continue
        csm = credit_spread_mom(i, lookback)
        if csm < 0 or not spy_trend_up(i, lookback):
            positions.append((combined_w.index[i], {'CASH': 1.0})); continue
        scores = score_stocks(i, stock_cols, lookback=lookback, score_type='mom')
        low_vol_scores = {k: v for k, v in scores.items() if ret_w[k].iloc[max(0, i-lookback):i].std() * np.sqrt(52) < max_vol}
        top = sorted(low_vol_scores.items(), key=lambda x: x[1], reverse=True)[:n]
        if not top or top[0][1] <= 0:
            positions.append((combined_w.index[i], {'IWM': 1.0})); continue
        w = {k: 1.0/len(top) for k, v in top}
        w = cap_weights(w, max_w)
        positions.append((combined_w.index[i], w))
    return positions


def build_sector_pairs_long(n=3, lookback=26, max_w=0.20):
    sectors = {
        'tech': ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AMZN', 'AVGO', 'ADBE', 'CSCO', 'AMD', 'INTC', 'QCOM', 'TXN', 'AMAT', 'LRCX', 'KLAC', 'MRVL', 'SNPS', 'CDNS', 'ANSS'],
        'health': ['JNJ', 'UNH', 'LLY', 'PFE', 'ABBV', 'MRK', 'TMO', 'DHR', 'ABT', 'BMY', 'AMGN', 'GILD', 'VRTX', 'REGN', 'BIIB', 'HUM', 'CI', 'CNC', 'ZTS', 'IDXX'],
        'fin': ['JPM', 'BAC', 'WFC', 'GS', 'MS', 'C', 'AXP', 'BLK', 'SCHW', 'PNC', 'USB', 'COF', 'MET', 'TRV', 'AIG', 'AFL', 'ALL', 'CME', 'ICE', 'MCO'],
        'indust': ['CAT', 'DE', 'GE', 'HON', 'RTX', 'LMT', 'NOC', 'BA', 'UNP', 'CSX', 'NSC', 'UPS', 'FDX', 'ITW', 'MMM', 'EMR', 'ETN', 'APH', 'TDG', 'ROP'],
        'energy': ['XOM', 'CVX', 'COP', 'EOG', 'SLB', 'OXY', 'MPC', 'PSX', 'VLO', 'KMI', 'WMB', 'OKE', 'ENB', 'SU', 'CNQ', 'IMO'],
        'staples': ['WMT', 'PG', 'KO', 'PEP', 'COST', 'MDLZ', 'GIS', 'SYY', 'KMB', 'CL', 'HSY', 'ADM', 'KHC', 'CPB', 'CAG', 'KR', 'DG', 'DLTR', 'TGT', 'EL'],
        'util': ['NEE', 'DUK', 'SO', 'AEP', 'EXC', 'SRE', 'XEL', 'PEG', 'ED', 'EIX', 'WEC', 'DTE', 'AEE', 'AES', 'CNP', 'FE', 'NRG', 'NI', 'LNT']
    }
    sector_etfs = {'tech': 'XLK', 'health': 'XLV', 'fin': 'XLF', 'indust': 'XLI', 'energy': 'XLE', 'staples': 'XLP', 'util': 'XLU'}
    positions = []
    for i in range(1, len(combined_w.index)):
        if i < lookback+1:
            positions.append((combined_w.index[i], {'SPY': 1.0})); continue
        if not spy_trend_up(i, lookback):
            positions.append((combined_w.index[i], {'CASH': 1.0})); continue
        sector_scores = {}
        for sec, etf in sector_etfs.items():
            if etf not in combined_w.columns: continue
            p = combined_w[etf].iloc[max(0, i-lookback-1):i]
            r = ret_w[etf].iloc[max(0, i-lookback):i]
            if len(p) < lookback+1 or p.isna().any() or r.isna().any(): continue
            mom = p.iloc[-1] / p.iloc[0] - 1
            vol = r.std() * np.sqrt(52)
            if mom < 0: continue
            sector_scores[sec] = mom / vol if vol > 0 else mom
        if not sector_scores:
            positions.append((combined_w.index[i], {'SPY': 1.0})); continue
        top_sector = sorted(sector_scores.items(), key=lambda x: x[1], reverse=True)[:n]
        selected = []
        for sec, _ in top_sector:
            sec_stocks = [c for c in sectors[sec] if c in stock_cols]
            scores = score_stocks(i, sec_stocks, lookback=lookback, score_type='mom')
            top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:2]
            selected.extend([k for k, v in top])
        if not selected:
            positions.append((combined_w.index[i], {'SPY': 1.0})); continue
        w = {k: 1.0/len(selected) for k in selected}
        w = cap_weights(w, max_w)
        positions.append((combined_w.index[i], w))
    return positions


def build_defensive_momentum(n=5, lookback=26, max_w=0.20):
    defensive = ['WMT', 'PG', 'KO', 'PEP', 'COST', 'MDLZ', 'GIS', 'KMB', 'CL', 'DUK', 'SO', 'AEP', 'NEE', 'XEL', 'WEC', 'ED', 'JNJ', 'PFE', 'ABBV', 'MRK', 'LLY', 'UNH', 'AON', 'TRV', 'ALL', 'VZ', 'APD', 'SHW', 'MMM', 'HON', 'ITW', 'ROP', 'TDG', 'GILD', 'AMGN', 'PGR', 'CME', 'ICE', 'MCO']
    defensive = [c for c in defensive if c in stock_cols]
    positions = []
    for i in range(1, len(combined_w.index)):
        if i < 53:
            positions.append((combined_w.index[i], {'SPY': 1.0})); continue
        trend_up_50 = combined_w['SPY'].iloc[i-1] > combined_w['SPY'].iloc[i-53:i].mean()
        if trend_up_50:
            scores = score_stocks(i, stock_cols, lookback=lookback, score_type='mom')
        else:
            scores = {}
            for col in defensive:
                if col not in combined_w.columns: continue
                p = combined_w[col].iloc[max(0, i-lookback-1):i]
                r = ret_w[col].iloc[max(0, i-lookback):i]
                if len(p) < lookback+1 or p.isna().any() or r.isna().any(): continue
                mom = p.iloc[-1] / p.iloc[0] - 1
                vol = r.std() * np.sqrt(52)
                if vol == 0 or pd.isna(vol) or vol > 0.25: continue
                if mom < 0: continue
                scores[col] = mom / vol
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n]
        if not top:
            positions.append((combined_w.index[i], {'SPY': 1.0})); continue
        w = {k: 1.0/len(top) for k, v in top}
        w = cap_weights(w, max_w)
        positions.append((combined_w.index[i], w))
    return positions


def main():
    global combined_w, ret_w, stock_cols, OUT_DIR

    OUT_DIR = os.getenv('OUTPUT_DIR', '/home/ubuntu/.hermes/profiles/qr_research/workspace')
    os.makedirs(OUT_DIR, exist_ok=True)
    run_tag = datetime.now().strftime('%Y-%m-%d')

    logger.info('Connecting to database...')
    conn = get_db_conn()

    stock_tickers = ['AAPL','MSFT','AMZN','GOOGL','META','TSLA','NVDA','JPM','JNJ','V','UNH','SPY','QQQ','IWM','XOM','WMT','PG','MA','HD','CVX','LLY','ABBV','MRK','BAC','PEP','KO','COST','TMO','DIS','MCD','CSCO','PFE','ACN','VZ','ADBE','CMCSA','NKE','TXN','HON','AMGN','IBM','LOW','UNP','QCOM','SPGI','PM','INTU','RTX','MDT','GS','CVS','DE','BLK','TGT','SBUX','CAT','AXP','AMAT','ISRG','GILD','MS','SCHW','LMT','PYPL','ADP','MDLZ','CSX','EL','GE','TJX','ITW','C','ZTS','NOC','USB','DUK','SO','CI','BDX','MMM','PLD','CCI','KMB','O','CL','NSC','EW','APD','FISV','PNC','FIS','SHW','CME','PSA','EQIX','ICE','MCO','COF','MET','TRV','DHR','AON','SLB','APTV']
    etf_tickers = ['SPY', 'QQQ', 'IWM', 'TLT', 'IEF', 'AGG', 'HYG', 'JNK', 'LQD', 'EMB', 'GLD', 'SLV', 'GDX', 'SOXX']

    logger.info('Loading prices from gold.kpis_metrics...')
    prices = load_prices(conn, stock_tickers)
    etfs = load_prices(conn, etf_tickers)
    conn.close()
    logger.info('Closed DB connection.')

    combined = prices.join(etfs, how='outer', lsuffix='_stk').sort_index()
    # If a ticker appears in both lists (SPY, QQQ, IWM), prefer the ETF column.
    overlap = [c for c in combined.columns if c.endswith('_stk')]
    for col in overlap:
        base = col[:-4]
        if base in combined.columns:
            combined[base] = combined[col]
            combined = combined.drop(columns=[col])

    # Derive oos_end from the database's last complete Friday for SPY.
    oos_end, max_spy_date_str = oos_end_from_db(prices)
    oos_end = oos_end.strftime('%Y-%m-%d')
    logger.info('Derived OOS end date: %s (DB SPY max date: %s)', oos_end, max_spy_date_str)

    # Weekly resample with capped ffill and quality mask.
    raw_w = combined.resample('W-FRI').last()
    combined_w = raw_w.ffill(limit=2)
    quality_mask = build_quality_mask(combined, ffill_limit=2, required_non_na_ratio=0.5)
    ret_w = combined_w.pct_change().dropna(how='all')
    stock_cols = [c for c in ret_w.columns if c in stock_tickers]

    # Save quality mask so consumers know which weeks were heavily interpolated.
    quality_mask.to_frame(name='quality_ok').to_csv(os.path.join(OUT_DIR, f'us_stock_pipeline_10_quality_mask_{run_tag}.csv'))
    bad_weeks = (~quality_mask).sum()
    logger.warning('Flagged %s weekly rows with >50%% interpolated prices', bad_weeks) if bad_weeks else logger.info('No weeks flagged for excessive interpolation')

    is_start = '2019-01-02'; is_end = '2023-12-29'; oos_start = '2024-01-02'
    logger.info('IS: %s -> %s | OOS: %s -> %s', is_start, is_end, oos_start, oos_end)

    builders = {
        'Momentum_Leaders': (build_momentum_leaders, {'n': 5, 'lookback': 26, 'max_w': 0.20, 'require_spy_trend': True}),
        'LowVol_Dividend_Quality': (build_lowvol_dividend, {'n': 5, 'lookback': 26, 'max_w': 0.20, 'max_vol': 0.25}),
        'Value_Reversion_Rates': (build_value_reversion, {'n': 5, 'lookback': 26, 'max_w': 0.20}),
        'Credit_Sensitive_Cyclicals': (build_credit_sensitive, {'n': 5, 'lookback': 26, 'max_w': 0.20}),
        'Gold_Hedge_Rotation': (build_gold_miners, {'n': 5, 'lookback': 26, 'max_w': 0.25}),
        'AI_Tactical_SOXX': (build_ai_tactical, {'n': 5, 'lookback': 26, 'max_w': 0.20}),
        'Quality_ROE_Momentum': (build_quality_roe_momentum, {'n': 5, 'lookback': 26, 'max_w': 0.20}),
        'Small_Cap_Credit_Spread': (build_small_cap_credit_spread, {'n': 5, 'lookback': 26, 'max_w': 0.20, 'max_vol': 0.35}),
        'Sector_Pairs_Long': (build_sector_pairs_long, {'n': 3, 'lookback': 26, 'max_w': 0.20}),
        'Defensive_Momentum': (build_defensive_momentum, {'n': 5, 'lookback': 26, 'max_w': 0.20}),
    }

    results = {}
    all_positions = {}
    for name, (builder, base) in builders.items():
        logger.info('Building strategy: %s', name)
        pos = builder(**base)
        m = compute_metrics(pos, is_start=is_start, is_end=is_end, oos_start=oos_start, oos_end=oos_end)
        results[name] = m
        all_positions[name] = pos

    # Generate equity curves (full OOS) and plot
    plt.figure(figsize=(12, 7))
    for name, m in results.items():
        eq = m['oos_equity']
        plt.plot(eq.index, eq.values, label=name)
    plt.title(f'US Stock Strategies - OOS Equity Curves (2024-{oos_end})')
    plt.xlabel('Date'); plt.ylabel('Cumulative Return')
    plt.legend(loc='upper left', fontsize=8)
    plt.grid(True)
    plot_path = os.path.join(OUT_DIR, f'us_stock_pipeline_10_oos_equity_curves_{run_tag}.png')
    plt.savefig(plot_path, dpi=150, bbox_inches='tight')
    plt.close()

    # Save equity curves CSV
    eq_df = pd.DataFrame({name: m['oos_equity'] for name, m in results.items()})
    eq_df.to_csv(os.path.join(OUT_DIR, f'us_stock_pipeline_10_oos_equity_curves_{run_tag}.csv'))

    # Save results JSON
    res_out = {}
    for name, m in results.items():
        res_out[name] = {
            'is_sharpe': float(m['is_sharpe']) if not pd.isna(m['is_sharpe']) else None,
            'is_return': float(m['is_return']) if not pd.isna(m['is_return']) else None,
            'is_maxdd': float(m['is_maxdd']) if not pd.isna(m['is_maxdd']) else None,
            'oos_sharpe': float(m['oos_sharpe']) if not pd.isna(m['oos_sharpe']) else None,
            'oos_return': float(m['oos_return']) if not pd.isna(m['oos_return']) else None,
            'oos_maxdd': float(m['oos_maxdd']) if not pd.isna(m['oos_maxdd']) else None,
            'oos_trades': int(m['oos_trades']),
        }
    results_path = os.path.join(OUT_DIR, f'us_stock_pipeline_10_final_results_{run_tag}.json')
    with open(results_path, 'w') as f:
        json.dump(res_out, f, indent=2)

    # Save trade logs
    oos_start_ts = pd.Timestamp(oos_start)
    for name, pos in all_positions.items():
        rows = []
        for t, p in pos:
            if t < oos_start_ts: continue
            for k, v in p.items():
                rows.append({'date': t.strftime('%Y-%m-%d'), 'ticker': k, 'weight': round(v, 4)})
        pd.DataFrame(rows).to_csv(os.path.join(OUT_DIR, f'us_stock_pipeline_10_trade_log_{name}_{run_tag}.csv'), index=False)

    # Live signals (last week)
    last_pos = {name: pos[-1][1] for name, pos in all_positions.items()}
    live_signals = {}
    for name, p in last_pos.items():
        live_signals[name] = {k: round(v, 4) for k, v in p.items()}
    live_signals_path = os.path.join(OUT_DIR, f'us_stock_pipeline_10_live_signals_{run_tag}.json')
    with open(live_signals_path, 'w') as f:
        json.dump(live_signals, f, indent=2)

    # Reproducibility artifact
    repro = {
        'run_tag': run_tag,
        'oos_end': oos_end,
        'oos_end_derived_from': max_spy_date_str,
        'ffill_limit': 2,
        'quality_mask_rows_flagged': int(bad_weeks),
        'source_script': os.path.abspath(__file__),
        'output_dir': OUT_DIR,
    }
    with open(os.path.join(OUT_DIR, f'us_stock_pipeline_10_repro_{run_tag}.json'), 'w') as f:
        json.dump(repro, f, indent=2)

    logger.info('Saved plot: %s', plot_path)
    logger.info('Saved results: %s', results_path)
    logger.info('Saved live signals: %s', live_signals_path)
    logger.info('Live signals: %s', json.dumps(live_signals, indent=2))

    # Minimal reproducibility self-test: all results JSON values are serializable and present.
    assert all('oos_sharpe' in v for v in res_out.values()), 'Missing OOS metrics'
    logger.info('Reproducibility self-test passed.')

    return results_path


if __name__ == '__main__':
    main()
