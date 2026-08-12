#!/usr/bin/env python3
"""Scenario 6 extension: correction that FAILS to attach opens NO contradiction.

E2E-confirms RE-14 (reverse-engineering run 11): the store-side auto-flag fires
only when a `kind="correction"` observation ATTACHES to an existing concept
(A=true). A correction whose content is dissimilar (below tauAttach) creates its
own concept and opens NO contradiction — the challenge never reaches the prior
concept's mediation flow.

Hypotheses:
1. A correction on an unrelated topic is stored with action=created (new
   concept), not attached.
2. The store ack carries NO contradiction id.
3. memory_overview on the circle shows zero openContradictions.
4. The original concept stays 'active' — memory_fetch shows no status/open
   contradictions, body unchanged.
5. Data layer: ZERO rows in `contradictions` for the original concept.

NOTE: contrast test06 — there the correction is a near-identical restatement of
the same claim (attaches -> contradiction). Here the correction is topically
disjoint (forceNew-like distance), so the attach never happens.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, DATA

DB = os.path.join(DATA, "monet.db")
TS = str(int(time.time()))
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
    try:
        c.initialize()

        circle = "e2e-s18-" + TS

        # 1. a claim about topic X
        claim = f"The refactoring budget for project {TOKEN} is 40 hours."
        r = c.call_json("memory_store", {"content": claim, "circle": circle,
                                         "sourceRefs": ["e2e:test18"]})
        cid_a = r.get("conceptId")
        check("claim_created", bool(cid_a), f"id={cid_a}")

        # 2. a CORRECTION on a completely different topic Y (below tauAttach)
        corr = f"The weather in Brisbane today is sunny and 24 degrees, unrelated to {TOKEN}."
        r = c.call_json("memory_store", {"content": corr, "circle": circle,
                                         "kind": "correction", "sourceRefs": ["e2e:test18"]})
        cid_b = r.get("conceptId")
        check("correction_created_new_concept", r.get("action") == "created" and cid_b != cid_a,
              f"action={r.get('action')} cid_b={cid_b} (dissimilar correction did not attach)")
        cont = (r.get("contradiction") or {})
        check("correction_ack_no_contradiction", not cont.get("id"),
              f"ack contradiction={cont.get('id')} (no auto-flag on failed attach)")

        # 3. overview: no open contradictions in the circle
        ov = c.call_json("memory_overview", {"circle": circle})
        check("overview_no_open", len(ov.get("openContradictions") or []) == 0,
              f"open={len(ov.get('openContradictions') or [])}")

        # 4. original concept untouched: active, no dispute fields, body unchanged
        f_a = c.call_json("memory_fetch", {"id": cid_a})
        check("orig_concept_active", f_a.get("status") in (None, "active"),
              f"status={f_a.get('status')} (no open contradiction -> active)")
        check("orig_concept_no_open_field", "openContradictions" not in f_a,
              "fetch card has no openContradictions (not disputed)")
        check("orig_concept_body_unchanged", f_a.get("body") == claim,
              f"body={str(f_a.get('body'))[:60]} (no verdict/append from the failed correction)")
        check("orig_obs_count_unchanged", f_a.get("observationCount", 1) == 1,
              f"obs={f_a.get('observationCount')} (correction created its own concept)")

        # 5. the correction concept exists separately with its own body
        f_b = c.call_json("memory_fetch", {"id": cid_b})
        check("corr_concept_has_correction", "weather" in (f_b.get("body") or ""),
              f"correction concept body={str(f_b.get('body'))[:60]}")
    finally:
        c.close()

    # ================= Data layer =================
    # ZERO contradictions rows for the original concept (RE-14: flag only on attach)
    n_contra = sql(f"SELECT COUNT(*) FROM contradictions WHERE concept_id='{cid_a}';")
    check("no_contradiction_rows", int(n_contra) == 0,
          f"contradictions(concept A)={n_contra} (no row, no status change)")

    # The correction observation exists, on ITS OWN concept, and is NOT superseded
    d = sql(f"SELECT concept_id || '|' || COALESCE(superseded_at,'NULL') FROM observations WHERE content LIKE '%unrelated to {TOKEN}%';")
    d_parts = d.split("|")
    check("corr_obs_on_own_concept", d_parts[0] == cid_b, f"concept_id={d_parts[0]}")
    check("corr_obs_not_superseded", d_parts[1] == "NULL", f"superseded_at={d_parts[1]}")

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
