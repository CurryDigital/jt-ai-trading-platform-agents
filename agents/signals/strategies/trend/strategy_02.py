#!/usr/bin/env python3
"""
S-02: 52-week high momentum (Equities)
Data: gold.daily_ohlcv, ticker=SPY
Signal: long when close >= 0.98 * 252d high AND volume > 1.5x 20d avg
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


class Strategy02(BaseStrategy):
    def __init__(self, conn):
        super().__init__(conn, 2, "52-week high momentum")

    def _load_data(self):
        cur = self.conn.cursor()
        cur.execute("""
            SELECT date, close, volume FROM gold.daily_ohlcv
            WHERE ticker = 'SPY'
            ORDER BY date
        """)
        rows = cur.fetchall()
        df = pd.DataFrame(rows, columns=['date', 'close', 'volume'])
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df

    def compute_signal(self) -> int:
        if not self.is_active_today():
            return 0

        df = self._load_data()
        if len(df) < 252:
            return 0

        df['hi252'] = df['close'].rolling(252).max()
        df['vol_avg20'] = df['volume'].rolling(20).mean()

        today = df.iloc[-1]

        if today['close'] >= today['hi252'] * 0.98 and today['volume'] > today['vol_avg20'] * 1.5:
            return 1
        return 0

    def run(self) -> dict:
        active = self.is_active_today()
        signal = self.compute_signal()

        df = self._load_data()
        price = float(df['close'].iloc[-1])
        atr14 = self._compute_atr14(df)
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

    def _compute_atr14(self, df):
        if len(df) < 15:
            return 2.0
        returns = df['close'].pct_change().dropna()
        return float(returns.rolling(14).std().iloc[-1] * df['close'].iloc[-1])
