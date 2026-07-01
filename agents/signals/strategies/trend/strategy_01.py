#!/usr/bin/env python3
"""
S-01: Dual EMA crossover (Equities)
Data: gold.daily_ohlcv, basket of 5 liquid ETFs

Basket: SPY, QQQ, IWM, GLD, TLT
  For each ticker:
    compute ema10, ema50
    delta = (ema10 - ema50) / close  (normalised EMA spread)
    weight = 1 / 20-day realised volatility
  combined_delta = weighted average of deltas
  long  when combined_delta > +0.001
  short when combined_delta < -0.001
  flat  otherwise
"""

import sys, os
import pandas as pd
import numpy as np

# Signal-agent layout (post 2026-06-22 split):
#   agents/signals/strategies/trend/strategy_NN.py  ← this file
#   agents/etl/shared/scripts/db.py                  ← canonical DB pool (cross-agent dep)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNALS_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..'))
ETL_SHARED = os.path.normpath(os.path.join(SIGNALS_ROOT, '..', 'etl', 'shared', 'scripts'))
sys.path.insert(0, SIGNALS_ROOT)
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from strategies.base_strategy import BaseStrategy
from db import get_connection


class Strategy01(BaseStrategy):
    def __init__(self, conn):
        super().__init__(conn, 1, "Dual EMA crossover")
        self.basket = ['SPY', 'QQQ', 'IWM', 'GLD', 'TLT']

    def _load_data(self, ticker='SPY'):
        cur = self.conn.cursor()
        cur.execute("""
            SELECT date, close FROM gold.daily_ohlcv
            WHERE ticker = %s
            ORDER BY date
        """, (ticker,))
        rows = cur.fetchall()
        df = pd.DataFrame(rows, columns=['date', 'close'])
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        df['close'] = df['close'].astype(float)
        return df

    def compute_signal(self):
        if not self.is_active_today():
            return 0

        deltas = []
        weights = []
        for ticker in self.basket:
            df = self._load_data(ticker=ticker)
            if df is None or len(df) < 50:
                continue
            close = df['close']
            ema10 = close.ewm(span=10, adjust=False).mean()
            ema50 = close.ewm(span=50, adjust=False).mean()
            delta = (ema10.iloc[-1] - ema50.iloc[-1]) / close.iloc[-1]
            vol = close.pct_change().rolling(20).std().iloc[-1]
            deltas.append(delta)
            weights.append(1.0 / (vol + 1e-6))

        if not deltas:
            return 0

        combined = np.average(deltas, weights=weights)
        if combined > 0.001:
            return 1
        if combined < -0.001:
            return -1
        return 0

    def run(self):
        active = self.is_active_today()
        signal = self.compute_signal()

        df = self._load_data('SPY')
        price = float(df['close'].iloc[-1])
        returns = df['close'].pct_change().dropna()
        atr14 = float(returns.rolling(14).std().iloc[-1] * price)
        position_size = self.size_position(signal, price, atr14)

        today = pd.Timestamp.now().date().isoformat()
        regime = getattr(self, '_today_regime', 'UNKNOWN')
        confidence = getattr(self, '_today_confidence', 0.0)

        return {
            'strategy_id': self.strategy_id,
            'name': self.name,
            'date': today,
            'signal': signal,
            'position_size': position_size,
            'regime': regime,
            'confidence': confidence,
            'active': active,
        }
