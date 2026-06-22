#!/usr/bin/env python3
"""
S-16: London FX breakout (FX)
Data: gold.daily_ohlcv, ticker=EURUSD=X

SUSPENDED: requires intraday data (Asian session range 00:00-07:00 GMT).
Daily OHLCV proxy produced -0.485 Sharpe.
Will be re-enabled when 1-min bars available.

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


class Strategy16(BaseStrategy):
    def __init__(self, conn):
        super().__init__(conn, 16, "London FX breakout", vol_target=0.008)

    def compute_signal(self) -> int:
        if not self.is_active_today():
            return 0
        # SUSPENDED: requires intraday data
        # Daily OHLCV proxy produced -0.485 Sharpe
        # Will be re-enabled when 1-min bars available
        return 0

    def run(self) -> dict:
        active = self.is_active_today()
        signal = self.compute_signal()

        today = pd.Timestamp.now().date().isoformat()
        regime = getattr(self, '_today_regime', 'UNKNOWN')
        confidence = getattr(self, '_today_confidence', 0.0)

        return {
            'strategy_id': self.strategy_id,
            'name': self.name,
            'date': today,
            'signal': signal,
            'position_size': 0.0,
            'regime': regime,
            'confidence': confidence,
            'active': active,
            'notes': 'suspended_no_intraday_data',
        }
