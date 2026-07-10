#!/usr/bin/env python3
"""
S-11: Tech momentum trend (Equities)
Data: gold.daily_ohlcv, ticker=QQQ

20-day high breakout with SMA20 trailing exit.
Long when close breaks above 20-day high AND volume > 1.5x 20d avg.
Hold until close < SMA20 (trend following with trailing stop).
"""

from strategies.base_strategy import BaseStrategy
import pandas as pd


class Strategy11(BaseStrategy):
    def __init__(self, conn):
        super().__init__(conn, 11, "Tech momentum trend")

    def _load_data(self, ticker='QQQ'):
        cur = self.conn.cursor()
        cur.execute("""
            SELECT date, close, volume FROM gold.daily_ohlcv
            WHERE ticker = %s
            ORDER BY date
        """, (ticker,))
        rows = cur.fetchall()
        df = pd.DataFrame(rows, columns=['date', 'close', 'volume'])
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df

    def compute_signal(self):
        if not self.is_active_today():
            return 0

        df = self._load_data()
        if df is None or len(df) < 50:
            return 0

        close = df['close']
        volume = df['volume']

        hi20 = close.rolling(20).max().shift(1)
        sma20 = close.rolling(20).mean()
        vol_avg20 = volume.rolling(20).mean()

        # Entry: break above 20-day high with volume
        # Exit: close below SMA20
        # For today's signal: 1 if in position, 0 if flat
        in_position = False
        for i in range(1, len(df)):
            if close.iloc[i] > hi20.iloc[i] and volume.iloc[i] > vol_avg20.iloc[i] * 1.5:
                in_position = True
            elif close.iloc[i] < sma20.iloc[i]:
                in_position = False

        return 1 if in_position else 0

    def run(self):
        active = self.is_active_today()
        signal = self.compute_signal()

        df = self._load_data()
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
