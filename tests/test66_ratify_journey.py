#!/usr/bin/env python3
"""Scenario 13 — rule RATIFICATION (memory_ratify): the human-approval surface of the skeleton.

Why this scenario. The released 1.11.0 roster advertises 21 tools and `memory_ratify` is
one of them, yet only ONE of its four verdicts had ever been driven on the live stdio
path (`retire`, test21 arm F). Everything else the tool's own description promises had
zero end-to-end evidence:

  * "Approve/re-ratify enters ... reject keeps it out; retire ends current membership.
     The latest verdict governs membership, while every verdict remains in history."
  * "Name `entrance` so the record can later say whether anything gated this entry:
     extraction requires `battery` (all four gates answered), declaration forbids it
     because sovereignty replaced the test." — the monet-core#142 "which principles
     entered untested?" feature.
  * "`memberRuleIds` ... Linked only for approve/re-ratify; invalid for preferences."
  * "`packet` preserves exactly what the human saw" (stored verbatim, never parsed).
  * Refusals: retired candidate, disputed candidate, non-candidate kind, wrong circle.

This test drives the whole journey through MCP tool calls against a FRESH isolated
store, reads every effect back on a public surface (`memory_overview` for the on-demand
curation view, `agent_context` for the always-on narrow view), and finishes with a
FRESH-PROCESS readback so a ruling that only lived in process memory cannot pass.

The two-projection check is the sharpest one here: the SAME membership must reach
`agent_context` WITHOUT `entrance`/`battery` (always-on minimization) and
`memory_overview` WITH them (on-demand auditability). A leak in either direction is a
real design violation (monet-core#142), not a formatting nit.

Isolation: private temp store (`-d <tmp>`), never the prod store or the shared test
store; no HOME override, so the real embedder cache is reused read-only (see the
skill's HOME-redirect trap). Re-run safe: timestamped circle + content token.

Exit 0 = PASS, 1 = FAIL (any check failed), 5 = STALE (harness could not reach a verdict).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient  # noqa: E402

KEEP = bool(os.environ.get("MONET_KEEP_STORE"))
STORE = tempfile.mkdtemp(prefix="r127-ratify-")
DB = os.path.join(STORE, "monet.db")
TS = int(time.time())
CIRCLE = "e2e-ratify-%d" % TS
OTHER = "e2e-ratify-other-%d" % TS
TOKEN = "RTFY%d" % TS

PASS = []
FAIL = []
NOTES = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print("  PASS %s%s" % (name, ("  [%s]" % detail) if detail else ""))
    else:
        FAIL.append(name)
        print("  FAIL %s%s" % (name, ("  [%s]" % detail) if detail else ""))


def note(msg):
    NOTES.append(msg)
    print("  note %s" % msg)


def wtext(resp):
    """A core refusal arrives as non-JSON text; call_json wraps it as _rawText."""
    if isinstance(resp, dict):
        return str(resp.get("_rawText", ""))
    return str(resp)


def refused(resp, needle):
    if not isinstance(resp, dict) or "_rawText" not in resp:
        return False
    return needle.lower() in wtext(resp).lower()


def said(ok, resp, needle):
    return ok and refused(resp, needle)


def why(resp):
    return wtext(resp).replace("\n", " ")[:160]


def skeleton(ov):
    if not isinstance(ov, dict):
        return []
    entries = ov.get("skeleton")
    return entries if isinstance(entries, list) else []


def ids(ov):
    return [e.get("conceptId") for e in skeleton(ov)]


def entry(ov, cid):
    for e in skeleton(ov):
        if e.get("conceptId") == cid:
            return e
    return None


def ent_of(ov, cid):
    e = entry(ov, cid)
    return None if e is None else e.get("entrance", "<absent>")


def sql(query):
    """Diagnostic-only reads (WAL: safe alongside the running server)."""
    try:
        out = subprocess.run(["sqlite3", DB, query], capture_output=True, text=True, timeout=20)
        return out.stdout.strip()
    except Exception as exc:  # pragma: no cover
        NOTES.append("sql failed: %r" % (exc,))
        return ""


def verdict_history(concept_id):
    """(row count, latest verdict, latest entrance) — the 'every verdict remains in
    history' half of the contract, which no wire surface exposes."""
    rows = sql(
        "SELECT COUNT(*), (SELECT verdict FROM ratifications r2 WHERE r2.subject_concept_id='%s' "
        "ORDER BY r2.rowid DESC LIMIT 1), (SELECT entrance FROM ratifications r3 "
        "WHERE r3.subject_concept_id='%s' ORDER BY r3.rowid DESC LIMIT 1) FROM ratifications "
        "WHERE subject_concept_id='%s';" % (concept_id, concept_id, concept_id)
    )
    if not rows or "|" not in rows:
        return (None, None, None)
    parts = rows.split("|")
    try:
        n = int(parts[0])
    except ValueError:
        n = None
    return (n, parts[1] if len(parts) > 1 else None, parts[2] if len(parts) > 2 else None)


