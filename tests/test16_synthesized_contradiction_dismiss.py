#!/usr/bin/env python3
"""Scenario 6 x 10 extension: DISMISS on a SYNTHESIZED concept (contradiction).

Open questions from run 11 (next steps #2 and #3):
  #2  "Contradiction: `dismiss` with a `body` — does the handler accept it and
      record anything (e.g. detail) or ignore it?" (boundary probe)
  #3  "Scenario 6 x 10: contradiction on a SYNTHESIZED concept then dismiss —
      does dismiss interact with needsSynthesis differently than accept-new?"

This drives the FULL synthesized-contradiction-dismiss sequence (extends test14's
synth arm with test15's no-verdict verdict):

ARM A (dismiss WITHOUT body on a synthesized concept):
1. N near-identical stores dedup into ONE concept (needsSynthesis=True).
2. memory_synthesize -> needsSynthesis=False, body set (settled state).
3. CORRECTION (kind=correction) on the same topic:
   - attaches to the same concept (dedup still works after synthesize)
   - opens a contradiction
   - re-arms needsSynthesis (extends test13/14 finding to the dismiss arm)
4. DISMISS without body — succeeds on a multi-observation concept (test15) and,
   hypothesis: behaves identically on a synthesized concept (resolve handlers do
   not touch synthesize state).
5. Verify: contradiction closed (open=0, disputed=0), body NOT rewritten (keeps
   synthesized body + observation appends, no verdict text), obsCount unchanged,
   needsSynthesis STAYS True (dismiss is not a synthesize), data layer: exactly
   1 concept_revisions row (only the synthesize; dismiss writes none even on a
   synthesized concept), contradiction row retained with terminal status.

ARM B (dismiss WITH body — boundary probe, E2E-verifies RE run-11 finding 6:
the handler silently ignores `body` on dismiss; no revision, no verdict text):
6. Same fixture on a fresh circle; dismiss with a `body` param.
7. Verify: succeeds, closes the contradiction, concept body UNCHANGED (the body
   param is ignored — no verdict rewrite, no revision row added).
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, DATA

DB = os.path.join(DATA, "monet.db")
TS = str(int(time.time()))
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


def synth_then_correction(c, circle, token):
    """Store N near-identical obs -> one concept; synthesize; correction -> contradiction.
    Returns (concept_id, contradiction_id)."""
    cid = None
    for i in range(N):
        r = c.call_json("memory_store",
                        {"content": f"synth-dismiss probe observation {i} topic {token}",
                         "circle": circle, "sourceRefs": ["e2e:test16"]})
        if cid is None:
            cid = r.get("conceptId")
            check("first_store_created", r.get("action") == "created", f"action={r.get('action')}")

    f = c.call_json("memory_fetch", {"id": cid, "observations": True})
    check("obs_count_N_before", f.get("observationCount") == N, f"obs={f.get('observationCount')}")
    check("needsSynthesis_true_before", f.get("needsSynthesis") is True,
          f"needsSynthesis={f.get('needsSynthesis')}")

    body1 = f"SYNTH BASE: all synth-dismiss probes agree on topic {token}."
    ack1 = c.call_json("memory_synthesize", {"id": cid, "body": body1, "circle": circle})
    check("synth1_stored", ack1.get("message") == "synthesis stored", f"ack={str(ack1)[:100]}")
    f1 = c.call_json("memory_fetch", {"id": cid, "observations": True})
    check("needsSynthesis_cleared_after_synth", not f1.get("needsSynthesis"),
          f"needsSynthesis={f1.get('needsSynthesis')}")
    check("body1_set", f1.get("body") == body1, f"body={str(f1.get('body'))[:60]}")

    corr = f"synth-dismiss probe CORRECTION: the opposite is true on topic {token}."
    r = c.call_json("memory_store", {"content": corr, "circle": circle,
                                     "kind": "correction", "sourceRefs": ["e2e:test16"]})
    cont_id = (r.get("contradiction") or {}).get("id")
    check("correction_opens_contradiction", bool(cont_id), f"contradiction={cont_id}")
    check("correction_attached_same_concept", r.get("conceptId") == cid,
          f"concept={r.get('conceptId')} vs {cid}")

    f2 = c.call_json("memory_fetch", {"id": cid, "observations": True})
    check("obs_count_Nplus1", f2.get("observationCount") == N + 1,
          f"obs={f2.get('observationCount')}")
    check("needsSynthesis_reflags_on_correction", f2.get("needsSynthesis") is True,
          f"needsSynthesis={f2.get('needsSynthesis')} (correction observation re-arms, synth state irrelevant)")
    return cid, cont_id, f2.get("body")


def main():
    c = MonetClient(DATA)
    try:
        c.initialize()

        # ================= ARM A: DISMISS (no body) on a synthesized concept =================
        circle_a = "e2e-s16a-" + TS
        token_a = "tok-a-" + TS
        cid_a, cont_a, body_after_corr_a = synth_then_correction(c, circle_a, token_a)

        r_d = c.call_json("memory_resolve", {"contradictionId": cont_a, "decision": "dismiss",
                                             "circle": circle_a, "resolvedBy": "monet-e2e-test"})
        check("dismiss_no_body_succeeds_on_synth", r_d.get("status") == "active",
              f"dismiss without body works on synthesized concept: {str(r_d)[:100]}")

        ov_a = c.call_json("memory_overview", {"circle": circle_a})
        check("dismiss_clears_open", len(ov_a.get("openContradictions") or []) == 0,
              f"open={len(ov_a.get('openContradictions') or [])}")
        check("dismiss_clears_disputed", ov_a.get("counts", {}).get("disputed", 0) == 0,
              f"disputed={ov_a.get('counts', {}).get('disputed')}")

        f_after_a = c.call_json("memory_fetch", {"id": cid_a, "observations": True})
        check("dismiss_keeps_body_on_synth", f_after_a.get("body") == body_after_corr_a,
              "body unchanged by dismiss (synthesized body + obs appends kept, no verdict rewrite)")
        check("dismiss_keeps_obs", f_after_a.get("observationCount") == N + 1,
              f"obs={f_after_a.get('observationCount')} (dismiss writes no observation)")
        check("dismiss_does_not_clear_needsSynthesis", f_after_a.get("needsSynthesis") is True,
              f"needsSynthesis={f_after_a.get('needsSynthesis')} (dismiss is not a synthesize; synth state not restored)")

        # ============ ARM B: DISMISS WITH a body — boundary probe (RE run-11 finding 6) ============
        circle_b = "e2e-s16b-" + TS
        token_b = "tok-b-" + TS
        cid_b, cont_b, body_after_corr_b = synth_then_correction(c, circle_b, token_b)

        r_db = c.call_json("memory_resolve", {"contradictionId": cont_b, "decision": "dismiss",
                                              "circle": circle_b, "resolvedBy": "monet-e2e-test",
                                              "body": f"VERDICT-TEXT-B: should be ignored on topic {token_b}."})
        check("dismiss_with_body_succeeds", r_db.get("status") == "active",
              f"dismiss with body still succeeds: {str(r_db)[:100]}")

        ov_b = c.call_json("memory_overview", {"circle": circle_b})
        check("dismiss_with_body_closes", len(ov_b.get("openContradictions") or []) == 0
              and ov_b.get("counts", {}).get("disputed", 0) == 0,
              f"open={len(ov_b.get('openContradictions') or [])} disputed={ov_b.get('counts', {}).get('disputed')}")

        f_after_b = c.call_json("memory_fetch", {"id": cid_b, "observations": True})
        check("dismiss_with_body_ignores_body", f_after_b.get("body") == body_after_corr_b
              and "VERDICT-TEXT-B" not in (f_after_b.get("body") or ""),
              "body param silently ignored on dismiss — no verdict text injected, body unchanged")
    finally:
        c.close()

    # ================= Data layer =================
    # ARM A: contradiction row retained, terminal status, resolved meta set
    d_status_a = sql(f"SELECT status FROM contradictions WHERE id='{cont_a}';")
    check("dismiss_row_terminal_status", d_status_a in ("dismissed", "resolved", "closed"),
          f"status={d_status_a} (row retained, no longer open)")
    d_meta_a = sql(f"SELECT resolved_by || '|' || COALESCE(resolved_at,'') FROM contradictions WHERE id='{cont_a}';")
    check("dismiss_sets_resolved_meta", "monet-e2e-test" in d_meta_a and d_meta_a.split("|")[1] != "",
          f"resolved_by/resolved_at populated: {d_meta_a}")
    d_kind_a = sql(f"SELECT kind FROM contradictions WHERE id='{cont_a}';")
    check("dismiss_retains_kind", d_kind_a == "value-conflict", f"kind={d_kind_a}")

    # ARM B: same row semantics for the with-body dismiss
    d_status_b = sql(f"SELECT status FROM contradictions WHERE id='{cont_b}';")
    check("dismiss_with_body_row_terminal_status", d_status_b in ("dismissed", "resolved", "closed"),
          f"status={d_status_b}")

    # Revisions: exactly 1 (the synthesize) in BOTH arms — dismiss writes NO revision,
    # even with a body param (RE run-11: revisions record body-changing ops only).
    rev_a = sql(f"SELECT COUNT(*) FROM concept_revisions WHERE concept_id='{cid_a}';")
    rev_b = sql(f"SELECT COUNT(*) FROM concept_revisions WHERE concept_id='{cid_b}';")
    check("dismiss_no_body_writes_no_revision", int(rev_a) == 1,
          f"revisions(A)={rev_a} (1 = synthesize only)")
    check("dismiss_with_body_writes_no_revision", int(rev_b) == 1,
          f"revisions(B)={rev_b} (1 = synthesize only; body param produced no revision)")

    # Observations: N + 1 correction in both arms
    obs_a = sql(f"SELECT COUNT(*) FROM observations WHERE concept_id='{cid_a}';")
    obs_b = sql(f"SELECT COUNT(*) FROM observations WHERE concept_id='{cid_b}';")
    check("obs_rows_a", int(obs_a) == N + 1, f"obs(A)={obs_a}")
    check("obs_rows_b", int(obs_b) == N + 1, f"obs(B)={obs_b}")

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
