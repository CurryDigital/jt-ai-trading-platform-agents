"""
Threshold comparison helper used by qr_risk and qr_qa.

Reads operator strings from `risk_config.operator` and applies them to
metric values. Returns True when the threshold is BREACHED — callers
treat True as "flag this" / "fail this gate".
"""

from numbers import Number
from typing import Union

Numeric = Union[int, float, Number]

# Canonical operators. Aliases are normalised first.
_OPERATORS = {
    "<":  lambda v, t: v <  t,
    ">":  lambda v, t: v >  t,
    "<=": lambda v, t: v <= t,
    ">=": lambda v, t: v >= t,
    "==": lambda v, t: v == t,
    "!=": lambda v, t: v != t,
}

_ALIASES = {
    "lt":  "<",
    "gt":  ">",
    "lte": "<=",
    "gte": ">=",
    "eq":  "==",
    "ne":  "!=",
    "neq": "!=",
}


def check_threshold(value: Numeric, operator: str, threshold: Numeric) -> bool:
    """
    Return True when `value <op> threshold` evaluates True.

    Examples (truthy means "breach detected, flag it"):
        check_threshold(-0.25, '<', -0.20)  # max_drawdown more negative than -20% → True
        check_threshold(0.30,  '<',  0.50)  # sharpe_oos below 0.5            → True
        check_threshold(40,    '<',  30  )  # trade_count_oos above 30        → False

    Raises:
        ValueError if operator is unknown or value/threshold are non-numeric.
    """
    if value is None or threshold is None:
        # A missing metric should not silently pass a gate.
        raise ValueError(f"check_threshold: value={value!r} threshold={threshold!r} (None not allowed)")

    op = (operator or "").strip().lower()
    op = _ALIASES.get(op, op)
    if op not in _OPERATORS:
        raise ValueError(f"check_threshold: unknown operator {operator!r}")

    return _OPERATORS[op](float(value), float(threshold))
