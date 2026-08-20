#!/usr/bin/env python3
"""Scenario 6/11 extension: memory_retire / memory_restore round-trip (1.6.1 tools).

Answers run-17 next step #1: retire/restore beyond the test20 guard arm. The
retire path was E2E-tested only as a refusal (pair flag) and a refuse-arm for
flagging; restore had ZERO E2E coverage. This test pins the full round-trip:

A. retire hides from all retrieval surfaces (search/fetch/list/overview counts)
   while the evidence stays untouched (observations/segments/tokens rows intact)
B. retire is idempotent: a second retire on a retired concept returns a success ack
C. restore brings the concept back (same body, searchable/listed/counted again);
   tombstone row retained, restoration row written, status back to 'active'
D. graph re-derivation (the documented claim): retire DELETES all concept edges;
   restore REBUILDS them from evidence — about/co_occurred/related return with
   count=1 and fresh last_reinforced_at, but the follows (ordering) edge does NOT
   survive the round trip (ordering/reinforcement history lost)
E. open contradiction blocks retire (doc tension resolved: MCP handler refuses
   BEFORE any auto-close; retire-delete-gap.md wins); dismiss -> retire succeeds
F. declared principle refuses retire naming memory_ratify as the withdraw tool;
   memory_ratify verdict='retire' -> retire succeeds
G. restore is idempotent on an active concept (success ack, no error)
H. wrong-circle retire is refused as "concept not found" (circle scoping)

GR-06: fresh circle + content token per run; all content carries the token.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, DATA

DB = os.path.join(DATA, "monet.db")
TS = str(int(time.time()))
CIRCLE = "e2e-s21-" + TS
OTHER = "e2e-other21-" + TS
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


def dismiss_dup_pairs(c, circle, cid):
    """Find-21 recovery: retire REFUSES a concept that carries an UNDISMISSED
    possible_duplicate_of pair flag ('erase rather than answer'). Storing
    structurally-similar / token-sharing sentences intermittently auto-pairs
    them (contradiction-processing.md §4a, line ~273), so defensively dismiss
    any open possible_duplicate_of pair before retiring. memory_resolve with
    conceptAId/conceptBId -> {action:'pair-flags-dismissed', rowsUpdated:2};
    then retire proceeds. This makes ARM A/D/E/F robust to auto-pairing."""
    rows = sql(
        f"SELECT src_id, dst_id FROM memory_edge "
        f"WHERE type='possible_duplicate_of' AND dismissed_at IS NULL "
        f"AND (src_id='{cid}' OR dst_id='{cid}');")
    partners = []
    for line in rows.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) < 2:
            continue
        src, dst = parts[0], parts[1]
        partner = dst if src == cid else src
        partners.append(partner)
    for p in partners:
        c.call_json("memory_resolve", {"conceptAId": cid, "conceptBId": p, "circle": circle})
    return partners


def main():
    c = MonetClient(DATA)
    try:
        c.initialize()

        # ============ ARM A+B+C: single-concept round trip ============
        content = f"The orbital cargo manifest for run {TOKEN} lists 7 pods."
        r = c.call_json("memory_store", {"content": content, "circle": CIRCLE,
                                         "sourceRefs": ["e2e:test21"]})
        cid = r.get("conceptId")
        check("a_created", r.get("action") == "created" and bool(cid), f"id={cid}")

        s0 = c.call_json("memory_search", {"query": "orbital cargo manifest", "circle": CIRCLE})
        check("a_searchable_before", cid in [x.get("id") for x in (s0.get("results") or [])],
              f"hits={[x.get('id') for x in (s0.get('results') or [])]}")

        ov0 = c.call_json("memory_overview", {"circle": CIRCLE})
        concepts0 = (ov0.get("counts") or {}).get("concepts", 0)

        # --- retire ---
        dismiss_dup_pairs(c, CIRCLE, cid)
        rr = c.call_json("memory_retire", {"id": cid, "circle": CIRCLE})
        check("a_retire_ack", rr.get("action") == "retired" and rr.get("conceptId") == cid,
              f"action={rr.get('action')}")
        check("a_retire_msg", "out of memory_search" in str(rr.get("message", "")),
              f"msg={str(rr.get('message'))[:70]}")

        # surfaces hidden
        f = c.call_json("memory_fetch", {"id": cid})
        check("a_fetch_not_found", "concept not found" in str(f.get("_rawText", f)),
              f"fetch={str(f)[:70]}")
        s1 = c.call_json("memory_search", {"query": "orbital cargo manifest", "circle": CIRCLE})
        check("a_search_misses", cid not in [x.get("id") for x in (s1.get("results") or [])],
              f"hits={[x.get('id') for x in (s1.get('results') or [])]}")
        lst = c.call_json("memory_list", {"circle": CIRCLE, "limit": 100})
        mem_ids = [x.get("id") for x in (lst.get("memories") or [])]
        check("a_list_excludes", cid not in mem_ids, f"memories={len(mem_ids)}")
        ov1 = c.call_json("memory_overview", {"circle": CIRCLE})
        concepts1 = (ov1.get("counts") or {}).get("concepts", 0)
        check("a_overview_drops", concepts1 == concepts0 - 1,
              f"concepts {concepts0} -> {concepts1}")

        # evidence untouched
        obs = sql(f"SELECT COUNT(*) FROM observations WHERE concept_id='{cid}';")
        segs = sql(f"SELECT COUNT(*) FROM observation_segments WHERE observation_id IN (SELECT id FROM observations WHERE concept_id='{cid}');")
        toks = sql(f"SELECT COUNT(*) FROM observation_tokens WHERE observation_id IN (SELECT id FROM observations WHERE concept_id='{cid}');")
        check("a_evidence_untouched", obs == "1" and segs == "1" and int(toks or 0) >= 1,
              f"obs={obs} segs={segs} toks={toks}")
        tomb = sql(f"SELECT COUNT(*) FROM concept_tombstones WHERE concept_id='{cid}';")
        status = sql(f"SELECT status FROM concepts WHERE id='{cid}';")
        check("a_tombstone_written", tomb == "1", f"tombstones={tomb}")
        check("a_status_retired", status == "retired", f"status={status}")

        # --- retire idempotent (B) ---
        rr2 = c.call_json("memory_retire", {"id": cid, "circle": CIRCLE})
        check("b_retire_again_success", rr2.get("action") == "retired",
              f"action={rr2.get('action')} err={str(rr2.get('_rawText', ''))[:80]}")
        tomb2 = sql(f"SELECT COUNT(*) FROM concept_tombstones WHERE concept_id='{cid}';")
        check("b_no_second_tombstone", tomb2 == "1", f"tombstones={tomb2}")

        # --- restore (C) ---
        res = c.call_json("memory_restore", {"id": cid, "circle": CIRCLE})
        check("c_restore_ack", res.get("action") == "restored" and res.get("conceptId") == cid,
              f"action={res.get('action')}")
        f2 = c.call_json("memory_fetch", {"id": cid})
        check("c_fetch_same_body", f2.get("body") == content, f"body={str(f2.get('body'))[:60]}")
        check("c_fetch_kind", f2.get("kind") == "fact", f"kind={f2.get('kind')}")
        s2 = c.call_json("memory_search", {"query": "orbital cargo manifest", "circle": CIRCLE})
        check("c_searchable_again", cid in [x.get("id") for x in (s2.get("results") or [])],
              f"hits={[x.get('id') for x in (s2.get('results') or [])]}")
        lst2 = c.call_json("memory_list", {"circle": CIRCLE, "limit": 100})
        mem_ids2 = [x.get("id") for x in (lst2.get("memories") or [])]
        check("c_list_includes", cid in mem_ids2, f"memories={len(mem_ids2)}")
        ov2 = c.call_json("memory_overview", {"circle": CIRCLE})
        concepts2 = (ov2.get("counts") or {}).get("concepts", 0)
        check("c_overview_restored", concepts2 == concepts0, f"concepts={concepts2}")

        rest_row = sql(f"SELECT COUNT(*) FROM concept_restorations WHERE concept_id='{cid}';")
        tomb3 = sql(f"SELECT COUNT(*) FROM concept_tombstones WHERE concept_id='{cid}';")
        status2 = sql(f"SELECT status FROM concepts WHERE id='{cid}';")
        check("c_restoration_written", rest_row == "1", f"restorations={rest_row}")
        check("c_tombstone_retained", tomb3 == "1", f"tombstones={tomb3}")
        check("c_status_active", status2 == "active", f"status={status2}")

        # --- restore idempotent on ACTIVE concept (G) ---
        res2 = c.call_json("memory_restore", {"id": cid, "circle": CIRCLE})
        check("g_restore_active_success", res2.get("action") == "restored",
              f"action={res2.get('action')} err={str(res2.get('_rawText', ''))[:80]}")

        # ============ ARM D: graph re-derivation ============
        ta, tb = TOKEN + "-zeta", TOKEN + "-eta"
        rA = c.call_json("memory_store", {"content": f"The {ta} reactor coolant flow is 40 L/s.",
                                          "circle": CIRCLE, "sourceRefs": ["e2e:test21"]})
        a = rA.get("conceptId")
        rB = c.call_json("memory_store", {"content": f"The {tb} reactor fuel rod count is 96.",
                                          "circle": CIRCLE, "sourceRefs": ["e2e:test21"]})
        b = rB.get("conceptId")
        check("d_two_concepts", bool(a) and bool(b) and a != b, f"A={a[:8]} B={b[:8]}")

        def edge_types(cid_):
            rows = sql(f"SELECT type || '~' || count || '~' || last_reinforced_at FROM memory_edge "
                       f"WHERE src_id='{cid_}' OR dst_id='{cid_}' ORDER BY type;")
            return [r.split("~") for r in rows.split("\n") if r]

        def pair_edges(cid_a, cid_b):
            rows = sql(f"SELECT type || '~' || count || '~' || last_reinforced_at FROM memory_edge "
                       f"WHERE (src_id='{cid_a}' AND dst_id='{cid_b}') OR (src_id='{cid_b}' AND dst_id='{cid_a}') "
                       f"ORDER BY type;")
            return [r.split("~") for r in rows.split("\n") if r]

        before = pair_edges(a, b)
        types_before = sorted(x[0] for x in before)
        check("d_edges_before", "follows" in types_before and len(before) >= 4,
              f"types={types_before}")
        max_reinf_before = max(int(x[2]) for x in before)

        dismiss_dup_pairs(c, CIRCLE, a)
        rrA = c.call_json("memory_retire", {"id": a, "circle": CIRCLE})
        check("d_retire_ok", rrA.get("action") == "retired", f"action={rrA.get('action')}")
        after_retire = pair_edges(a, b)
        check("d_edges_deleted_on_retire", len(after_retire) == 0, f"pair_edges={len(after_retire)}")
        check("d_partner_pair_edges_deleted", "co_occurred" not in [x[0] for x in pair_edges(b, a)],
              f"B->A edges after retire: {len(pair_edges(b, a))} (pair edges removed both directions)")

        resA = c.call_json("memory_restore", {"id": a, "circle": CIRCLE})
        check("d_restore_ok", resA.get("action") == "restored", f"action={resA.get('action')}")
        after = pair_edges(a, b)
        types_after = sorted(x[0] for x in after)
        check("d_edges_rebuilt", len(after) >= 4, f"pair_edges={len(after)} types={types_after}")
        check("d_about_cooccurred_back",
              "about" in types_after and "co_occurred" in types_after and "related" in types_after,
              f"types={types_after}")
        check("d_follows_lost", "follows" not in types_after,
              f"follows re-derived after restore (expected LOST — types={types_after})")
        check("d_counts_reset", all(int(x[1]) == 1 for x in after),
              f"counts={sorted(set(int(x[1]) for x in after))}")
        max_reinf_after = max(int(x[2]) for x in after)
        check("d_reinforcement_reset", max_reinf_after > max_reinf_before,
              f"last_reinforced_at {max_reinf_before} -> {max_reinf_after} (fresh)")
        check("d_pair_rebuilt_both_ways", len(pair_edges(b, a)) == len(after),
              f"B->A={len(pair_edges(b, a))} A->B={len(after)} (symmetric rebuild)")

        # ============ ARM E: open contradiction blocks retire ============
        claim_e = f"The harbor tug fleet for {TOKEN} has 5 vessels."
        rE = c.call_json("memory_store", {"content": claim_e, "circle": CIRCLE,
                                          "sourceRefs": ["e2e:test21"]})
        ce = rE.get("conceptId")
        fl = c.call_json("memory_flag_contradiction",
                         {"conceptId": ce, "detail": f"stale on {TOKEN}",
                          "kind": "staleness", "circle": CIRCLE})
        cont = fl.get("contradictionId")
        check("e_flag_open", bool(cont) and fl.get("status") == "open", f"contradictionId={cont}")

        re_ = c.call_json("memory_retire", {"id": ce, "circle": CIRCLE})
        err_e = str(re_.get("_rawText", ""))
        check("e_retire_refused", "open contradiction" in err_e, f"err={err_e[:90]}")
        n_open = sql(f"SELECT COUNT(*) FROM contradictions WHERE concept_id='{ce}' AND status='open';")
        check("e_rows_untouched", n_open == "1", f"open={n_open}")
        st = sql(f"SELECT status FROM concepts WHERE id='{ce}';")
        check("e_concept_not_retired", st == "disputed", f"status={st}")

        # dismiss -> retire succeeds
        rd = c.call_json("memory_resolve", {"contradictionId": cont, "decision": "dismiss",
                                            "circle": CIRCLE, "resolvedBy": "monet-e2e-test"})
        check("e_dismiss_ok", rd.get("status") == "active", f"ack={str(rd)[:80]}")
        re2 = c.call_json("memory_retire", {"id": ce, "circle": CIRCLE})
        check("e_retire_after_dismiss", re2.get("action") == "retired",
              f"action={re2.get('action')} err={str(re2.get('_rawText', ''))[:80]}")
        if re2.get("action") != "retired":
            dismiss_dup_pairs(c, CIRCLE, ce)
            re2 = c.call_json("memory_retire", {"id": ce, "circle": CIRCLE})
            check("e_retire_after_pair_dismiss", re2.get("action") == "retired",
                  f"action={re2.get('action')} err={str(re2.get('_rawText', ''))[:80]}")
        c.call_json("memory_restore", {"id": ce, "circle": CIRCLE})

        # ============ ARM F: declared principle refuses retire; ratify withdraws ============
        dec = c.call_json("memory_declare", {"content": f"The {TOKEN} principle is: verify telemetry before signoff.",
                                             "circle": CIRCLE, "species": "principle",
                                             "exitsEvidence": f"telemetry missing for {TOKEN}"})
        did = dec.get("conceptId")
        check("f_declared", bool(did) and dec.get("action") == "created", f"id={did}")
        rf = c.call_json("memory_retire", {"id": did, "circle": CIRCLE})
        err_f = str(rf.get("_rawText", ""))
        check("f_retire_refused", "skeleton member by ratification" in err_f and "memory_ratify" in err_f,
              f"err={err_f[:110]}")

        rat = c.call_json("memory_ratify", {"candidateId": did, "verdict": "retire", "circle": CIRCLE})
        check("f_ratify_retire", rat.get("verdict") == "retire" and bool(rat.get("ratificationId")),
              f"ack={str(rat)[:100]}")
        rat_row = sql(f"SELECT verdict FROM ratifications WHERE subject_concept_id='{did}' ORDER BY created_at DESC LIMIT 1;")
        check("f_ratification_row", rat_row == "retire", f"verdict={rat_row}")

        rf2 = c.call_json("memory_retire", {"id": did, "circle": CIRCLE})
        check("f_retire_after_ratify", rf2.get("action") == "retired",
              f"action={rf2.get('action')} err={str(rf2.get('_rawText', ''))[:80]}")
        if rf2.get("action") != "retired":
            dismiss_dup_pairs(c, CIRCLE, did)
            rf2 = c.call_json("memory_retire", {"id": did, "circle": CIRCLE})
            check("f_retire_after_pair_dismiss", rf2.get("action") == "retired",
                  f"action={rf2.get('action')} err={str(rf2.get('_rawText', ''))[:80]}")
        c.call_json("memory_restore", {"id": did, "circle": CIRCLE})

        # ============ ARM H: wrong-circle retire refused ============
        claim_h = f"The polar beacon duty roster for {TOKEN} has 4 entries."
        rH = c.call_json("memory_store", {"content": claim_h, "circle": CIRCLE,
                                          "sourceRefs": ["e2e:test21"]})
        ch = rH.get("conceptId")
        rh = c.call_json("memory_retire", {"id": ch, "circle": OTHER})
        err_h = str(rh.get("_rawText", ""))
        check("h_wrong_circle_refused", "concept not found" in err_h, f"err={err_h[:80]}")
        st_h = sql(f"SELECT status FROM concepts WHERE id='{ch}';")
        check("h_not_retired", st_h == "active", f"status={st_h}")
    finally:
        c.close()

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
