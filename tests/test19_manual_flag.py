#!/usr/bin/env python3
"""Scenario 6 extension: MANUAL memory_flag_contradiction opener.

Answers run-13 next step #2: the manual flag path was source-documented
(contradiction-processing.md section 1b/1c) but had ZERO E2E coverage — every
contradiction test (06/14/15/16/17/18) drove the store-side auto-flag via
kind="correction". This test pins the manual opener end-to-end:

A. basic staleness flag -> open row, derived 'disputed' status on the fetch
   card, confidence -0.3 (floor 0.1), arousal +3, detail passthrough
B. kinds stack (value-conflict with observationId, scope-conflict) -> 3 open
   rows, observation_id passthrough, confidence floor, arousal stacking
C. wrong circle -> refused with "concept not found" (circle-scoping, count
   unchanged)
D. rule concept -> refused ("is a rule and cannot be flagged"), zero rows
E. retired concept (memory_retire — first E2E use of the 1.6.1 tool) ->
   refused ("cannot mutate a retired concept"), zero rows

GR-06: fresh circle + content token per run; all content carries the token so
re-runs never attach to leftovers.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, DATA

DB = os.path.join(DATA, "monet.db")
TS = str(int(time.time()))
CIRCLE = "e2e-s19-" + TS
TOKEN = TS
OTHER = "e2e-other-" + TS

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

        # ---- fixture: a plain claim about topic X ----
        claim = f"The manual flag probe budget for project {TOKEN} is 55 hours."
        r = c.call_json("memory_store", {"content": claim, "circle": CIRCLE,
                                         "sourceRefs": ["e2e:test19"]})
        cid = r.get("conceptId")
        check("claim_created", r.get("action") == "created" and bool(cid), f"id={cid}")

        base_conf = float(sql(f"SELECT confidence FROM concepts WHERE id='{cid}';"))
        base_arousal = int(sql(f"SELECT arousal_score FROM concepts WHERE id='{cid}';"))
        check("baseline_read", base_conf > 0, f"base_conf={base_conf} base_arousal={base_arousal}")

        # ================= ARM A: basic manual flag (staleness) =================
        detail_a = f"superseded by newer data on {TOKEN}"
        r = c.call_json("memory_flag_contradiction",
                        {"conceptId": cid, "detail": detail_a, "kind": "staleness",
                         "circle": CIRCLE})
        cid_a = r.get("contradictionId")
        check("a_ack_has_contradiction_id", bool(cid_a), f"contradictionId={cid_a}")
        check("a_ack_status_open", r.get("status") == "open", f"status={r.get('status')}")
        check("a_ack_detail_passthrough", r.get("detail") == detail_a, f"detail={str(r.get('detail'))[:60]}")
        check("a_ack_concept_matches", r.get("conceptId") == cid, f"conceptId={r.get('conceptId')}")

        row = sql(f"SELECT kind || '|' || status || '|' || COALESCE(observation_id,'NULL') FROM contradictions WHERE id='{cid_a}';")
        parts = row.split("|")
        check("a_row_kind_staleness", parts[0] == "staleness", f"kind={parts[0]}")
        check("a_row_status_open", parts[1] == "open", f"status={parts[1]}")
        check("a_row_obs_null", parts[2] == "NULL", f"observation_id={parts[2]} (manual flag w/o obs)")

        conf = float(sql(f"SELECT confidence FROM concepts WHERE id='{cid}';"))
        arousal = int(sql(f"SELECT arousal_score FROM concepts WHERE id='{cid}';"))
        exp_conf = round(max(0.1, base_conf - 0.3), 3)
        check("a_confidence_minus_0_3", abs(conf - exp_conf) < 0.01,
              f"conf {base_conf} -> {conf} (expected {exp_conf})")
        check("a_arousal_plus_3", arousal == base_arousal + 3,
              f"arousal {base_arousal} -> {arousal}")

        # derived disputed status surfaces on the FETCH card (manual flag too)
        f = c.call_json("memory_fetch", {"id": cid})
        check("a_fetch_status_disputed", f.get("status") == "disputed", f"status={f.get('status')}")
        oc = f.get("openContradictions") or []
        check("a_fetch_open_contradictions", len(oc) == 1 and oc[0].get("id") == cid_a,
              f"openContradictions={len(oc)}")

        ov = c.call_json("memory_overview", {"circle": CIRCLE})
        check("a_overview_open_1", len(ov.get("openContradictions") or []) == 1,
              f"open={len(ov.get('openContradictions') or [])}")
        check("a_overview_disputed_ge_1", ov.get("counts", {}).get("disputed", 0) >= 1,
              f"disputed={ov.get('counts', {}).get('disputed')}")

        # ================= ARM B: kinds stack + observationId passthrough =================
        # observation id of the original claim (store ack carries none — derive from DB)
        obs_id = sql(f"SELECT id FROM observations WHERE concept_id='{cid}' AND content LIKE '%{TOKEN}%' LIMIT 1;")
        check("b_obs_id_derived", bool(obs_id), f"obs_id={obs_id}")

        detail_b = f"recheck value on {TOKEN}"
        r2 = c.call_json("memory_flag_contradiction",
                         {"conceptId": cid, "detail": detail_b, "kind": "value-conflict",
                          "observationId": obs_id, "circle": CIRCLE})
        cid_b = r2.get("contradictionId")
        check("b_ack_open", r2.get("status") == "open" and bool(cid_b), f"id={cid_b}")
        row2 = sql(f"SELECT kind || '|' || COALESCE(observation_id,'NULL') FROM contradictions WHERE id='{cid_b}';")
        p2 = row2.split("|")
        check("b_row_kind_value_conflict", p2[0] == "value-conflict", f"kind={p2[0]}")
        check("b_row_obs_passthrough", p2[1] == obs_id, f"observation_id={p2[1]}")

        r3 = c.call_json("memory_flag_contradiction",
                         {"conceptId": cid, "detail": f"scope mismatch on {TOKEN}",
                          "kind": "scope-conflict", "circle": CIRCLE})
        cid_c = r3.get("contradictionId")
        check("c_ack_open", r3.get("status") == "open" and bool(cid_c), f"id={cid_c}")
        row3 = sql(f"SELECT kind FROM contradictions WHERE id='{cid_c}';")
        check("c_row_kind_scope_conflict", row3 == "scope-conflict", f"kind={row3}")

        n_open = int(sql(f"SELECT COUNT(*) FROM contradictions WHERE concept_id='{cid}' AND status='open';"))
        check("b_three_open_rows", n_open == 3, f"open={n_open}")

        conf3 = float(sql(f"SELECT confidence FROM concepts WHERE id='{cid}';"))
        check("b_confidence_floor", abs(conf3 - 0.1) < 0.01, f"conf={conf3} (floor 0.1 after 2nd flag)")
        arousal3 = int(sql(f"SELECT arousal_score FROM concepts WHERE id='{cid}';"))
        check("b_arousal_stacked", arousal3 == base_arousal + 9,
              f"arousal={arousal3} (expected {base_arousal + 9}; +3 per flag)")

        ov2 = c.call_json("memory_overview", {"circle": CIRCLE})
        check("b_overview_open_3", len(ov2.get("openContradictions") or []) == 3,
              f"open={len(ov2.get('openContradictions') or [])}")

        # ================= ARM C: wrong circle refused =================
        rc = c.call_json("memory_flag_contradiction",
                         {"conceptId": cid, "detail": f"cross-circle {TOKEN}",
                          "kind": "value-conflict", "circle": OTHER})
        err_c = rc.get("_rawText", "")
        check("c_wrong_circle_refused", "concept not found" in err_c, f"err={err_c[:80]}")
        n_after_c = int(sql(f"SELECT COUNT(*) FROM contradictions WHERE concept_id='{cid}' AND status='open';"))
        check("c_count_unchanged", n_after_c == 3, f"open={n_after_c} (no new row on refusal)")

        # ================= ARM D: rule concept refused =================
        rr = c.call_json("memory_store",
                         {"content": f"Never deploy to prod on Friday for project {TOKEN}.",
                          "kind": "rule", "circle": CIRCLE,
                          "rule": {"stage": f"e2e-deploy-{TOKEN}", "scope": "domain",
                                   "reason": "e2e fixture rule"},
                          "sourceRefs": ["e2e:test19"]})
        rule_id = rr.get("conceptId")
        check("d_rule_stored", bool(rule_id), f"rule_id={rule_id}")
        rule_kind = sql(f"SELECT kind FROM concepts WHERE id='{rule_id}';")
        check("d_rule_kind_rule", rule_kind == "rule", f"kind={rule_kind}")

        rd = c.call_json("memory_flag_contradiction",
                         {"conceptId": rule_id, "detail": f"flag rule {TOKEN}",
                          "kind": "value-conflict", "circle": CIRCLE})
        err_d = rd.get("_rawText", "")
        check("d_rule_refused", "is a rule and cannot be flagged" in err_d, f"err={err_d[:90]}")
        n_rule = int(sql(f"SELECT COUNT(*) FROM contradictions WHERE concept_id='{rule_id}';"))
        check("d_rule_zero_rows", n_rule == 0, f"contradictions(rule)={n_rule}")

        # ================= ARM E: retired concept refused =================
        claim_e = f"The legacy subsystem status flag for {TOKEN} is amber."
        r = c.call_json("memory_store", {"content": claim_e, "circle": CIRCLE,
                                         "sourceRefs": ["e2e:test19"]})
        cid_e = r.get("conceptId")
        check("e_claim_created", bool(cid_e), f"id={cid_e}")

        rret = c.call_json("memory_retire", {"id": cid_e, "circle": CIRCLE})
        check("e_retire_ack", "Retired" in str(rret.get("message", "")), f"action={rret.get('action')} msg={str(rret.get('message'))[:60]}")

        re_ = c.call_json("memory_flag_contradiction",
                          {"conceptId": cid_e, "detail": f"flag retired {TOKEN}",
                           "kind": "value-conflict", "circle": CIRCLE})
        err_e = re_.get("_rawText", "")
        check("e_retired_refused", "cannot mutate a retired concept" in err_e, f"err={err_e[:80]}")
        n_ret = int(sql(f"SELECT COUNT(*) FROM contradictions WHERE concept_id='{cid_e}';"))
        check("e_retired_zero_rows", n_ret == 0, f"contradictions(retired)={n_ret}")

        # retired concept leaves the fetch surface (1.6.1 retire semantics)
        fe = c.call_json("memory_fetch", {"id": cid_e})
        check("e_retired_not_fetchable", fe.get("status") is None and not fe.get("body"),
              f"fetch={str(fe)[:80]} (retired leaves fetch)")
    finally:
        c.close()

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
