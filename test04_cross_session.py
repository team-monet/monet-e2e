#!/usr/bin/env python3
"""Scenario 4: cross-session persistence.

A store must survive process restarts: write in session A, close the
server, then start a fresh server (session B) and retrieve the data.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import MonetClient, DATA

CIRCLE = "e2e-x"
MARKER = "cross-session marker 2026-08-08 persists across server restarts"

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
    # Session A: write
    c = MonetClient(DATA)
    try:
        c.initialize()
        r = c.call_json("memory_store", {"content": MARKER, "circle": CIRCLE, "sourceRefs": ["e2e:test04"]})
        aid = r.get("conceptId")
        check("sessionA_store", bool(aid), f"id={aid}")
    finally:
        c.close()

    # Session B: fresh server, read back
    c2 = MonetClient(DATA)
    try:
        c2.initialize()
        r = c2.call_json("memory_search", {"query": "cross-session marker persists", "circle": CIRCLE, "limit": 3})
        cards = r.get("results") or []
        check("sessionB_search", any(MARKER[:30] in str(card) for card in cards[:3]) or (cards and cards[0].get("circle") == CIRCLE),
              f"top={cards[0] if cards else 'none'}")
        # fetch by id must work in a different process than the writer
        r = c2.call_json("memory_fetch", {"id": aid, "observations": True})
        check("sessionB_fetch", MARKER in str(r), str(r)[:120])
        # list shows persisted circle
        r = c2.call_json("memory_list", {"circle": CIRCLE})
        check("sessionB_list", (r.get("total") or 0) >= 1, f"total={r.get('total')}")
    finally:
        c2.close()

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
