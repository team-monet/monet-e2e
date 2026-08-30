#!/usr/bin/env python3
"""RE-55 (upstream team-monet/monet#101 note): declare() writes a principle into
an ARCHIVED circle with NO disclosure that the row sits outside store-wide recall.

Reverse-engineering + E2E finding (verified 2026-08-30 on installed 1.9.1):
`memory_declare` resolves the home circle and writes WITHOUT consulting
`isArchivedCircle` — it is an ordinary store, and #101 fixed the disclosure for
memory_checkpoint (RE-51) but explicitly names declare() and reassignCircle as
REMAINING gaps. A declared rule/principle is an ordinary concept, so it genuinely
falls out of store-wide search when archived; a declare into an archived circle
returns no archived/guidance disclosure — this diverges from memory_store (#78)
and memory_checkpoint (#101).

Confirmed 1.9.1: store anchor -> archive circle -> `memory_declare`
{species: principle, circle: <archived>} -> receipt keys
{action, advisories, circle, conceptId, species} with NO 'archived'/'guidance'/
'landedInArchivedCircle' signal; DB `concepts` row `kind='principle'` lands in
the archived circle name. This is the declare sibling of RE-17 (store) / RE-51
(checkpoint).

Desired contract (asserted, XFAIL while present): a declare into an archived
circle must either (a) be REFUSED (mirroring the retired-concept guard / #81),
or (b) DISCLOSE that the landing circle is archived and the row sits outside
store-wide recall (a `guidance` clause / `archived` signal in the receipt).
Naming the circle is not disclosure.

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: bug still present (declare writes into archived circle,
              receipt has no archived disclosure) — expected
  3   = XPASS: bug appears fixed (write refused OR disclosure present)
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, DATA

ISSUE = "RE-55"
DB = os.path.join(DATA, "monet.db")
TS = str(int(time.time()))
CIRCLE = f"e2e-re55-{TS}"
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
            "sourceRefs": ["e2e:test56"],
        })
        check("anchor_stored", r.get("action") == "created" and bool(r.get("conceptId")),
              f"id={r.get('conceptId')}")

        r = c.call_json("memory_circle_manage", {"action": "archive", "circle": CIRCLE})
        check("archive_ack", r.get("action") == "archived" and r.get("circle") == CIRCLE,
              f"resp={r}")

        alias_status = sql(f"SELECT status FROM circle_aliases WHERE from_name = '{CIRCLE}';")
        check("circle_aliases_archived", alias_status == "archived", f"status={alias_status}")

        # ---- THE bug: declare a principle into the archived circle ----
        r = c.call_json("memory_declare", {
            "species": "principle",
            "content": f"RE55 declared principle policy for {TOKEN} is governed.",
            "circle": CIRCLE,
            "sourceRefs": ["e2e:test56"],
        })
        concept_id = r.get("conceptId")
        print(f"  [RE-55] declare into archived circle -> keys={sorted(r.keys())}")
        minted = bool(concept_id)

        # Desired contract: refused OR disclosed.
        refused = not minted
        disclosed = (
            ("archiv" in str(r).lower())
            or "guidance" in r
            or any(k.lower() in ("archived", "archivedcircle", "landedinarchivedcircle", "hidden")
                   for k in r.keys())
        )
        bug_fixed = refused or disclosed

        # When the bug is present, prove the principle row really landed in the
        # archived circle (silent write, outside store-wide recall).
        if minted:
            land = sql(f"SELECT circle FROM concepts WHERE id = '{concept_id}' AND kind='principle';")
            check("bug_principle_landed_in_archived_circle", land == CIRCLE,
                  f"circle={land}")

    finally:
        c.close()

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if bug_fixed:
        print(f"\nRESULT: XPASS {ISSUE} — declare into archived circle refused "
              f"or disclosed (bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — declare minted principle into archived circle "
          f"with no archived disclosure ({len(PASS)} setup checks passed)")
    return 2


if __name__ == "__main__":
    sys.exit(main())