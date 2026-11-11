#!/usr/bin/env python3
"""Free-tier edge probe (user directive 2026-10-17, item 6c).

Free tier is the ONLY options dataset we will ever have. If the vendor
narrows free access from below (old dates become 403), the nightly job —
which only pulls the recent window — would never notice until a re-pull of
an old date was attempted. This probe re-requests the OLDEST stored date per
symbol each night:

  TierGated (403) on a previously loaded date
      -> exit 3 + 'TIER GATE EDGE' message. The wrapper treats this as FATAL
         with a specific alert: derivatives research freezes at stored data.
  MarketClosed / empty                        -> OK (holiday at the edge)
  data returned                               -> OK
  terminal unreachable / other error          -> exit 4 (inconclusive; the
                                                 wrapper's own FATAL path
                                                 already covers terminal-down)

Read-only against the DB; one vendor request per symbol.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "shared", "scripts")))
os.environ.setdefault("AWS_REGION", "ap-southeast-1")

import db
from theta_client import ThetaClient, TierGated, MarketClosed

SYMBOLS = ("SPY", "XLE", "QQQ")  # QQQ added 2026-10-26 (Track B backfill, kanban t_8d75977e)


def main():
    conn = db.get_connection()
    cur = conn.cursor()
    client = ThetaClient()
    have_symbol = _contracts_have_symbol(cur)
    failures = []
    for sym in SYMBOLS:
        if have_symbol:
            cur.execute("SELECT min(q.trade_date) FROM silver.option_eod_quotes q "
                        "JOIN silver.option_contracts c USING (contract_id) "
                        "WHERE c.symbol = %s", (sym,))
        else:
            cur.execute("SELECT min(trade_date) FROM silver.option_eod_quotes")
        edge = cur.fetchone()[0]
        if edge is None:
            print(f"{sym}: no stored quotes — nothing to edge-probe")
            continue
        ds = edge.strftime("%Y%m%d")
        try:
            rows = client.option_eod(sym, ds)
            print(f"{sym}: edge {edge} OK ({len(rows)} rows returned)")
        except TierGated as e:
            failures.append(f"{sym} edge {edge}: {e}")
            print(f"{sym}: TIER GATE EDGE {edge}: {e}", flush=True)
        except MarketClosed:
            print(f"{sym}: edge {edge} market closed (holiday) — OK")
        except Exception as e:  # noqa: BLE001
            print(f"{sym}: edge probe INCONCLUSIVE: {e}", flush=True)
            conn.close()
            sys.exit(4)
    conn.close()
    if failures:
        print("TIER GATE EDGE: free-tier history narrowed — dates previously "
              "loaded now return 403: " + "; ".join(failures)
              + ". Derivatives research freezes at stored data.", flush=True)
        sys.exit(3)
    sys.exit(0)


def _contracts_have_symbol(cur):
    cur.execute("""SELECT count(*) FROM information_schema.columns
                   WHERE table_schema='silver' AND table_name='option_contracts'
                     AND column_name='symbol'""")
    return cur.fetchone()[0] == 1


if __name__ == "__main__":
    main()
