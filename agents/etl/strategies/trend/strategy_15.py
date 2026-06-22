#!/usr/bin/env python3
"""
S-15: Natgas seasonal (Futures)
Data: gold.daily_ohlcv, ticker=FCG (First Trust Natural Gas ETF)
Fallback: XLE if FCG data insufficient (< 3 years)

Signal:
  long when month in [11, 12, 1, 2] AND regime=TREND
  flat otherwise
  No short for this strategy.

vol_target = 0.005
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


class Strategy15(BaseStrategy):
    def __init__(self, conn):
        super().__init__(conn, 15, "Natgas seasonal", vol_target=0.005)
        self.ticker = self._resolve_ticker(conn)

    def _resolve_ticker(self, conn):
        """Use FCG if available with >= 3 years history, else XLE."""
        cur = conn.cursor()
        cur.execute("""
            SELECT ticker, MIN(date), COUNT(*) FROM gold.daily_ohlcv
            WHERE ticker IN ('FCG', 'XLE')
            GROUP BY ticker
        """)
        rows = {r[0]: {'min_date': r[1], 'count': r[2]} for r in cur.fetchall()}
        
        if 'FCG' in rows and rows['FCG']['count'] >= 750:  # ~3 years
            return 'FCG'
        return 'XLE'

    def _load_data(self):
        cur = self.conn.cursor()
        cur.execute("""
            SELECT date, close FROM gold.daily_ohlcv
            WHERE ticker = %s
            ORDER BY date
        """, (self.ticker,))
        rows = cur.fetchall()
        df = pd.DataFrame(rows, columns=['date', 'close'])
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        df['close'] = df['close'].astype(float)
        return df

    def compute_signal(self) -> int:
        if not self.is_active_today():
            return 0

        today_month = pd.Timestamp.now().month
        if today_month in [11, 12, 1, 2]:
            return 1
        return 0

    def run(self) -> dict:
        active = self.is_active_today()
        signal = self.compute_signal()

        df = self._load_data()
        price = float(df['close'].iloc[-1]) if len(df) > 0 else 1.0
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
