#!/usr/bin/env python3
"""
S-06: BTC Donchian breakout (Crypto)
Data: gold.daily_ohlcv ticker=BTC-USD, gold.crypto_funding_metrics
Signal: long when close > 20d high, short when close < 20d low
Filter: skip if funding_z > 2.0
vol_target = 0.005 (half default)
"""
import sys, os
import pandas as pd

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


class Strategy06(BaseStrategy):
    def __init__(self, conn):
        super().__init__(conn, 6, "BTC Donchian breakout", vol_target=0.005)

    def _load_data(self):
        cur = self.conn.cursor()
        cur.execute("""
            SELECT date, close, high, low FROM gold.daily_ohlcv
            WHERE ticker = 'BTC-USD'
            ORDER BY date
        """)
        rows = cur.fetchall()
        df = pd.DataFrame(rows, columns=['date', 'close', 'high', 'low'])
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        for col in ['close', 'high', 'low']:
            df[col] = df[col].astype(float)
        return df

    def _get_funding_z(self):
        cur = self.conn.cursor()
        cur.execute("""
            SELECT funding_z FROM gold.crypto_funding_metrics
            WHERE symbol = 'BTCUSDT'
            ORDER BY date DESC LIMIT 1
        """)
        row = cur.fetchone()
        if row and row[0] is not None:
            return float(row[0])
        return 0.0

    def compute_signal(self) -> int:
        if not self.is_active_today():
            return 0

        df = self._load_data()
        if len(df) < 21:
            return 0

        funding_z = self._get_funding_z()
        if funding_z > 2.0:
            return 0

        df['dc_hi'] = df['high'].rolling(20).max().shift(1)
        df['dc_lo'] = df['low'].rolling(20).min().shift(1)

        today = df.iloc[-1]
        if today['close'] > today['dc_hi']:
            return 1
        if today['close'] < today['dc_lo']:
            return -1
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
