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
