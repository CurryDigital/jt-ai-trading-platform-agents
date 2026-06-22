#!/usr/bin/env python3
"""
S-18: USD/JPY macro trend (FX)
Data: gold.daily_ohlcv ticker=JPY=X

Rate-spread signal deferred — requires reliable daily yield data.
Using EMA trend as proxy.

Signal:
  usdjpy = close (note: JPY=X quotes as USD per JPY)
  ema20 = usdjpy.ewm(span=20).mean()
  ema60 = usdjpy.ewm(span=60).mean()
  long  when ema20 > ema60 AND usdjpy < 155
  short when ema20 < ema60 AND usdjpy > 140
  flat  otherwise

vol_target = 0.008
"""
import sys, os
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..'))
SHARED = os.path.join(WORKSPACE, 'shared', 'scripts')
sys.path.insert(0, WORKSPACE)
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from strategies.base_strategy import BaseStrategy


class Strategy18(BaseStrategy):
    def __init__(self, conn):
        super().__init__(conn, 18, "USD/JPY macro trend", vol_target=0.008)

    def _load_data(self):
        cur = self.conn.cursor()
        cur.execute("""
            SELECT date, close FROM gold.daily_ohlcv
            WHERE ticker = 'JPY=X'
            ORDER BY date
        """)
        rows = cur.fetchall()
        df = pd.DataFrame(rows, columns=['date', 'close'])
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        df['close'] = df['close'].astype(float)
        return df

    def compute_signal(self) -> int:
        if not self.is_active_today():
            return 0

        df = self._load_data()
        if len(df) < 61:
            return 0

        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema60'] = df['close'].ewm(span=60, adjust=False).mean()

        usdjpy = df['close'].iloc[-1]
        ema20 = df['ema20'].iloc[-1]
        ema60 = df['ema60'].iloc[-1]

        if ema20 > ema60 and usdjpy < 155:
            return 1
        if ema20 < ema60 and usdjpy > 140:
            return -1
        return 0

    def run(self) -> dict:
        active = self.is_active_today()
        signal = self.compute_signal()

        df = self._load_data()
        price = 1.0  # FX notional
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
            return 0.01
        returns = df['close'].pct_change().dropna()
        return float(returns.rolling(14).std().iloc[-1])
