#!/usr/bin/env python3
"""
registry_loader.py
==================
Single source of truth for strategy discovery. Reads registry.json and
exposes:

    load_registry()             → list[StrategyEntry]
    load_enabled_strategies()   → list[StrategyEntry]  (enabled=true only)
    build_strategy_map()        → dict[regime: str, list[int]]  (= STRATEGY_MAP)
    import_strategy_class(entry) → cls

This replaces the previous setup where strategy lists were hardcoded in
THREE files (strategies/run_signals.py, strategies/stubs.py, regime/regime_rules.py).
Now there's one JSON file; new strategies appear in the cron next run without
editing any Python.

No external deps: stdlib only (json + importlib). The registry format is
documented at agents/etl/strategies/STRATEGIES.md.
"""

from __future__ import annotations

import importlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "registry.json")

VALID_REGIMES = {"TREND", "MEAN_REV", "CARRY", "EVENT", "FLAT"}
VALID_ASSET_CLASSES = {"equity", "crypto", "fx", "commodity"}


class RegistryError(ValueError):
    """Registry data is malformed or violates a contract."""


@dataclass(frozen=True)
class StrategyEntry:
    id: int
    name: str
    class_path: str          # "module.path:ClassName"
    regime: str
    enabled: bool
    asset_class: str
    params: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""


def _validate(entry: Dict[str, Any], seen_ids: set) -> StrategyEntry:
    required = ("id", "name", "class_path", "regime", "enabled", "asset_class")
    missing = [k for k in required if k not in entry]
    if missing:
        raise RegistryError(
            f"Registry entry missing fields {missing}: {entry!r}"
        )

    if not isinstance(entry["id"], int):
        raise RegistryError(f"id must be int, got {type(entry['id']).__name__}: {entry!r}")
    if entry["id"] in seen_ids:
        raise RegistryError(f"Duplicate strategy id={entry['id']}: {entry!r}")
    seen_ids.add(entry["id"])

    if entry["regime"] not in VALID_REGIMES:
        raise RegistryError(
            f"Unknown regime {entry['regime']!r} for id={entry['id']}. "
            f"Valid: {sorted(VALID_REGIMES)}"
        )

    if entry["asset_class"] not in VALID_ASSET_CLASSES:
        raise RegistryError(
            f"Unknown asset_class {entry['asset_class']!r} for id={entry['id']}. "
            f"Valid: {sorted(VALID_ASSET_CLASSES)}"
        )

    if ":" not in entry["class_path"]:
        raise RegistryError(
            f"class_path must be 'module.path:ClassName', got {entry['class_path']!r}"
        )

    return StrategyEntry(
        id=entry["id"],
        name=entry["name"],
        class_path=entry["class_path"],
        regime=entry["regime"],
        enabled=bool(entry["enabled"]),
        asset_class=entry["asset_class"],
        params=dict(entry.get("params") or {}),
        notes=entry.get("notes", ""),
    )


def load_registry(path: Optional[str] = None) -> List[StrategyEntry]:
    """Read and validate the registry. Raises RegistryError on any issue."""
    path = path or REGISTRY_PATH
    with open(path) as f:
        data = json.load(f)

    entries_raw = data.get("strategies")
    if not isinstance(entries_raw, list):
        raise RegistryError(f"registry.json must have a top-level 'strategies' list. Got: {type(entries_raw).__name__}")

    seen_ids: set = set()
    return [_validate(e, seen_ids) for e in entries_raw]


def load_enabled_strategies(path: Optional[str] = None) -> List[StrategyEntry]:
    return [e for e in load_registry(path) if e.enabled]


def build_strategy_map(path: Optional[str] = None) -> Dict[str, List[int]]:
    """
    Derive the STRATEGY_MAP that regime_rules.py used to hardcode.
    Only ENABLED strategies appear in the map — disabled ones don't gate-in.
    """
    out: Dict[str, List[int]] = {r: [] for r in VALID_REGIMES}
    for entry in load_registry(path):
        if entry.enabled:
            out[entry.regime].append(entry.id)
    for regime in out:
        out[regime].sort()
    return out


def import_strategy_class(entry: StrategyEntry):
    """
    Dynamically import the strategy class named in entry.class_path.
    Raises RegistryError with a descriptive message on import / attribute failure
    (instead of bubbling raw ImportError, which is harder to debug).
    """
    module_path, _, class_name = entry.class_path.partition(":")
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise RegistryError(
            f"Strategy id={entry.id} ({entry.name}): cannot import module "
            f"{module_path!r}: {e}"
        ) from e
    try:
        return getattr(module, class_name)
    except AttributeError as e:
        raise RegistryError(
            f"Strategy id={entry.id} ({entry.name}): module {module_path!r} "
            f"has no attribute {class_name!r}"
        ) from e
