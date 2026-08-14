#!/usr/bin/env python3
"""RE-19 (circle-routing.md): mergeCircle HARD-DELETES workstream concepts.

Reverse-engineering finding (v1.5.2 source): `mergeCircle` hard-deletes every
`kind='workstream'` concept in the merged circle (`hardDeleteNativeConcept`) and
counts it as `noop` — a destructive merge path for workstreams only, with no
confirmation or tombstone. Normal concepts go through `reassignCircle`; only
workstreams are silently destroyed.

This test documents the DESIRED contract: merging a circle must move workstream
concepts into the destination like any other concept (preserving their open
items), NOT silently hard-delete them.

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: bug still present (workstream hard-deleted) — expected
  3   = XPASS: bug appears fixed (workstream survives merge)
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, DATA

ISSUE = "RE-19"
DB = os.path.join(DATA, "monet.db")
TS = str(int(time.time()))
CIRCLE_A = f"e2e-re19-src-{TS}"
CIRCLE_B = f"e2e-re19-dst-{TS}"

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

        # Setup: one normal concept + one workstream (with 2 open items) in A.
        r = c.call_json("memory_store", {
            "content": f"re19 merge probe normal {TS}",
            "circle": CIRCLE_A,
            "sourceRefs": ["e2e:test23"],
        })
        check("store_normal_concept", bool(r.get("conceptId")), str(r)[:120])

        r = c.call_json("memory_checkpoint", {
            "circle": CIRCLE_A,
            "workstream": {
                "title": f"re19 merge probe workstream {TS}",
                "open": [
                    {"kind": "step", "text": "ship the re19 merge"},
                    {"kind": "question", "text": "was the workstream destroyed?"},
                ],
            },
        })
        ws_id = (r.get("workstream") or {}).get("id")
        opened = (r.get("workstream") or {}).get("opened") or []
        check("open_workstream", bool(ws_id) and len(opened) == 2, f"ws={ws_id} opened={len(opened)}")

        # Pre-merge: the workstream is active in A.
        r = c.call_json("memory_workstreams", {"circle": CIRCLE_A})
        pre_ids = [w.get("id") for w in (r.get("workstreams") or [])]
        check("workstream_active_in_A_pre_merge", ws_id in pre_ids, f"ids={pre_ids}")

        # Merge A -> B.
        r = c.call_json("memory_circle_manage", {"action": "merge", "circle": CIRCLE_A, "to": CIRCLE_B})
        results = r.get("conceptResults") or []
        ws_result = next((x for x in results if x.get("conceptId") == ws_id), None)
        check("merge_completed", bool(results), f"n={len(results)}")

        # THE bug assertion: the workstream must survive the merge.
        # (v1.5.2 hard-deleted it and counted `noop`; correct behavior = moved.)
        moved = ws_result is not None and ws_result.get("action") == "moved"
        print(f"  [RE-19] workstream merge result: {ws_result}")

        r = c.call_json("memory_workstreams", {"circle": CIRCLE_B})
        post_ids = [w.get("id") for w in (r.get("workstreams") or [])]
        survived = ws_id in post_ids

        # Open items must be preserved in the destination.
        r = c.call_json("memory_workstreams", {"id": ws_id, "circle": CIRCLE_B})
        items_preserved = len(opened) > 0 and len((r.get("items") or r.get("open") or [])) >= len(opened)
        print(f"  [RE-19] post-merge workstream in B: survived={survived}, "
              f"items_in_detail={len((r.get('items') or r.get('open') or []))}, expected={len(opened)}")

        bug_fixed = moved and survived and items_preserved

        # DB cross-check: the workstream concept must still exist and be in B.
        row = sql(f"SELECT circle, kind FROM concepts WHERE id = '{ws_id}'")
        check("workstream_concept_still_in_db", bool(row), f"row='{row}'")

    finally:
        c.close()

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if bug_fixed:
        print(f"\nRESULT: XPASS {ISSUE} — workstream survives merge (bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — workstream still hard-deleted on merge ({len(PASS)} setup checks passed)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