def passed_gate(gate, evidence_ref=None):
    d = {"gate": gate, "passed": True}
    if evidence_ref is not None:
        d["evidenceRef"] = evidence_ref
    return d


def failed_gate(gate):
    return {"gate": gate, "passed": False}


def dismiss_dup_pairs(c, circle, cid):
    """Find-21 recovery, same as test21: memory_retire refuses a concept carrying an
    undismissed PAIR_FLAG (possible_duplicate_of OR extraction_candidate); dismiss any
    open pair first. Both types count — an extraction_candidate edge blocks a retire too.

    Pair shape is `conceptAId` + `conceptBId` ONLY: passing `decision` alongside them is
    refused by name (decision belongs to the contradiction-verdict path). Pair rows are
    written BIDIRECTIONALLY, so dedupe the partners before calling."""
    rows = sql(
        "SELECT src_id, dst_id FROM memory_edge WHERE type IN ('possible_duplicate_of','extraction_candidate') "
        "AND dismissed_at IS NULL AND (src_id='%s' OR dst_id='%s');" % (cid, cid)
    )
    partners = []
    responses = []
    for line in rows.split("\n"):
        if "|" not in line:
            continue
        src, dst = line.split("|")[:2]
        partner = dst if src == cid else src
        if partner not in partners:
            partners.append(partner)
    for partner in partners:
        res = c.call_json("memory_resolve", {"circle": circle, "conceptAId": cid, "conceptBId": partner})
        print("  note pair dismissal %s <-> %s -> %s" % (cid[:8], partner[:8], str(res)[:110]))
        responses.append(res)
    return responses


