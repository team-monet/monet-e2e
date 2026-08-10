#!/usr/bin/env python3
"""Scenario 10 extension: synthesize idempotency + version semantics (API + data layer).

Open question from run 4 (Finding 6): what does `version` in the
memory_synthesize ack count? Observed 10 stores -> version 9 on first
synthesize, which could mean "obsCount - 1" (derived) OR a revision counter
coincidentally equal to obsCount-1.

This test distinguishes the two:
1. N near-identical stores dedup into ONE concept (needsSynthesis=True).
2. Call memory_synthesize 3x with different bodies, no new stores in between.
   - revision counter => version increments by exactly 1 each call (v2=v1+1, v3=v2+1)
   - derived from obsCount => version stays flat across calls
3. VERIFIED (2026-08-11): version is DERIVED — flat across calls, equal to
   observationCount - 1. version is NOT a revision counter, and version is NOT
   unique across concept_revisions rows (3 synthesize calls -> 3 rows, all
   version 4 for a 5-obs concept).
4. Observations must stay intact across synthesizes (observationCount, texts).
5. needsSynthesis stays cleared once synthesized (no new observations); and it
   is set from CREATION (a fresh single-observation concept already has it).
6. Data layer: concept_revisions gains exactly one row per synthesize call,
   bodies recorded in call order.
7. Edge case: synthesize a single-observation concept (needsSynthesis=True)
   is allowed, ack version = 0 (= obsCount - 1).
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, DATA

DB = os.path.join(DATA, "monet.db")
CIRCLE = "e2e-s12-" + str(int(time.time()))
N = 5

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
    concept_id = None
    obs_texts = None
    versions = []
    try:
        c.initialize()

        # ---- Phase A: build a multi-observation concept ----
        for i in range(N):
            content = f"idempotency probe observation {i} about the same versioning topic"
            r = c.call_json("memory_store", {"content": content, "circle": CIRCLE, "sourceRefs": ["e2e:test12"]})
            if concept_id is None:
                concept_id = r.get("conceptId")
                check("first_store_created", r.get("action") == "created", f"action={r.get('action')}")
        f = c.call_json("memory_fetch", {"id": concept_id, "observations": True})
        check("obs_count_N", f.get("observationCount") == N, f"obs={f.get('observationCount')}")
        check("needsSynthesis_true", f.get("needsSynthesis") is True,
              f"needsSynthesis={f.get('needsSynthesis')}")
        obs_texts = [o.get("content") for o in (f.get("observations") or [])]

        # ---- Phase B: synthesize 3x, no new stores ----
        for k, body in enumerate(("VERSION PROBE BODY ONE", "VERSION PROBE BODY TWO", "VERSION PROBE BODY THREE")):
            ack = c.call_json("memory_synthesize", {"id": concept_id, "body": body, "circle": CIRCLE})
            check(f"synth_{k+1}_stored", ack.get("message") == "synthesis stored", f"ack={str(ack)[:100]}")
            check(f"synth_{k+1}_version_pos", isinstance(ack.get("version"), int) and ack.get("version", 0) >= 1,
                  f"version={ack.get('version')}")
            versions.append(ack.get("version"))

        check("version_flat_across_calls", versions[0] == versions[1] == versions[2],
              f"versions={versions} (flat => derived, NOT a per-call revision counter)")
        check("version_is_obs_derived", versions[0] == N - 1,
              f"v1={versions[0]} == obsCount-1={N-1}; matches run-4 10 obs -> 9, so version = observationCount - 1")
        check("version_no_revision_counter", versions[0] != 1,
              f"v1={versions[0]} != 1 (a pure revision counter would give 1,2,3)")

        # ---- Phase C: state preserved across synthesizes ----
        f2 = c.call_json("memory_fetch", {"id": concept_id, "observations": True})
        check("needsSynthesis_stays_cleared", not f2.get("needsSynthesis"),
              f"needsSynthesis={f2.get('needsSynthesis')}")
        check("body_last_wins", f2.get("body") == "VERSION PROBE BODY THREE", f"body={str(f2.get('body'))[:50]}")
        check("obs_count_preserved", f2.get("observationCount") == N, f"obs={f2.get('observationCount')}")
        obs_after = [o.get("content") for o in (f2.get("observations") or [])]
        check("obs_texts_preserved", obs_after == obs_texts,
              f"len={len(obs_after) if obs_after else 0}")

        # ---- Phase D: edge — synthesize a clean single-obs concept ----
        r_single = c.call_json("memory_store",
                               {"content": "a single standalone observation with its own topic",
                                "circle": CIRCLE, "sourceRefs": ["e2e:test12"]})
        single_id = r_single.get("conceptId")
        fs = c.call_json("memory_fetch", {"id": single_id})
        check("single_needsSynthesis_from_creation", fs.get("needsSynthesis") is True,
              f"needsSynthesis={fs.get('needsSynthesis')} (flag is set even on a freshly created 1-observation concept)")
        try:
            ack_s = c.call_json("memory_synthesize", {"id": single_id, "body": "SINGLE SYNTH BODY", "circle": CIRCLE})
            check("single_synth_allowed", True, f"ack={str(ack_s)[:100]}")
            check("single_synth_version_obs_derived", ack_s.get("version") == 0,
                  f"version={ack_s.get('version')} (1 obs -> version 0 = obsCount-1)")
        except Exception as e:
            check("single_synth_allowed", False, f"refused: {str(e)[:120]}")
    finally:
        c.close()

    # ---- Phase E: data layer (server closed -> sqlite3 safe) ----
    rev_rows = sql(f"SELECT version, body FROM concept_revisions WHERE concept_id='{concept_id}' ORDER BY created_at, rowid;")
    rev_lines = [ln for ln in rev_rows.splitlines() if ln]
    check("revisions_3_rows", len(rev_lines) == 3, f"rows={len(rev_lines)}")
    bodies_db = [ln.split("|", 1)[1] if "|" in ln else "" for ln in rev_lines]
    check("revisions_bodies_ordered", bodies_db == ["VERSION PROBE BODY ONE", "VERSION PROBE BODY TWO", "VERSION PROBE BODY THREE"],
          f"bodies={bodies_db}")
    versions_db = [ln.split("|", 1)[0] for ln in rev_lines]
    check("revisions_version_derived_not_unique", all(v == str(N - 1) for v in versions_db),
          f"versions={versions_db} (all rows carry obsCount-1; version is NOT unique per revision row)")
    obs = int(sql(f"SELECT COUNT(*) FROM observations WHERE concept_id='{concept_id}';"))
    check("obs_rows_preserved", obs == N, f"obs={obs}")

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    print(f"OBSERVED versions: {versions}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
