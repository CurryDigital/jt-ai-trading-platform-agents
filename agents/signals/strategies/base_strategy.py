#!/usr/bin/env python3
"""
Base Strategy — Signal Framework Goal 1
========================================
Abstract base class inherited by all 20 strategies.
Provides regime gate, position sizer, and persistence.
"""
from abc import ABC, abstractmethod
from datetime import date


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies."""

    def __init__(self, conn, strategy_id: int,
                 name: str, vol_target: float = 0.01):
        self.conn = conn
        self.strategy_id = strategy_id
        self.name = name
        self.vol_target = vol_target  # 1% daily vol target

    def is_active_today(self) -> bool:
        """
        Reads gold.regime_label for today.
        Returns True only if self.strategy_id is in
        active_strategies list for today's regime.
        Also returns True on EIA days if strategy_id == 12.
        """
        cur = self.conn.cursor()
        cur.execute("""
            SELECT regime, override_used, confidence, severity
            FROM gold.regime_label
            WHERE date = (SELECT MAX(date) FROM gold.regime_label)
        """)
        row = cur.fetchone()
        if row is None:
            return False

        regime, override_used, confidence, severity = row
        self._today_regime = regime
        self._today_confidence = float(confidence) if confidence else 0.0
        self._today_event_flag = bool(severity == 1) if severity is not None else False

        # EIA day special case: strategy 12 is always active on EIA days
        if self.strategy_id == 12 and self._today_event_flag:
            return True

        # Load strategy map from regime_rules
        from regime.regime_rules import STRATEGY_MAP
        active_ids = STRATEGY_MAP.get(regime, [])
        return self.strategy_id in active_ids

    @abstractmethod
    def compute_signal(self) -> int:
        """
        Returns: +1 (long), -1 (short), 0 (flat)
        Must call is_active_today() first.
        If not active, return 0 immediately.
        """
        pass

    def size_position(self, signal: int,
                      price: float,
                      atr14: float) -> float:
        """
        Vol-target position sizing.
        position_size = (portfolio_value * vol_target)
                        / (atr14 * price)
        Returns number of units (float).
        Returns 0.0 if signal == 0.
        Assume portfolio_value = 100_000 as default.
        """
        if signal == 0 or price <= 0 or atr14 <= 0:
            return 0.0
        portfolio_value = 100_000.0
        return (portfolio_value * self.vol_target) / (atr14 * price)

    def run(self) -> dict:
        """
        Calls compute_signal() then size_position().
        Returns dict with keys:
          strategy_id, name, date, signal,
          position_size, regime, confidence
        """
        active = self.is_active_today()
        signal = self.compute_signal()

        # Default price and atr14 for stub sizing
        price = 100.0
        atr14 = 2.0
        position_size = self.size_position(signal, price, atr14)

        today = date.today().isoformat()
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

    def save(self, result: dict) -> None:
        """
        Upserts result dict into gold.strategy_signals.
        """
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO gold.strategy_signals
                (date, strategy_id, strategy_name, signal,
                 position_size, regime, confidence, active, computed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (date, strategy_id) DO UPDATE SET
                strategy_name = EXCLUDED.strategy_name,
                signal = EXCLUDED.signal,
                position_size = EXCLUDED.position_size,
                regime = EXCLUDED.regime,
                confidence = EXCLUDED.confidence,
                active = EXCLUDED.active,
                computed_at = NOW()
        """, (
            result['date'],
            result['strategy_id'],
            result['name'],
            result['signal'],
            result['position_size'],
            result['regime'],
            result['confidence'],
            result['active'],
        ))
        self.conn.commit()
