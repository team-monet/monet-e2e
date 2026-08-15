#!/usr/bin/env python3
"""RE-32 (living-model-ranking.md): livingModel card discards the ranking score.

Reverse-engineering finding (v0.9.0 readable `engine.ts`, run 27): the living
model is ordered by `livingModelScore` — a multiplicative blend of four
independent signals (confidence x usefulness-boost x recency-half-life x
arousal-boost) — but `livingModelCard` emits only `{id, title, kind, confidence,
supportCount}`. The score that decided the ordering is computed then discarded
at the surface, so a caller sees *that* a concept ranks high but not *why*
(recency vs usefulness vs arousal). The ordering is opaque.

This test documents the DESIRED contract: the living-model card should expose
its ranking score (a numeric rank signal, e.g. a `score` field or a per-signal
breakdown) so an agent can see why one concept outranks another. The bug is
present when every card lacks any rank signal, leaving the ordering
unexplainable from the exposed fields alone.

Deterministic reproduction: store several distinct concepts, then fetch one of
them repeatedly (a usefulness signal that should reorder it), and assert the
overview's livingModel cards each carry a numeric rank signal.

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: livingModel cards still discard the ranking score (opaque ordering)
  3   = XPASS: livingModel cards now expose the ranking score (bug appears fixed)
"""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient

ISSUE = "RE-32"
CLI = os.environ.get("MONET_CLI") or "/Users/codalee/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js"
NODE = os.environ.get("MONET_NODE_PATH") or "/opt/homebrew/opt/node@22/bin"

os.environ["MONET_CLI"] = CLI
os.environ["MONET_NODE_PATH"] = NODE

TS = str(int(time.time()))

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def is_numeric(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def main():
    base = tempfile.mkdtemp(prefix="monet-re32-e2e-")
    store = os.path.join(base, "store")
    os.makedirs(store)

    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")

    bug_fixed = False
    try:
        c = MonetClient(store)
        try:
            c.initialize()
            circle = f"e2e-re32-{TS}"

            # ---- store 3 distinct concepts ----
            contents = [
                "alpha concept about pricing strategy",
                "beta concept about customer retention",
                "gamma concept about onboarding flow",
            ]
            ids = []
            for content in contents:
                r = c.call_json("memory_store", {"content": content, "circle": circle})
                ids.append(r.get("conceptId"))
            check("three_concepts_created", all(i for i in ids) and len(set(ids)) == 3,
                  f"ids={len(ids)}")

            # ---- create a usefulness gradient: fetch the FIRST concept repeatedly ----
            # (usefulness_score is +1 per getConcept, per living-model-ranking.md §3a)
            for _ in range(4):
                c.call_json("memory_fetch", {"conceptId": ids[0]})

            ov = c.call_json("memory_overview", {"circle": circle})
            cards = ov.get("livingModel") or []

            # ---- CONTROL: the living model is populated and ordered ----
            check("living_model_populated", len(cards) >= 3, f"cards={len(cards)}")
            check("living_model_card_shape", all(
                {"id", "title", "kind", "confidence", "supportCount"} <= set(card.keys())
                for card in cards
            ), f"keys={sorted(cards[0].keys()) if cards else '[]'}")

            # ---- DESIRED contract: each card exposes its ranking score ----
            # The ordering is score-driven (livingModelScore DESC), but the card
            # discards the score. Assert every card carries a numeric rank signal.
            rank_signals = [
                any(is_numeric(card.get(k)) for k in ("score", "rank", "livingModelScore"))
                for card in cards
            ]
            bug_fixed = all(rank_signals)

            # Report the observed ordering for the diary (opaque without score).
            order = [f"{card.get('title')}(supp={card.get('supportCount')})" for card in cards]
            print(f"  [RE-32] livingModel order: {order}")
            print(f"  [RE-32] rank-signal present: {rank_signals}")
        finally:
            c.close()
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if bug_fixed:
        print(f"\nRESULT: XPASS {ISSUE} — livingModel cards now expose the ranking score (bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — livingModel cards still discard the ranking score, "
          f"so the ordering is opaque ({len(PASS)} setup checks passed)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
