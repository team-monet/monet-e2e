#!/usr/bin/env python3
"""Scenario 3: Korean search retrieval.

Stores Korean observations and searches them back with a Korean query.
EXPECTED STATE: with an English-only embedder (bge-small-en-v1.5) this
fails — Korean tokens embed to noise. After `monet repair` migration to
Xenova/paraphrase-multilingual-MiniLM-L12-v2 it should pass.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import MonetClient, DATA

CIRCLE = "e2e-ko"

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

        claims = [
            "주식 트래커는 yfinance로 19종목을 매일 조회한다",
            "브로커는 무무와 토스를 사용한다",
            "자동매매는 승인 후 주문만 실행한다",
        ]
        ids = []
        for claim in claims:
            r = c.call_json("memory_store", {"content": claim, "circle": CIRCLE, "sourceRefs": ["e2e:test03-ko"]})
            ids.append(r.get("conceptId"))
            print(f"  stored -> {r.get('conceptId')}")

        # Korean query targeting the first claim
        queries = [
            ("주식 트래커 종목 조회", 0),
            ("무무 브로커", 1),
            ("자동매매 주문", 2),
        ]
        for q, idx in queries:
            r = c.call_json("memory_search", {"query": q, "circle": CIRCLE, "limit": 3})
            cards = r.get("results") or []
            hit = any(card.get("id") == ids[idx] for card in cards[:3])
            check(f"ko_search_{idx+1}", hit, f"q='{q}' top={cards[0] if cards else 'none'}")
    finally:
        c.close()

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
