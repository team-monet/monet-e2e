#!/usr/bin/env python3
"""Scenario 5: circle isolation.

1. near-identical content in two circles stays separate
2. circle-restricted search never leaks across circles
3. unrestricted search returns both with their home circle
4. memory_reassign_circle auto -> dedup-merges into destination circle
5. memory_reassign_circle forceNew -> moves as a distinct concept
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import MonetClient, DATA

# GR-06: fresh circles per run — fixed names accumulated state across runs and
# broke the top-5 ranking assertion (verified 2026-08-10: circle C had 9 cards
# from prior runs; today's forceNew concept ranked below the top-5 cutoff).
TS = str(int(time.time()))
CIRCLE_A = f"e2e-iso-a-{TS}"
CIRCLE_B = f"e2e-iso-b-{TS}"
CIRCLE_C = f"e2e-iso-c-{TS}"
TOKEN = TS

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

        # 1. store near-identical content in two circles
        r = c.call_json("memory_store", {"content": f"circle isolation probe {TOKEN} alpha", "circle": CIRCLE_A, "sourceRefs": ["e2e:test05"]})
        id_a = r.get("conceptId")
        r = c.call_json("memory_store", {"content": f"circle isolation probe {TOKEN} beta", "circle": CIRCLE_B, "sourceRefs": ["e2e:test05"]})
        id_b = r.get("conceptId")
        check("store_both_circles", bool(id_a) and bool(id_b) and id_a != id_b, f"a={id_a} b={id_b}")

        # 2. restricted search stays inside its circle
        r = c.call_json("memory_search", {"query": "circle isolation probe", "circle": CIRCLE_A, "limit": 5})
        cards_a = r.get("results") or []
        check("circleA_no_leak", all(card.get("circle") == CIRCLE_A for card in cards_a), f"n={len(cards_a)}")
        r = c.call_json("memory_search", {"query": "circle isolation probe", "circle": CIRCLE_B, "limit": 5})
        cards_b = r.get("results") or []
        check("circleB_no_leak", all(card.get("circle") == CIRCLE_B for card in cards_b), f"n={len(cards_b)}")

        # 3. unrestricted search returns both, tagged with home circle
        r = c.call_json("memory_search", {"query": "circle isolation probe", "limit": 10})
        cards_all = r.get("results") or []
        seen = {card.get("circle") for card in cards_all if card.get("id") in (id_a, id_b)}
        check("unrestricted_both_circles", CIRCLE_A in seen and CIRCLE_B in seen, f"seen={seen}")

        # 4. reassign (auto): alpha from A to B -> dedup-merges into beta
        r = c.call_json("memory_reassign_circle", {"id": id_a, "toCircle": CIRCLE_B, "circle": CIRCLE_A})
        check("reassign_auto_merged", r.get("action") == "merged" and r.get("mergedIntoId") == id_b, str(r)[:140])
        r = c.call_json("memory_search", {"query": "circle isolation probe", "circle": CIRCLE_A, "limit": 5})
        check("reassigned_gone_from_A", all(card.get("id") != id_a for card in (r.get("results") or [])))
        r = c.call_json("memory_search", {"query": "circle isolation probe", "circle": CIRCLE_B, "limit": 10})
        cards_b2 = r.get("results") or []
        check("probe_still_in_B", any(card.get("id") == id_b and card.get("observationCount", 0) >= 2 for card in cards_b2),
              f"cards={[(x['id'][:8], x.get('observationCount')) for x in cards_b2]}")

        # 5. reassign (forceNew): distinct concept moved to fresh circle C
        r = c.call_json("memory_store", {"content": f"forceNew move probe {TOKEN} gamma", "circle": CIRCLE_A, "sourceRefs": ["e2e:test05"]})
        id_g = r.get("conceptId")
        r = c.call_json("memory_reassign_circle", {"id": id_g, "toCircle": CIRCLE_C, "circle": CIRCLE_A, "resolution": "forceNew"})
        moved_id = r.get("conceptId")
        check("reassign_forceNew_moved", bool(moved_id), str(r)[:140])
        r = c.call_json("memory_search", {"query": "forceNew move probe", "circle": CIRCLE_C, "limit": 5})
        cards_c = r.get("results") or []
        check("forceNew_present_in_C", any(card.get("id") == moved_id for card in cards_c), f"cards={[x['id'][:8] for x in cards_c]}")
    finally:
        c.close()

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
