#!/usr/bin/env python3
"""RE-51 (upstream team-monet/monet#81): checkpoint write into an archived
circle carries NO disclosure that the row now sits outside store-wide recall.

Reverse-engineering + E2E finding (verified 2026-08-23 on installed 1.7.1):
`memory_checkpoint`'s workstream path (`saveWorkstream` / `captureFind`) resolves
the circle and writes WITHOUT consulting `isArchivedCircle`. Unlike
`memory_store` (RE-17 / test24), whose PR #78 disclosure also does not REFUSE
but at least the store path is under scrutiny, the checkpoint receipt names the
circle (honestly, so a mid-call rename is reported) but never says that circle
is archived — no `guidance` clause, no `archived` flag. The minted workstream /
filed find lands in a circle that is invisible to store-wide recall until
unarchived, and the caller is told the write succeeded.

Confirmed on 1.7.1: store anchor → archive circle → `memory_checkpoint`
{workstream:{title,...}} → receipt `{circle, workstream:{id,title,opened,closed}}`
with NO archived signal; DB `concepts` row `kind='workstream'` lands in the
archived circle name. This is the checkpoint/save sibling of RE-17 (store path).

Desired contract (asserted, XFAIL while present): a checkpoint write into an
archived circle must either (a) be REFUSED (mirroring the retired-concept guard,
as #81 argues), or (b) DISCLOSE that the landing circle is archived and the row
sits outside store-wide recall (a `guidance` clause / `archived` signal in the
receipt). Naming the circle is not disclosure (per #81).

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: bug still present (checkpoint writes into archived circle,
              receipt has no archived disclosure) — expected
  3   = XPASS: bug appears fixed (write refused OR disclosure present)
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, DATA

ISSUE = "RE-51"
DB = os.path.join(DATA, "monet.db")
TS = str(int(time.time()))
CIRCLE = f"e2e-re51-{TS}"
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
            "sourceRefs": ["e2e:test54"],
        })
        check("anchor_stored", r.get("action") == "created" and bool(r.get("conceptId")),
              f"id={r.get('conceptId')}")

        r = c.call_json("memory_circle_manage", {"action": "archive", "circle": CIRCLE})
        check("archive_ack", r.get("action") == "archived" and r.get("circle") == CIRCLE,
              f"resp={r}")

        alias_status = sql(f"SELECT status FROM circle_aliases WHERE from_name = '{CIRCLE}';")
        check("circle_aliases_archived", alias_status == "archived", f"status={alias_status}")

        # ---- THE bug: checkpoint a workstream into the archived circle ----
        r = c.call_json("memory_checkpoint", {
            "circle": CIRCLE,
            "workstream": {
                "title": f"w51-{TOKEN}",
                "status": "active",
                "open": [{"kind": "step", "text": f"step a {TOKEN}"}],
            },
        })
        print(f"  [RE-51] checkpoint into archived circle -> {r}")
        receipt = r.get("_rawText", "") or str(r)
        ws = r.get("workstream") or {}
        minted = bool(ws.get("id"))

        # Desired contract: refused OR disclosed.
        refused = not minted
        disclosed = (
            ("archiv" in receipt.lower())
            or "guidance" in r
            or any(k.lower() in ("archived", "archivedcircle", "hidden") for k in r.keys())
        )
        bug_fixed = refused or disclosed

        # When the bug is present, prove the workstream row really landed in the
        # archived circle (silent write, outside store-wide recall).
        if minted:
            wid = ws["id"]
            land = sql(f"SELECT circle FROM concepts WHERE id = '{wid}' AND kind='workstream';")
            check("bug_workstream_landed_in_archived_circle", land == CIRCLE,
                  f"circle={land}")

    finally:
        c.close()

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if bug_fixed:
        print(f"\nRESULT: XPASS {ISSUE} — checkpoint into archived circle refused "
              f"or disclosed (bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — checkpoint minted workstream into archived circle "
          f"with no archived disclosure ({len(PASS)} setup checks passed)")
    return 2


if __name__ == "__main__":
    sys.exit(main())