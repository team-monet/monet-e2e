#!/usr/bin/env python3
"""RE-47 (ambiguous-band correction mis-attach) regression guard.

The `correction-attach` exemption (resolution.ts) used to attach a
`kind="correction"` observation in the ambiguous band (tauAmbiguous <= score <
tauAttach) to the evidence-nominated concept — then engine.ts disputed it,
flipping an innocent concept to `disputed`. DESIRED contract: an ambiguous-band
correction must FORK to its own concept (not absorb into the matched concept),
leave the matched concept's observationCount untouched, and open no
contradiction / no dispute. REGRESSION-GUARD for the 1.7.1 fix (upstream #52/#76).

Exit codes:
  0/1 = setup broke (test itself wrong)
  2   = XFAIL: bug present (correction absorbed into matched concept / disputed)
  3   = XPASS: correction forks cleanly (bug fixed)
"""
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient

ISSUE = "RE-47"
os.environ.setdefault("MONET_CLI", os.environ.get("MONET_CLI") or "/Users/codalee/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js")
os.environ.setdefault("MONET_NODE_PATH", "/opt/homebrew/opt/node@22/bin")

CIRCLE = "e2e-re47-" + str(int(time.time()))
BASE = ("Caching generated per-user content in an in-memory key-value store "
        "reduces database round-trips for read-heavy pages.")
AMBIG = ("A caching layer for generated per-user content should invalidate by "
         "user id when the profile changes.")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def main():
    base = tempfile.mkdtemp(prefix="monet-re47-e2e-")
    store = os.path.join(base, "store")
    os.makedirs(store)
    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")
    forked = False
    try:
        c = MonetClient(store)
        c.initialize()
        r0 = c.call_json("memory_store", {"content": BASE, "circle": CIRCLE})
        base_id = r0.get("conceptId")
        check("base_created", r0.get("action") == "created" and bool(base_id), f"id={base_id}")

        # ambiguous-band correction
        r1 = c.call_json("memory_store", {"content": AMBIG, "circle": CIRCLE, "kind": "correction"})
        corr_id = r1.get("conceptId")
        ns = r1.get("nearMatchScore")
        check("correction_known", bool(corr_id), f"id={corr_id}")
        # in the ambiguous band nearMatchScore ~0.60 (bge-m3)
        print(f"  [RE-47] correction action={r1.get('action')} nearMatchScore={ns} "
              f"nearMatchId={r1.get('nearMatchId')} contradiction={r1.get('contradiction')}")
        # forked = its OWN concept (not the base), which is the desired behavior
        forked = (corr_id != base_id)

        # matched concept untouched: obsCount still 1, not disputed
        card = c.call_json("memory_fetch", {"id": base_id, "circle": CIRCLE})
        obs = card.get("observationCount")
        check("matched_not_absorbed", forked, f"corr={corr_id} base={base_id}")
        check("matched_obsCount_unchanged", obs == 1, f"obsCount={obs}")
        check("matched_not_disputed", card.get("status") != "disputed",
              f"status={card.get('status')} openContradictions={card.get('openContradictions')}")
        c.close()
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if forked:
        print(f"\nRESULT: XPASS {ISSUE} — ambiguous-band correction forks to its own "
              f"concept, matched concept untouched + not disputed (bug fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — ambiguous-band correction absorbed into the matched "
          f"concept (mis-attach, blasts an innocent concept); bug present")
    return 2


if __name__ == "__main__":
    sys.exit(main())