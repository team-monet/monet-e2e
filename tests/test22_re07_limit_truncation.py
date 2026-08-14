#!/usr/bin/env python3
"""RE-07 (search-pipeline.md): `limit` truncation is silent.

Reverse-engineering finding: `memory_search` slices results with
`.slice(0, limit)` and reports NO flag that more matches existed. Only the
JSON-size cap (Ar=40000 chars) emits `resultsTruncated`/`resultsOmitted`; the
`limit` cut is silent. So a caller asking for `limit=3` cannot tell whether 3
or 300 matches existed.

This test documents the DESIRED contract: when more matches exist than `limit`,
the response should signal truncation (reusing the existing `resultsTruncated` /
`resultsOmitted` flag mechanism already used for the size cap).

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: bug still present (limit truncation still silent) — expected
  3   = XPASS: bug appears fixed (truncation now signaled)
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, DATA

ISSUE = "RE-07"
DB = os.path.join(DATA, "monet.db")
TS = str(int(time.time()))
CIRCLE = f"e2e-re07-{TS}"

# Six STRUCTURALLY DISTINCT sentences that all carry the same distinctive
# phrase, so they rank high for the query but do NOT dedup-merge into one
# concept (GR-06: distinct sentence STRUCTURE is required to stay separate).
PHRASE = "deployment readiness review"
SENTENCES = [
    f"The {PHRASE} concluded the alpha release is safe to ship.",
    f"Before shipping beta, we ran the {PHRASE} and found three blockers.",
    f"Nobody expected the {PHRASE} to greenlight gamma this early.",
    f"She wrote the {PHRASE} for delta in a single afternoon.",
    f"The {PHRASE} for epsilon raised more questions than answers.",
    f"After the incident, the {PHRASE} for zeta was redone from scratch.",
]

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def sql(query):
    out = subprocess.run(["sqlite3", DB, query], capture_output=True, text=True)
    return out.stdout.strip()


def main():
    c = MonetClient(DATA)
    bug_fixed = False
    try:
        c.initialize()

        ids = []
        for s in SENTENCES:
            r = c.call_json("memory_store", {"content": s, "circle": CIRCLE, "sourceRefs": ["e2e:test22"]})
            ids.append(r.get("conceptId"))
        check("stored_6_distinct_concepts", len(set(ids)) == 6, f"unique={len(set(ids))}")

        # setup: with a generous limit, search surfaces MORE than 3 of the 6.
        r = c.call_json("memory_search", {"query": PHRASE, "circle": CIRCLE, "limit": 20})
        cards = r.get("results") or []
        check("search_surfaces_more_than_3", len(cards) > 3, f"n={len(cards)} (need >3 to make limit=3 a real cut)")

        # THE bug assertion: limit=3 should signal that more matches existed.
        r = c.call_json("memory_search", {"query": PHRASE, "circle": CIRCLE, "limit": 3})
        bug_fixed = r.get("resultsTruncated") is True or r.get("resultsOmitted") is not None
        print(f"  [RE-07] limit=3 -> results={len(r.get('results') or [])}, "
              f"resultsTruncated={r.get('resultsTruncated')}, resultsOmitted={r.get('resultsOmitted')}")

    finally:
        c.close()

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if bug_fixed:
        print(f"\nRESULT: XPASS {ISSUE} — limit truncation now signaled (bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — limit truncation still silent ({len(PASS)} setup checks passed)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
