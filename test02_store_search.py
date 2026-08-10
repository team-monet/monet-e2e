#!/usr/bin/env python3
"""Scenario 2: store -> search -> retrieve round trip.

Stores distinct observations in circle 'e2e', searches them back,
and verifies the retrieved concept carries the stored content.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import MonetClient, DATA

CIRCLE = "e2e"
SRC = ["e2e:test02"]

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

        # 1. store three distinct claims
        claims = [
            "The Monet MCP server exposes 21 tools over stdio.",
            "Isolated test database lives under MONET_TEST_DIR.",
            "A fresh circle keeps repeated runs from merging into old concepts.",
        ]
        ids = []
        for claim in claims:
            r = c.call_json("memory_store", {"content": claim, "circle": CIRCLE, "sourceRefs": SRC})
            concept_id = r.get("conceptId")
            ids.append(concept_id)
            print(f"  stored -> {concept_id}")
        check("store_3_claims", all(ids), f"ids={ids}")

        # 2. search back each claim by a distinctive phrase
        for i, claim in enumerate(claims):
            phrase = " ".join(claim.split()[:3])
            r = c.call_json("memory_search", {"query": phrase, "circle": CIRCLE, "limit": 3})
            cards = r.get("results") or []
            hit = any(claim[:30] in str(card.get("slug", "")) for card in cards[:3]) or any(
                ids[i] == card.get("id") for card in cards[:3]
            )
            check(f"search_claim_{i+1}", hit, f"top={cards[0] if cards else 'none'}")

        # 3. fetch by id and verify content
        if ids[0]:
            r = c.call_json("memory_fetch", {"id": ids[0], "observations": True})
            fetched = str(r)
            check("fetch_by_id", claims[0][:30] in fetched or "The Monet MCP server" in fetched, fetched[:160])

        # 4. circle isolation sanity: search from another circle should not surface e2e cards
        r = c.call_json("memory_search", {"query": "Monet MCP server tools", "circle": "other-circle", "limit": 5})
        cards = r.get("results") or []
        check("circle_restrict_excludes", len(cards) == 0, f"n={len(cards)}")
    finally:
        c.close()

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
