#!/usr/bin/env python3
"""Scenario 6: contradiction detection & resolution.

1. store a claim -> concept created
2. store a correction (kind=correction) -> same concept, contradiction OPEN
3. memory_overview shows openContradictions + disputed=1
4. memory_search surfaces contradictions:1
5. memory_resolve(decision=accept-new) -> contradiction closed, disputed=0
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import MonetClient, DATA

# Fresh circle per run: repeated runs on the same circle would merge into the
# previously-resolved concept and change the contradiction semantics.
CIRCLE = "e2e-c6-" + str(int(time.time()))
TOKEN = str(int(time.time()))  # unique content token inside the fresh circle

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def main():
    c = MonetClient(DATA)
    try:
        c.initialize()

        # 1. claim
        claim = f"The flagship color of Monet e2e {TOKEN} is blue."
        r = c.call_json("memory_store", {"content": claim, "circle": CIRCLE, "sourceRefs": ["e2e:test06"]})
        cid = r.get("conceptId")
        check("claim_created", bool(cid), f"id={cid}")

        # 2. correction
        corr = f"The flagship color of Monet e2e {TOKEN} is green."
        r = c.call_json("memory_store", {"content": corr, "circle": CIRCLE, "kind": "correction", "sourceRefs": ["e2e:test06"]})
        cont_id = (r.get("contradiction") or {}).get("id")
        check("correction_opens_contradiction", bool(cont_id), f"contradiction={cont_id}")

        # 3. overview shows the open contradiction
        ov = c.call_json("memory_overview", {"circle": CIRCLE})
        oc = ov.get("openContradictions") or []
        check("overview_lists_contradiction", any(c.get("id") == cont_id for c in oc), f"open={len(oc)}")
        check("overview_disputed_count", ov.get("counts", {}).get("disputed", 0) >= 1, f"disputed={ov.get('counts', {}).get('disputed')}")

        # 4. search surfaces the contradiction flag
        r = c.call_json("memory_search", {"query": "flagship color", "circle": CIRCLE, "limit": 5})
        cards = r.get("results") or []
        hit = next((card for card in cards if card.get("id") == cid), None)
        check("search_shows_contradictions", bool(hit) and hit.get("contradictions", 0) >= 1, f"card={hit}")

        # 5. resolve with accept-new
        r = c.call_json("memory_resolve", {"contradictionId": cont_id, "decision": "accept-new", "circle": CIRCLE, "resolvedBy": "monet-e2e-test"})
        check("resolve_returns_active", r.get("status") == "active", str(r)[:120])

        ov2 = c.call_json("memory_overview", {"circle": CIRCLE})
        check("resolve_clears_open", len(ov2.get("openContradictions") or []) == 0)
        check("resolve_clears_disputed", ov2.get("counts", {}).get("disputed", 0) == 0,
              f"disputed={ov2.get('counts', {}).get('disputed')}")
    finally:
        c.close()

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
