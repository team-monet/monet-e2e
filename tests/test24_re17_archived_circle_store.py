#!/usr/bin/env python3
"""RE-17 (circle-routing.md): storeInternal has no archived-circle guard.

Reverse-engineering finding (v1.5.2 source; re-verified v0.9.0 readable TS
2026-08-14): `storeInternal` resolves the circle and enforces only the
`*` breadth-marker guard — there is NO check for an archived circle. So
`memory_store` into a circle that `archiveCircle` has marked `status='archived'`
succeeds silently and the concept lands in a hidden circle (invisible to
store-wide recall until unarchived). Archive hides recall, not writes.

This test documents the DESIRED contract: archiving a circle is the store's own
statement that "nobody works here", so a write into it should be REFUSED (not
silently accepted into a hidden circle). This mirrors the existing retired-concept
guard ("cannot mutate a retired concept") and the `assertArchivedCircleMoveAllowed`
door that reassignCircle already enforces for circle-local blocking rules.

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: bug still present (store into archived circle succeeds) — expected
  3   = XPASS: bug appears fixed (store into archived circle refused)
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, DATA

ISSUE = "RE-17"
DB = os.path.join(DATA, "monet.db")
TS = str(int(time.time()))
CIRCLE = f"e2e-re17-{TS}"
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


def sql(query):
    out = subprocess.run(["sqlite3", DB, query], capture_output=True, text=True)
    return out.stdout.strip()


def main():
    c = MonetClient(DATA)
    bug_fixed = False
    try:
        c.initialize()

        # ---- setup: make the circle exist, then archive it ----
        r = c.call_json("memory_store", {
            "content": f"pre-archive anchor claim for project {TOKEN}.",
            "circle": CIRCLE,
            "sourceRefs": ["e2e:test24"],
        })
        check("anchor_stored", r.get("action") == "created" and bool(r.get("conceptId")),
              f"id={r.get('conceptId')}")

        r = c.call_json("memory_circle_manage", {"action": "archive", "circle": CIRCLE})
        check("archive_ack", r.get("action") == "archived" and r.get("circle") == CIRCLE,
              f"resp={r}")

        # DB cross-check: the archive wrote a self-alias status='archived'.
        alias_status = sql(f"SELECT status FROM circle_aliases WHERE from_name = '{CIRCLE}';")
        check("circle_aliases_archived", alias_status == "archived", f"status={alias_status}")

        # THE bug assertion: a store into the archived circle must be REFUSED.
        r = c.call_json("memory_store", {
            "content": f"post-archive write into hidden circle {TOKEN}.",
            "circle": CIRCLE,
            "sourceRefs": ["e2e:test24"],
        })
        stored = bool(r.get("conceptId"))
        raw = r.get("_rawText", "")
        print(f"  [RE-17] store into archived circle -> conceptId={r.get('conceptId')}, "
              f"action={r.get('action')}, _rawText={raw[:120]!r}")

        # Correct behavior = refused (no conceptId; an error is returned).
        bug_fixed = not stored

        # Cross-check the land-target when the bug is present (concept lands in the
        # archived circle, proving it really did accept the write).
        if stored:
            cid = r.get("conceptId")
            land_circle = sql(f"SELECT circle FROM concepts WHERE id = '{cid}';")
            check("bug_concept_landed_in_archived_circle", land_circle == CIRCLE,
                  f"circle={land_circle}")

    finally:
        c.close()

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if bug_fixed:
        print(f"\nRESULT: XPASS {ISSUE} — store into archived circle refused (bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — store into archived circle still succeeds silently "
          f"({len(PASS)} setup checks passed)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
