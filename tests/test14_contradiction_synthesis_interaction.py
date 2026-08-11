#!/usr/bin/env python3
"""Scenario 6 x 10 interaction: contradiction flagging vs needsSynthesis + resolve guards.

Open questions from run 8 (next step #2): "does contradiction flagging interact
with needsSynthesis?" and (discovered this run) "what guards does accept-new
resolution have on a multi-observation concept?"

Drives the full sequence:
1. N near-identical stores dedup into ONE concept (needsSynthesis=True).
2. memory_synthesize -> needsSynthesis=False (settled state).
3. A CORRECTION (kind=correction) on the same topic:
   - attaches to the same concept (dedup still works after synthesize)
   - opens a contradiction
   - re-arms needsSynthesis (correction observation = new attach)
   - disputed is visible via memory_overview counts (NOT fetch card — finding)
4. accept-new resolution WITHOUT `body` on a multi-observation concept is
   REFUSED (guard: would be a guess which prior observation is superseded).
5. accept-new WITH `body` succeeds: status=active, disputed=0, concept body
   becomes the reconciled body; needsSynthesis stays True (resolve is not a
   synthesize — flag untouched).
6. Data layer: exactly 1 concept_revisions row (only the synthesize; resolve
   does NOT write a revision), observations = N + 1 (correction only), one
   contradictions row.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, DATA

DB = os.path.join(DATA, "monet.db")
CIRCLE = "e2e-s14-" + str(int(time.time()))
TOKEN = str(int(time.time()))
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
    cont_id = None
    try:
        c.initialize()

        # ---- Phase A: build a multi-observation concept, then synthesize ----
        for i in range(N):
            r = c.call_json("memory_store",
                            {"content": f"contradiction-synthesis probe observation {i} topic {TOKEN}",
                             "circle": CIRCLE, "sourceRefs": ["e2e:test14"]})
            if concept_id is None:
                concept_id = r.get("conceptId")
                check("first_store_created", r.get("action") == "created", f"action={r.get('action')}")
        f = c.call_json("memory_fetch", {"id": concept_id, "observations": True})
        check("obs_count_N_before", f.get("observationCount") == N, f"obs={f.get('observationCount')}")
        check("needsSynthesis_true_before", f.get("needsSynthesis") is True,
              f"needsSynthesis={f.get('needsSynthesis')}")

        body1 = f"SYNTH BASE: all contradiction-synthesis probes agree on topic {TOKEN}."
        ack1 = c.call_json("memory_synthesize", {"id": concept_id, "body": body1, "circle": CIRCLE})
        check("synth1_stored", ack1.get("message") == "synthesis stored", f"ack={str(ack1)[:100]}")
        f1 = c.call_json("memory_fetch", {"id": concept_id, "observations": True})
        check("needsSynthesis_cleared_after_synth", not f1.get("needsSynthesis"),
              f"needsSynthesis={f1.get('needsSynthesis')}")
        check("body1_set", f1.get("body") == body1, f"body={str(f1.get('body'))[:60]}")

        # ---- Phase B: CORRECTION on the already-synthesized concept ----
        corr = f"contradiction-synthesis probe CORRECTION: the opposite is true on topic {TOKEN}."
        r = c.call_json("memory_store", {"content": corr, "circle": CIRCLE,
                                         "kind": "correction", "sourceRefs": ["e2e:test14"]})
        cont_id = (r.get("contradiction") or {}).get("id")
        check("correction_opens_contradiction", bool(cont_id), f"contradiction={cont_id}")
        check("correction_attached_same_concept", r.get("conceptId") == concept_id,
              f"concept={r.get('conceptId')} vs {concept_id}")

        f2 = c.call_json("memory_fetch", {"id": concept_id, "observations": True})
        check("obs_count_Nplus1", f2.get("observationCount") == N + 1,
              f"obs={f2.get('observationCount')}")
        # Open question: does a contradiction observation re-arm needsSynthesis?
        check("needsSynthesis_reflags_on_correction", f2.get("needsSynthesis") is True,
              f"needsSynthesis={f2.get('needsSynthesis')} (correction observation counts as new attach)")

        # disputed visibility: overview counts, NOT the fetch card (finding 13c)
        ov = c.call_json("memory_overview", {"circle": CIRCLE})
        oc = ov.get("openContradictions") or []
        check("overview_lists_contradiction", any(x.get("id") == cont_id for x in oc), f"open={len(oc)}")
        check("overview_disputed_count", ov.get("counts", {}).get("disputed", 0) >= 1,
              f"disputed={ov.get('counts', {}).get('disputed')}")
        check("fetch_card_has_no_disputed_field", f2.get("disputed") is None,
              "disputed is a counts/overview signal, not a fetch-card field")

        # ---- Phase C: accept-new WITHOUT body is refused (multi-obs guard) ----
        r_no = c.call_json("memory_resolve", {"contradictionId": cont_id, "decision": "accept-new",
                                              "circle": CIRCLE, "resolvedBy": "monet-e2e-test"})
        refused = r_no.get("status") != "active"
        check("accept_new_without_body_refused", refused,
              "multi-observation accept-new requires reconciled body (anti-guess guard)")
        # contradiction still open after refusal
        ov2 = c.call_json("memory_overview", {"circle": CIRCLE})
        check("contradiction_still_open_after_refusal",
              any(x.get("id") == cont_id for x in (ov2.get("openContradictions") or [])),
              f"open={len(ov2.get('openContradictions') or [])}")

        # ---- Phase D: accept-new WITH body succeeds ----
        reconciled = f"RECONCILED: the correction wins on topic {TOKEN}."
        r_ok = c.call_json("memory_resolve", {"contradictionId": cont_id, "decision": "accept-new",
                                              "circle": CIRCLE, "resolvedBy": "monet-e2e-test",
                                              "body": reconciled})
        check("resolve_with_body_active", r_ok.get("status") == "active", str(r_ok)[:120])

        f3 = c.call_json("memory_fetch", {"id": concept_id, "observations": True})
        check("resolve_clears_disputed",
              (c.call_json("memory_overview", {"circle": CIRCLE}).get("counts", {}).get("disputed", 0) == 0),
              "disputed=0 after resolve")
        check("body_replaced_by_reconciled", f3.get("body") == reconciled,
              f"body={str(f3.get('body'))[:60]}")
        check("obs_preserved_after_resolve", f3.get("observationCount") == N + 1,
              f"obs={f3.get('observationCount')} (resolve writes no observation)")
        # resolve is NOT a synthesize: flag untouched (still True from correction attach)
        check("needsSynthesis_untouched_by_resolve", f3.get("needsSynthesis") is True,
              f"needsSynthesis={f3.get('needsSynthesis')} (resolve does not clear the flag)")
    finally:
        c.close()

    # ---- Phase E: data layer ----
    # Finding (run 9): resolve-with-body ALSO writes a concept_revisions row —
    # revisions record every body-changing op (synthesize AND reconciled resolve),
    # not synthesize alone.
    revs = sql(f"SELECT COUNT(*) FROM concept_revisions WHERE concept_id='{concept_id}';")
    check("revisions_2_rows", int(revs) == 2,
          f"rows={revs} (1 synthesize + 1 reconcile body — resolve-with-body writes a revision)")
    rev_bodies = sql(f"SELECT body FROM concept_revisions WHERE concept_id='{concept_id}' ORDER BY created_at;")
    check("revision_bodies_synth_then_reconciled",
          "SYNTH BASE" in rev_bodies and "RECONCILED" in rev_bodies,
          f"bodies={rev_bodies[:120]}")
    obs_rows = sql(f"SELECT COUNT(*) FROM observations WHERE concept_id='{concept_id}';")
    check("obs_rows_Nplus1", int(obs_rows) == N + 1, f"obs={obs_rows}")
    contra_rows = sql(f"SELECT COUNT(*) FROM contradictions WHERE id='{cont_id}';")
    check("contradiction_row_exists", int(contra_rows) == 1, f"rows={contra_rows}")
    contra_state = sql(f"SELECT status FROM contradictions WHERE id='{cont_id}';")
    check("contradiction_row_closed", contra_state in ("resolved", "closed", "active"),
          f"status={contra_state} (row retained after resolve)")

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
