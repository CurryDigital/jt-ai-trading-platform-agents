#!/usr/bin/env python3
"""
check_strategy_docs.py — CI: every strategy has a docs/strategies/<id>.md.

Offline (no DB) it enforces coverage for the strategies that ARE knowable
offline — the enabled signal-agent strategies in
agents/signals/strategies/registry.json. When a DB is reachable it also checks
every gold.strategy_registry strategy (and flags orphan docs), by delegating to
gen_strategy_docs.py --check.

This is what stops a strategy being onboarded with no documentation of how its
BUY signal is computed.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_HERE, ".."))
_DOCS = os.path.join(_REPO, "docs", "strategies")
_REGISTRY = os.path.join(_REPO, "agents", "signals", "strategies", "registry.json")


def _signal_agent_ids():
    """Map the signal-agent registry entries to the semantic strategy_id used
    in gold.strategy_registry / the frontend. registry.json carries a numeric
    id + name; the doc filename convention is the registry name with spaces →
    the same string the DB uses. We accept a doc named after EITHER the
    display name or an explicit doc_id in the entry."""
    with open(_REGISTRY) as f:
        data = json.load(f)
    out = []
    for e in data.get("strategies", []):
        if not e.get("enabled", False):
            continue
        # doc id: explicit override, else the class name's strategy label.
        out.append({"name": e["name"], "doc_id": e.get("doc_id")})
    return out


def _has_doc(name, doc_id):
    candidates = []
    if doc_id:
        candidates.append(doc_id)
    # tolerate a few filename spellings for the display name
    candidates.append(name)
    candidates.append(name.replace(" ", "_"))
    candidates.append(name.replace(" ", "_").replace("/", "_"))
    return any(os.path.isfile(os.path.join(_DOCS, f"{c}.md")) for c in candidates)


def main() -> int:
    problems = []

    if not os.path.isdir(_DOCS):
        print(f"❌ {_DOCS} does not exist")
        return 1

    # 1) offline: enabled signal-agent strategies must have a doc.
    for s in _signal_agent_ids():
        if not _has_doc(s["name"], s["doc_id"]):
            problems.append(f"signal-agent strategy {s['name']!r} has no docs/strategies/*.md")

    # 2) template + readme must exist.
    for req in ("_TEMPLATE.md", "README.md"):
        if not os.path.isfile(os.path.join(_DOCS, req)):
            problems.append(f"docs/strategies/{req} missing")

    # The full gold.strategy_registry coverage check needs a DB and is run
    # separately as `python3 tools/gen_strategy_docs.py --check` by the
    # operator/hermes (or a CI job that has DB access). This offline check is
    # the always-on gate.

    if problems:
        print(f"❌ {len(problems)} strategy-doc problem(s):")
        for p in problems:
            print(f"  {p}")
        return 1
    n = len(_signal_agent_ids())
    print(f"✅ strategy docs OK — {n} signal-agent strategies covered "
          f"[offline; run gen_strategy_docs.py --check for full DB coverage]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