def main():
    print("== scenario 13: ratify journey (store %s, circle %s) ==" % (STORE, CIRCLE))
    c = MonetClient(STORE)
    try:
        listing = c.tools_list()
        names = [t.get("name") for t in (listing or {}).get("tools", [])] if isinstance(listing, dict) else []
    except Exception as exc:
        names = []
        note("tools/list failed: %r" % (exc,))
    if names:
        check("s0_ratify_on_roster", "memory_ratify" in names, "roster=%d tools" % len(names))

    # ---------------- ARM A — the declaration entrance is disclosed ----------------
    a = c.call_json("memory_declare", {
        "species": "principle", "circle": CIRCLE,
        "content": "Prefer one measurement over three inferences before changing an agent loop (%s)" % TOKEN,
        "exitsEvidence": "Run the loop with and without the change; compare wall time and error rate (%s)" % TOKEN,
    })
    p1 = a.get("conceptId") if isinstance(a, dict) else None
    check("a1_declared", isinstance(a, dict) and a.get("action") == "created" and bool(p1),
          "action=%s" % (a.get("action") if isinstance(a, dict) else why(a)))
    if not sql("SELECT 1;"):
        print("STALE: could not read the isolated store %s for history assertions" % DB)
        return 5

    ov = c.call_json("memory_overview", {"circle": CIRCLE})
    if p1:
        check("a2_member", p1 in ids(ov), "skeleton=%d" % len(skeleton(ov)))
        check("a3_entrance_declaration", ent_of(ov, p1) == "declaration", "entrance=%r" % ent_of(ov, p1))
        e = entry(ov, p1) or {}
        check("a4_no_battery_disclosed", "battery" not in e,
              "keys=%s" % ",".join(sorted(e.keys())))
    counts = (ov or {}).get("counts") or {}
    check("a5_counts_skeleton", counts.get("skeleton") == len(skeleton(ov)),
          "counts.skeleton=%r len=%d" % (counts.get("skeleton"), len(skeleton(ov))))

    # ---------------- ARM B — latest verdict governs; history accumulates ----------------
    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": p1, "verdict": "reject"})
    check("b1_reject_recorded", isinstance(r, dict) and r.get("verdict") == "reject"
          and bool(r.get("ratificationId")), "ack=%s" % (str(r)[:90]))
    check("b2_edge_ids_empty", isinstance(r, dict) and r.get("edgeIds") == [],
          "edgeIds=%r" % (r.get("edgeIds") if isinstance(r, dict) else None))
    ov = c.call_json("memory_overview", {"circle": CIRCLE})
    check("b3_reject_ends_membership", p1 not in ids(ov), "still=%s" % (p1 in ids(ov)))

    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": p1, "verdict": "re-ratify"})
    check("b4_re_ratify_ok", isinstance(r, dict) and r.get("verdict") == "re-ratify",
          "ack=%s" % (str(r)[:90]))
    ov = c.call_json("memory_overview", {"circle": CIRCLE})
    check("b5_membership_returns", p1 in ids(ov))
    check("b6_entrance_never_inferred", ent_of(ov, p1) is None,
          "entrance=%r (must not inherit the prior row's 'declaration')" % ent_of(ov, p1))

    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": p1, "verdict": "approve",
                                     "entrance": "declaration"})
    check("b7_approve_declaration_ok", isinstance(r, dict) and r.get("verdict") == "approve")
    ov = c.call_json("memory_overview", {"circle": CIRCLE})
    check("b8_entrance_is_latest", ent_of(ov, p1) == "declaration", "entrance=%r" % ent_of(ov, p1))

    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": p1, "verdict": "retire"})
    check("b9_retire_ok", isinstance(r, dict) and r.get("verdict") == "retire")
    ov = c.call_json("memory_overview", {"circle": CIRCLE})
    check("b10_retire_ends_membership", p1 not in ids(ov))

    n, latest, _ = verdict_history(p1)
    check("b11_history_kept", n == 5 and latest == "retire",
          "rows=%r latest=%r (declaration-approve + reject + re-ratify + approve + retire)" % (n, latest))

    # ---------------- ARM C — the entrance/battery contract (monet-core#142) ----------------
    a = c.call_json("memory_declare", {
        "species": "principle", "circle": CIRCLE,
        "content": "Bind a rule to the stage where it is looked up, never to the agent that wrote it (%s)" % TOKEN,
    })
    p2 = a.get("conceptId") if isinstance(a, dict) else None
    ov = c.call_json("memory_overview", {"circle": CIRCLE})
    check("c1_p2_baseline_member", p2 in ids(ov) and ent_of(ov, p2) == "declaration")

    base = {"circle": CIRCLE, "candidateId": p2, "verdict": "approve"}
    full = [passed_gate("generates"), passed_gate("covers"), passed_gate("transfers"), passed_gate("exits")]

    r = c.call_json("memory_ratify", dict(base, entrance="extraction"))
    check("c2_extraction_needs_battery", refused(r, "battery"), why(r))
    check("c2b_refusal_names_all_gates",
          all(g in wtext(r).lower() for g in ("generates", "covers", "transfers", "exits")), why(r))

    r = c.call_json("memory_ratify", dict(base, entrance="extraction", battery=full[:3]))
    check("c3_incomplete_battery_refused", refused(r, "exits"), why(r))

    r = c.call_json("memory_ratify", dict(base, entrance="extraction",
                                         battery=[passed_gate("generates"), passed_gate("covers"),
                                                  passed_gate("transfers"), failed_gate("exits")]))
    check("c4_failed_gate_inadmissible", refused(r, "failed exits") or refused(r, "exits"), why(r))

    r = c.call_json("memory_ratify", dict(base, entrance="declaration", battery=full))
    check("c5_declaration_forbids_battery", refused(r, "declaration"), why(r))

    r = c.call_json("memory_ratify", dict(base, battery=full))
    check("c6_battery_needs_entrance", refused(r, "entrance"), why(r))

    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": p2, "verdict": "retire",
                                     "entrance": "declaration"})
    check("c7_retire_carries_neither", refused(r, "retire"), why(r))

    r = c.call_json("memory_ratify", dict(base, entrance="extraction",
                                         battery=[passed_gate("generates"), passed_gate("covers"),
                                                  passed_gate("transfers"),
                                                  {"gate": "exits", "passed": "yes"}]))
    check("c8_non_boolean_refused", "_rawText" in (r if isinstance(r, dict) else {}), why(r))

    r = c.call_json("memory_ratify", dict(base, entrance="extraction",
                                         battery=[passed_gate("generates"), passed_gate("generates"),
                                                  passed_gate("covers"), passed_gate("transfers")]))
    check("c9_duplicate_gate_refused", "_rawText" in (r if isinstance(r, dict) else {}), why(r))

    r = c.call_json("memory_ratify", dict(base, entrance="extraction",
                                         battery=[passed_gate("generates"), passed_gate("covers"),
                                                  passed_gate("transfers"), passed_gate("vibes")]))
    check("c10_unknown_gate_refused", "_rawText" in (r if isinstance(r, dict) else {}), why(r))

    # The refusal storm must have written nothing: same membership, same entrance, one history row.
    ov = c.call_json("memory_overview", {"circle": CIRCLE})
    n, _, _ = verdict_history(p2)
    check("c11_refusals_wrote_nothing", p2 in ids(ov) and ent_of(ov, p2) == "declaration" and n == 1,
          "entrance=%r rows=%r (9 refused verdicts must not move either)" % (ent_of(ov, p2), n))

    # Rejections keep their failed answers (a rejected battery is still a record).
    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": p2, "verdict": "reject",
                                     "entrance": "extraction",
                                     "battery": [passed_gate("generates"), passed_gate("covers"),
                                                 passed_gate("transfers"), failed_gate("exits")]})
    check("c12_reject_keeps_failed_battery", isinstance(r, dict) and r.get("verdict") == "reject",
          "ack=%s" % (str(r)[:80] if isinstance(r, dict) else why(r)))
    ov = c.call_json("memory_overview", {"circle": CIRCLE})
    check("c13_reject_kept_it_out", p2 not in ids(ov))

    long_ref = ("https://github.com/team-monet/monet/blob/main/docs/evidence/%s" % TOKEN) + ("x" * 240)
    r = c.call_json("memory_ratify", dict(base, entrance="extraction",
                                         battery=[passed_gate("generates", long_ref),
                                                  passed_gate("covers"), passed_gate("transfers"),
                                                  passed_gate("exits")],
                                         packet={"shown": ["a", "b"], "rendered": "human saw this"},
                                         ratifiedBy="e2e-scenario-13"))
    check("c14_extraction_entry_accepted", isinstance(r, dict) and r.get("verdict") == "approve"
          and r.get("edgeIds") == [], "ack=%s" % (str(r)[:90] if isinstance(r, dict) else why(r)))
    ov = c.call_json("memory_overview", {"circle": CIRCLE})
    check("c15_entrance_extraction", ent_of(ov, p2) == "extraction", "entrance=%r" % ent_of(ov, p2))
    bat = (entry(ov, p2) or {}).get("battery")
    gates = [g.get("gate") for g in bat] if isinstance(bat, list) else None
    check("c16_battery_echoed", gates == ["generates", "covers", "transfers", "exits"],
          "gates=%r" % (gates,))
    refs = [g.get("evidenceRef", "") for g in bat] if isinstance(bat, list) else []
    clipped = refs[0] if refs else ""
    check("c17_long_evidence_ref_clipped", 0 < len(clipped) <= 150 and clipped.startswith(long_ref[:100]),
          "len=%d tail=%r (curation projection clips at CURATION_EVIDENCE_REF_MAX_CHARS=120)"
          % (len(clipped), clipped[-24:]))

    # ---------------- ARM D — memberRuleIds: principle-only rule derivation ----------------
    rr = c.call_json("memory_declare", {
        "species": "rule", "circle": CIRCLE, "stage": "release-review",
        "scope": "domain",
        "content": "Never publish a Monet release without a same-day doctor readback (%s)" % TOKEN,
    })
    rule_id = rr.get("conceptId") if isinstance(rr, dict) else None
    check("d1_rule_declared", bool(rule_id) and rr.get("species") == "rule",
          "ack=%s" % (str(rr)[:90] if isinstance(rr, dict) else why(rr)))

    pr = c.call_json("memory_declare", {
        "species": "preference", "circle": CIRCLE,
        "content": "Report Monet findings as measured numbers before narrative (%s)" % TOKEN,
    })
    pref_id = pr.get("conceptId") if isinstance(pr, dict) else None
    check("d2_preference_declared", bool(pref_id) and pr.get("species") == "preference",
          "ack=%s" % (str(pr)[:90] if isinstance(pr, dict) else why(pr)))

    f = c.call_json("memory_store", {
        "circle": CIRCLE, "kind": "fact",
        "content": "The %s run stored a plain fact to stand in as a non-rule candidate." % TOKEN,
    })
    fact_id = f.get("conceptId") if isinstance(f, dict) else None
    check("d3_fact_stored", bool(fact_id), "ack=%s" % (str(f)[:70] if isinstance(f, dict) else why(f)))

    ap = c.call_json("memory_declare", {
        "species": "principle", "circle": CIRCLE,
        "content": "Link a principle to the rules it generated so the derivation is auditable (%s)" % TOKEN,
    })
    p3 = ap.get("conceptId") if isinstance(ap, dict) else None
    check("d4_p3_declared", bool(p3))

    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": p3, "verdict": "approve",
                                     "memberRuleIds": [fact_id]})
    check("d5_non_rule_member_refused", refused(r, "rule"), why(r))

    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": pref_id, "verdict": "approve",
                                     "memberRuleIds": [rule_id]})
    check("d6_preference_member_refused", refused(r, "preference"), why(r))

    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": p3, "verdict": "approve",
                                     "memberRuleIds": [rule_id], "entrance": "declaration"})
    # `edgeIds` are memory_edge ROW ids (the derivation edges), not the rule's concept id.
    linked = r.get("edgeIds") if isinstance(r, dict) else None
    check("d7_member_linked", isinstance(linked, list) and len(linked) == 1,
          "edgeIds=%r (one derivation edge per named rule)" % (linked,))
    if isinstance(linked, list) and linked:
        # The edgeIds live in `lifecycle_edges` (NOT memory_edge — that is the observation graph):
        #   family IN (derivation|provenance|supersession), src_concept_id -> dst_concept_id|dst_span.
        e = sql("SELECT family || '|' || src_concept_id || '|' || COALESCE(dst_concept_id,'') "
                "FROM lifecycle_edges WHERE id='%s';" % linked[0])
        check("d7b_edge_is_derivation", e == "derivation|%s|%s" % (p3, rule_id),
              "edge=%r (principle -> rule derivation)" % (e,))
        born = sql("SELECT born_of || '|' || COALESCE(event_ref,'') || '|' || circle "
                   "FROM lifecycle_edges WHERE id='%s';" % linked[0])
        check("d7c_edge_is_ratification_born", born.split("|")[0] == "ratification" and born.endswith("|" + CIRCLE),
              "born_of|event_ref|circle=%r (a ratification-born edge names its ratification)" % (born,))
        if isinstance(r, dict) and r.get("ratificationId"):
            check("d7d_event_ref_is_ratification_id", born.split("|")[1] == r["ratificationId"],
                  "event_ref=%r ack.ratificationId=%r" % (born.split("|")[1], r["ratificationId"]))

    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": p3, "verdict": "re-ratify",
                                     "memberRuleIds": [rule_id, rule_id], "entrance": "declaration"})
    linked2 = r.get("edgeIds") if isinstance(r, dict) else None
    check("d8_member_ids_deduped", isinstance(linked2, list) and len(linked2) == 1,
          "edgeIds=%r (the same rule named twice must mint ONE edge, not two)" % (linked2,))
    # Derivation/provenance edges are DELIBERATELY non-unique (schema comment in lifecycle-edges.ts:
    # "a principle derives many rules, and a rule corrected twice carries two evidence spans"), so
    # de-duplication is per-CALL, not across verdicts: each verdict mints its own audit edge.
    n_edges = sql("SELECT COUNT(*) FROM lifecycle_edges WHERE family='derivation' "
                  "AND src_concept_id='%s' AND dst_concept_id='%s';" % (p3, rule_id))
    check("d8b_derivation_edges_per_verdict", n_edges == "2",
          "approve then re-ratify on the same rule -> %r derivation edge(s) (documented non-unique: "
          "one audit edge per verdict)" % (n_edges,))

    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": p3, "verdict": "reject",
                                     "memberRuleIds": ["no-such-rule-%s" % TOKEN]})
    check("d9_reject_ignores_member_ids", isinstance(r, dict) and r.get("verdict") == "reject"
          and r.get("edgeIds") == [],
          "ignored-by-contract: a bogus id on a reject must NOT be validated (%s)"
          % (str(r)[:70] if isinstance(r, dict) else why(r)))

    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": pref_id, "verdict": "approve",
                                     "entrance": "declaration"})
    ov = c.call_json("memory_overview", {"circle": CIRCLE})
    check("d10_preference_ratified", pref_id in ids(ov) and (entry(ov, pref_id) or {}).get("species") == "preference",
          "ack=%s" % (str(r)[:60] if isinstance(r, dict) else why(r)))

    # ---------------- ARM E — candidate guards ----------------
    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": fact_id, "verdict": "approve"})
    check("e1_non_candidate_refused", refused(r, "candidate"), why(r))

    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": "no-such-concept-%s" % TOKEN,
                                     "verdict": "approve"})
    check("e2_missing_candidate_refused", refused(r, "exist") or refused(r, "not found"), why(r))

    r = c.call_json("memory_ratify", {"circle": OTHER, "candidateId": p3, "verdict": "approve"})
    check("e3_wrong_circle_refused", "_rawText" in (r if isinstance(r, dict) else {}), why(r))
    check("e4_wrong_circle_names_both", CIRCLE in wtext(r) and OTHER in wtext(r), why(r))

    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": p3, "verdict": "approve-all"})
    check("e5_invalid_verdict_refused", "_rawText" in (r if isinstance(r, dict) else {}),
          "wire-layer refusal: %s" % why(r))

    # retired candidate: an entry verdict cannot resurrect it
    ar = c.call_json("memory_declare", {
        "species": "principle", "circle": CIRCLE,
        "content": "Retire a principle before retiring its concept, never the other way round (%s)" % TOKEN,
    })
    p5 = ar.get("conceptId") if isinstance(ar, dict) else None
    c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": p5, "verdict": "retire"})
    dismissals = dismiss_dup_pairs(c, CIRCLE, p5)
    ok_dis = [d for d in dismissals if isinstance(d, dict) and d.get("action") == "pair-flags-dismissed"]
    check("e6a0_pair_flag_dismissal_shape", bool(ok_dis) and all((d.get("rowsUpdated") or 0) >= 1 for d in ok_dis),
          "ack(s)=%s — pair shape is conceptAId+conceptBId ONLY (passing `decision` is refused by name)"
          % (str(ok_dis)[:120],))
    rt = c.call_json("memory_retire", {"circle": CIRCLE, "id": p5})
    check("e6a_principle_retirable_after_ratify_retire",
          isinstance(rt, dict) and rt.get("action") == "retired", "ack=%s" % (str(rt)[:90] if isinstance(rt, dict) else why(rt)))

    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": p5, "verdict": "approve"})
    check("e6b_retired_candidate_refused", refused(r, "resurrect") or refused(r, "retire"), why(r))

    rs = c.call_json("memory_restore", {"circle": CIRCLE, "id": p5})
    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": p5, "verdict": "approve",
                                     "entrance": "declaration"})
    ov = c.call_json("memory_overview", {"circle": CIRCLE})
    check("e7_restore_then_ratify_ok", isinstance(r, dict) and r.get("verdict") == "approve" and p5 in ids(ov),
          "restore=%s ratify=%s" % (str(rs)[:40] if isinstance(rs, dict) else why(rs),
                                    str(r)[:40] if isinstance(r, dict) else why(r)))

    # disputed candidate: mediate first, then membership returns
    ad = c.call_json("memory_declare", {
        "species": "principle", "circle": CIRCLE,
        "content": "Resolve an open contradiction before ratifying the principle it disputes (%s)" % TOKEN,
    })
    p6 = ad.get("conceptId") if isinstance(ad, dict) else None
    fl = c.call_json("memory_flag_contradiction", {
        "circle": CIRCLE, "conceptId": p6,
        "detail": "The %s run observed the opposite ruling in a sibling circle." % TOKEN,
    })
    check("e8a_contradiction_opened", isinstance(fl, dict) and bool(fl.get("contradictionId")),
          "ack=%s" % (str(fl)[:90] if isinstance(fl, dict) else why(fl)))
    fetched = c.call_json("memory_fetch", {"circle": CIRCLE, "id": p6})
    check("e8b_status_disputed", (fetched or {}).get("status") == "disputed",
          "status=%r" % ((fetched or {}).get("status"),))

    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": p6, "verdict": "approve"})
    check("e9_disputed_candidate_refused", refused(r, "contradiction") or refused(r, "mediate"), why(r))

    cid = fl.get("contradictionId") if isinstance(fl, dict) else None
    c.call_json("memory_resolve", {"circle": CIRCLE, "contradictionId": cid, "decision": "dismiss"})
    r = c.call_json("memory_ratify", {"circle": CIRCLE, "candidateId": p6, "verdict": "approve",
                                     "entrance": "declaration"})
    ov = c.call_json("memory_overview", {"circle": CIRCLE})
    check("e10_resolve_then_membership_returns",
          isinstance(r, dict) and r.get("verdict") == "approve" and p6 in ids(ov),
          "ack=%s" % (str(r)[:80] if isinstance(r, dict) else why(r)))

    # ---------------- ARM F — the two projections (on-demand vs always-on) ----------------
    ctx = c.call_json("agent_context", {"circle": CIRCLE})
    ctx_sk = (ctx or {}).get("skeleton")
    check("f1_agent_context_ships_skeleton", isinstance(ctx_sk, list) and len(ctx_sk) > 0,
          "entries=%s" % (len(ctx_sk) if isinstance(ctx_sk, list) else None))
    if isinstance(ctx_sk, list):
        leaked = [e for e in ctx_sk if "entrance" in e or "battery" in e]
        check("f2_always_on_has_no_entrance", leaked == [],
              "always-on minimization law: agent_context must NOT carry entrance/battery (leaks=%d)"
              % len(leaked))
        check("f3_always_on_ids_match_overview",
              sorted([e.get("conceptId") for e in ctx_sk]) == sorted(ids(ov)),
              "always-on=%d on-demand=%d" % (len(ctx_sk), len(skeleton(ov))))
    c.close()

    # ---------------- ARM G — fresh-process readback (a ruling that persisted) ----------------
    c2 = MonetClient(STORE)
    ov2 = c2.call_json("memory_overview", {"circle": CIRCLE})
    check("g1_retire_is_durable", p1 not in ids(ov2), "p1=%s" % (p1 in ids(ov2)))
    check("g2_extraction_entry_durable", ent_of(ov2, p2) == "extraction",
          "entrance=%r" % ent_of(ov2, p2))
    bat2 = (entry(ov2, p2) or {}).get("battery")
    check("g3_battery_durable", isinstance(bat2, list) and len(bat2) == 4,
          "gates=%s" % (len(bat2) if isinstance(bat2, list) else None))
    # p3 is deliberately absent: d9's reject ended its membership and the latest verdict governs,
    # so a later approve/re-ratify is what would bring it back — not a fresh open.
    durable = [pref_id, p5, p6]
    check("g4_later_members_durable", all(x in ids(ov2) for x in durable),
          "missing=%s" % [x for x in durable if x not in ids(ov2)])
    check("g4b_reject_still_governs", p3 not in ids(ov2),
          "p3 was rejected last; a reopen must not resurrect it")
    counts2 = (ov2 or {}).get("counts") or {}
    check("g5_counts_match_after_reopen", counts2.get("skeleton") == len(skeleton(ov2)),
          "counts=%r len=%d" % (counts2.get("skeleton"), len(skeleton(ov2))))
    c2.close()

    print("\n== %d passed, %d failed, %d notes ==" % (len(PASS), len(FAIL), len(NOTES)))
    if FAIL:
        print("FAILED: %s" % ", ".join(FAIL))
        return 1
    # ONE line: run_all.py greps the RESULT: line, so a wrapped RESULT loses the rest of the verdict.
    print("RESULT: ratify journey — %d checks green: every documented verdict, entrance/battery rule, "
          "candidate guard, derivation edge and projection held on the live path "
          "(declare -> ratify -> overview/agent_context -> fresh open)." % (len(PASS),))
    return 0


if __name__ == "__main__":
    rc = 0
    try:
        rc = main()
    finally:
        if not KEEP:
            shutil.rmtree(STORE, ignore_errors=True)
        else:
            print("kept store: %s" % STORE)
    sys.exit(rc)
