#!/usr/bin/env python3
"""
Unit tests for strategies.registry_loader.

Tests the contract documented in registry_loader.py:
- registry.json validates (no id collisions, allow-listed regimes/assets)
- build_strategy_map() returns ONLY enabled strategies grouped by regime
- import_strategy_class() actually imports the class
- malformed entries raise RegistryError with a useful message

Run: python3 agents/etl/tests/test_registry_loader.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ETL = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ETL)

from strategies.registry_loader import (
    load_registry, load_enabled_strategies, build_strategy_map,
    import_strategy_class, RegistryError, VALID_REGIMES, VALID_ASSET_CLASSES,
)


def _write_tmp_registry(entries) -> str:
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump({"schema_version": 1, "strategies": entries}, tmp)
    tmp.close()
    return tmp.name


def test_real_registry_loads_clean():
    """The production registry.json must validate."""
    entries = load_registry()
    assert len(entries) > 0
    assert all(e.regime in VALID_REGIMES for e in entries)
    assert all(e.asset_class in VALID_ASSET_CLASSES for e in entries)


def test_real_registry_has_expected_real_strategies():
    """The 7 real (non-stub) strategies must all be enabled."""
    enabled = load_enabled_strategies()
    enabled_ids = sorted(e.id for e in enabled)
    expected_real = [1, 2, 6, 11, 15, 16, 18]
    assert enabled_ids == expected_real, (
        f"expected {expected_real}, got {enabled_ids}. "
        "Either a real strategy was disabled OR a stub was enabled."
    )


def test_strategy_map_contains_only_enabled():
    smap = build_strategy_map()
    enabled_ids = {e.id for e in load_enabled_strategies()}
    all_ids_in_map = {sid for ids in smap.values() for sid in ids}
    assert all_ids_in_map == enabled_ids, (
        f"map IDs {all_ids_in_map} != enabled IDs {enabled_ids}"
    )
    # No stub IDs in any regime
    stub_ids = {e.id for e in load_registry() if not e.enabled}
    assert all_ids_in_map.isdisjoint(stub_ids), (
        f"disabled strategy IDs leaked into STRATEGY_MAP: "
        f"{all_ids_in_map & stub_ids}"
    )


def test_strategy_map_groups_by_regime():
    smap = build_strategy_map()
    for regime in VALID_REGIMES:
        assert regime in smap, f"{regime!r} missing from STRATEGY_MAP"
        # Within-regime ids are sorted
        assert smap[regime] == sorted(smap[regime])


def test_duplicate_id_raises():
    path = _write_tmp_registry([
        {"id": 1, "name": "a", "class_path": "x:Y",
         "regime": "TREND", "enabled": True, "asset_class": "equity"},
        {"id": 1, "name": "b", "class_path": "x:Z",
         "regime": "TREND", "enabled": True, "asset_class": "equity"},
    ])
    try:
        load_registry(path)
    except RegistryError as e:
        assert "Duplicate" in str(e)
        return
    finally:
        os.unlink(path)
    raise AssertionError("expected RegistryError on duplicate id")


def test_unknown_regime_raises():
    path = _write_tmp_registry([
        {"id": 99, "name": "bad", "class_path": "x:Y",
         "regime": "ALIEN", "enabled": True, "asset_class": "equity"},
    ])
    try:
        load_registry(path)
    except RegistryError as e:
        assert "ALIEN" in str(e)
        return
    finally:
        os.unlink(path)
    raise AssertionError("expected RegistryError on unknown regime")


def test_unknown_asset_class_raises():
    path = _write_tmp_registry([
        {"id": 99, "name": "bad", "class_path": "x:Y",
         "regime": "TREND", "enabled": True, "asset_class": "options"},
    ])
    try:
        load_registry(path)
    except RegistryError as e:
        assert "options" in str(e)
        return
    finally:
        os.unlink(path)
    raise AssertionError("expected RegistryError on unknown asset_class")


def test_missing_field_raises():
    path = _write_tmp_registry([
        {"id": 99, "name": "missing-class-path",
         "regime": "TREND", "enabled": True, "asset_class": "equity"},
    ])
    try:
        load_registry(path)
    except RegistryError as e:
        assert "class_path" in str(e) or "missing" in str(e).lower()
        return
    finally:
        os.unlink(path)
    raise AssertionError("expected RegistryError on missing field")


def test_bad_class_path_format_raises():
    path = _write_tmp_registry([
        {"id": 99, "name": "no-colon", "class_path": "no_colon_separator",
         "regime": "TREND", "enabled": True, "asset_class": "equity"},
    ])
    try:
        load_registry(path)
    except RegistryError as e:
        assert "module.path:ClassName" in str(e)
        return
    finally:
        os.unlink(path)
    raise AssertionError("expected RegistryError on bad class_path format")


def test_import_strategy_class_missing_module_raises_registry_error():
    """ImportError must be wrapped in RegistryError with context."""
    from strategies.registry_loader import StrategyEntry
    fake = StrategyEntry(
        id=99, name="ghost",
        class_path="strategies.nonexistent_module:Strategy99",
        regime="TREND", enabled=False, asset_class="equity",
    )
    try:
        import_strategy_class(fake)
    except RegistryError as e:
        assert "ghost" in str(e) and "nonexistent_module" in str(e)
        return
    raise AssertionError("expected RegistryError when importing missing module")


def _main():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    _main()
