#!/usr/bin/env python3
"""Scenario 6 extension: contradiction KEEP-CURRENT verdict path.

The verdict matrix from test14/15/16 has accept-new and dismiss E2E-pinned;
keep-current was only source-documented (RE run 11 finding 3). This test pins
its data-layer delta:

Source semantics (resolveContradiction, keep-current branch):
- loser superseded = the CORRECTION itself ({loser: r.observation_id,
  successor: null}) — priors stay live; the correction loses.
- status written: 'resolved'; resolution_obs_id = NULL (the correction lost);
  contradicted_observation_id = NULL (none named).
- body optional: given -> replaces concept body + title + writeRevision(+1);
  omitted -> body untouched, NO revision row.
- last_confirmed_at refreshed (already set at store time), arousal_score +1
  (verdict path, same as accept-new).
- needsSynthesis untouched (stays True — re-armed by the correction attach).
- concept status restored to 'active' via recompute (0 open left).

ARM A: keep-current WITHOUT body on a multi-observation concept.
ARM B: same fixture on a fresh circle, keep-current WITH body (body replace +
revision row like accept-new-with-body).
Boundary (source-only, not E2E-constructible): keep-current with NO live prior
predating the correction is refused ("no live observation predating the
correction to keep") — zero-live-obs states are blocked by the store path, so
this cannot be reached through normal flows.
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
N = 3

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


def build_and_open(c, circle):
    """Store N near-identical observations, then a correction -> open contradiction."""
    cid = None
    for i in range(N):
        r = c.call_json("memory_store",
                        {"content": f"keep-current probe observation {i} topic {TOKEN}",
                         "circle": circle, "sourceRefs": ["e2e:test17"]})
        if cid is None:
            cid = r.get("conceptId")
    corr = f"keep-current probe CORRECTION: the opposite is true on topic {TOKEN}."
    r = c.call_json("memory_store", {"content": corr, "circle": circle,
                                     "kind": "correction", "sourceRefs": ["e2e:test17"]})
    cont_id = (r.get("contradiction") or {}).get("id")
    assert cid and cont_id, f"failed to open contradiction: cid={cid} cont={cont_id}"
    return cid, cont_id


def main():
    c = MonetClient(DATA)
    try:
        c.initialize()

        # ============ ARM A: KEEP-CURRENT without body (correction loses) ============
        circle_a = "e2e-s17a-" + TS
        cid_a, cont_a = build_and_open(c, circle_a)

        body_before_a = c.call_json("memory_fetch", {"id": cid_a}).get("body")
        arousal_before_a = int(sql(f"SELECT arousal_score FROM concepts WHERE id='{cid_a}';"))
        last_conf_before_a = sql(f"SELECT COALESCE(last_confirmed_at,'') FROM concepts WHERE id='{cid_a}';")

        r_kc = c.call_json("memory_resolve", {"contradictionId": cont_a, "decision": "keep-current",
                                              "circle": circle_a, "resolvedBy": "monet-e2e-test"})
        check("keep_current_no_body_succeeds", r_kc.get("status") == "active",
              f"keep-current without body works on multi-obs concept: {str(r_kc)[:100]}")

        ov_a = c.call_json("memory_overview", {"circle": circle_a})
        check("keep_current_clears_open", len(ov_a.get("openContradictions") or []) == 0,
              f"open={len(ov_a.get('openContradictions') or [])}")
        check("keep_current_clears_disputed", ov_a.get("counts", {}).get("disputed", 0) == 0,
              f"disputed={ov_a.get('counts', {}).get('disputed')}")

        f_after_a = c.call_json("memory_fetch", {"id": cid_a, "observations": True})
        check("keep_current_keeps_body", f_after_a.get("body") == body_before_a,
              "body unchanged by keep-current without body (no verdict text injected)")
        check("keep_current_keeps_obs", f_after_a.get("observationCount") == N + 1,
              f"obs={f_after_a.get('observationCount')} (supersession is a flag, not a delete)")
        check("keep_current_does_not_clear_needsSynthesis", f_after_a.get("needsSynthesis") is True,
              f"needsSynthesis={f_after_a.get('needsSynthesis')} (resolve is not a synthesize)")

        # ============ ARM B: KEEP-CURRENT with body (body replace + revision) ============
        circle_b = "e2e-s17b-" + TS
        cid_b, cont_b = build_and_open(c, circle_b)
        body_before_b = c.call_json("memory_fetch", {"id": cid_b}).get("body")
        verdict_body = f"KEEP-CURRENT VERDICT B: the original claim stands on topic {TOKEN}."
        r_b = c.call_json("memory_resolve", {"contradictionId": cont_b, "decision": "keep-current",
                                             "circle": circle_b, "resolvedBy": "monet-e2e-test",
                                             "body": verdict_body})
        check("keep_current_with_body_succeeds", r_b.get("status") == "active", str(r_b)[:100])
        f_after_b = c.call_json("memory_fetch", {"id": cid_b})
        check("keep_current_with_body_replaces_body", f_after_b.get("body") == verdict_body,
              "keep-current WITH body replaces the concept body (like accept-new-with-body)")
    finally:
        c.close()

    # ================= Data layer =================
    # Contradiction row: resolved (NOT dismissed), resolution_obs_id NULL (correction lost)
    d_row_a = sql(f"SELECT status || '|' || COALESCE(resolution_obs_id,'NULL') || '|' || COALESCE(contradicted_observation_id,'NULL') FROM contradictions WHERE id='{cont_a}';")
    d_parts = d_row_a.split("|")
    check("keep_current_row_resolved", d_parts[0] == "resolved", f"status={d_parts[0]} (verdict branch, not dismissed)")
    check("keep_current_resolution_obs_null", d_parts[1] == "NULL", f"resolution_obs_id={d_parts[1]} (correction lost)")
    check("keep_current_contradicted_obs_null", d_parts[2] == "NULL", f"contradicted_observation_id={d_parts[2]} (none named)")
    d_meta_a = sql(f"SELECT resolved_by || '|' || COALESCE(resolved_at,'') FROM contradictions WHERE id='{cont_a}';")
    check("keep_current_sets_resolved_meta", "monet-e2e-test" in d_meta_a and d_meta_a.split("|")[1] != "",
          f"resolved_by/resolved_at populated: {d_meta_a}")

    # Supersession: the CORRECTION observation is superseded (loser), priors stay live.
    # The store ack does not carry the observation id — take it from the contradiction row.
    corr_obs_a = sql(f"SELECT observation_id FROM contradictions WHERE id='{cont_a}';")
    check("correction_obs_id_resolved", corr_obs_a != "", f"observation_id={corr_obs_a}")
    corr_sup_a = sql(f"SELECT COALESCE(superseded_by,'NULL') || '|' || COALESCE(superseded_at,'') FROM observations WHERE id='{corr_obs_a}';")
    csp = corr_sup_a.split("|")
    check("keep_current_supersedes_correction", csp[1] != "",
          f"correction observation superseded: by={csp[0]} at={csp[1]} (successor NULL)")
    check("keep_current_correction_successor_null", csp[0] == "NULL",
          "superseded_by NULL — the correction is retired with no successor (it lost)")
    live_priors_a = sql(f"SELECT COUNT(*) FROM observations WHERE concept_id='{cid_a}' AND superseded_at IS NULL AND id != '{corr_obs_a}';")
    check("keep_current_priors_stay_live", int(live_priors_a) == N,
          f"live priors after keep-current = {live_priors_a} (priors kept, only correction superseded)")

    # Revisions: no body -> no revision row (ARM A); body -> exactly 1 (ARM B)
    rev_a = sql(f"SELECT COUNT(*) FROM concept_revisions WHERE concept_id='{cid_a}';")
    rev_b = sql(f"SELECT COUNT(*) FROM concept_revisions WHERE concept_id='{cid_b}';")
    check("keep_current_no_body_writes_no_revision", int(rev_a) == 0, f"revisions(A)={rev_a}")
    check("keep_current_with_body_writes_revision", int(rev_b) == 1, f"revisions(B)={rev_b}")

    # Verdict-path side effects: last_confirmed_at set, arousal +1 (source: verdict branch)
    arousal_after_a = int(sql(f"SELECT arousal_score FROM concepts WHERE id='{cid_a}';"))
    check("keep_current_arousal_plus1", arousal_after_a == arousal_before_a + 1,
          f"arousal {arousal_before_a} -> {arousal_after_a} (+1 verdict side effect)")
    last_conf_after_a = sql(f"SELECT COALESCE(last_confirmed_at,'') FROM concepts WHERE id='{cid_a}';")
    check("keep_current_updates_last_confirmed",
          last_conf_before_a != "" and last_conf_after_a != "" and int(last_conf_after_a) > int(last_conf_before_a),
          f"last_confirmed_at refreshed by verdict: {last_conf_before_a} -> {last_conf_after_a}")

    # Observation rows: supersession is a flag — N + 1 rows remain in both arms
    obs_a = sql(f"SELECT COUNT(*) FROM observations WHERE concept_id='{cid_a}';")
    obs_b = sql(f"SELECT COUNT(*) FROM observations WHERE concept_id='{cid_b}';")
    check("obs_rows_a", int(obs_a) == N + 1, f"obs(A)={obs_a}")
    check("obs_rows_b", int(obs_b) == N + 1, f"obs(B)={obs_b}")

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
