#!/usr/bin/env python3
"""Scenario 14 — evidence-level SPLIT / merge-undo (memory_detach).

Why this scenario. The released 1.11.0 roster advertises 21 tools and `memory_detach`
is the last of them with ZERO end-to-end evidence: its only appearance anywhere in the
suite is the roster string in test01. Every other tool has at least one driven journey,
and `memory_detach` is the only surface that can UNDO a wrong merge — the exact cleanup
the server-ops playbook prescribes after a multilingual repair overmerges concepts
(`monet-server-operations/references/attach-retest-and-overmerge-split.md`). A tool
whose whole purpose is repairing bad attachment state cannot itself be unverified.

What the description promises, and what this test drives:

  * "By default they form a new concept" -> destAction="created", source recomputed.
  * "destConceptId attaches them to an existing same-circle concept" -> destAction="attached".
  * "Moving all observations into a destination deletes the source, consolidating a
     duplicate" -> sourceDeleted=true, source gone, its slug+id carried as destination aliases.
  * "The source is recomputed and marked for synthesis" -> observationCount drops, body is
     rebuilt WITHOUT the moved evidence, needsSynthesis re-arms.
  * "Without a destination, at least one observation must remain" -> last-observation refusal.
  * Scope + shape guards: wrong-circle source, wrong-circle destination, foreign observation id,
     nonexistent observation id, self-destination, workstream source, retired source, empty list.

Every effect is read back on a public surface (`memory_fetch` cards, `memory_search` cards),
and the whole journey is re-read from a FRESH server process so a split that only lived in
process memory cannot pass. Alias carry is DB-read because no wire surface exposes `aliases`
(the source id deliberately does NOT resolve through `memory_fetch`: aliases are for asserted
slug references, not id lookup — asserted here so the distinction is on record).

Isolation: private temp store (`-d <tmp>`), never the prod store or the shared test store; no
HOME override, so the real embedder cache is reused read-only (skill: HOME-redirect trap).
Re-run safe: timestamped circle + content token.

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
STORE = tempfile.mkdtemp(prefix="r128-detach-")
DB = os.path.join(STORE, "monet.db")
TS = int(time.time())
CIRCLE = "e2e-detach-%d" % TS
OTHER = "e2e-detach-other-%d" % TS
TOKEN = "DTCH%d" % TS

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


def why(resp):
    return wtext(resp).replace("\n", " ")[:180]


def call_capture(c, tool, args):
    """Refusals reach the client two ways: a core `err()` body (_rawText) or a JSON-RPC /
    schema rejection (raised by the harness). Normalize both to _rawText so one assertion
    style covers the whole refusal surface."""
    try:
        return c.call_json(tool, args)
    except RuntimeError as exc:
        return {"_rawText": str(exc)}


def sql(query):
    """Diagnostic-only reads (WAL: safe alongside the running server)."""
    try:
        out = subprocess.run(["sqlite3", DB, query], capture_output=True, text=True, timeout=20)
        return out.stdout.strip()
    except Exception as exc:  # pragma: no cover
        NOTES.append("sql failed: %r" % (exc,))
        return ""


def card(tool_resp):
    return tool_resp if isinstance(tool_resp, dict) else {}


def obs_of(c, cid, circle=CIRCLE):
    """Newest-first evidence page for a concept, via the public fetch surface."""
    r = c.call_json("memory_fetch", {"id": cid, "circle": circle, "observations": True})
    if not isinstance(r, dict) or "observations" not in r:
        return None, r
    return (r.get("observations") or []), r


def dismiss_dup_pairs(c, circle, cid):
    """Find-21 recovery (same helper as test21/test66): memory_retire refuses a concept
    carrying an undismissed PAIR_FLAG edge; dismiss any open pair first."""
    rows = sql(
        "SELECT src_id, dst_id FROM memory_edge WHERE type IN ('possible_duplicate_of','extraction_candidate') "
        "AND dismissed_at IS NULL AND (src_id='%s' OR dst_id='%s');" % (cid, cid)
    )
    partners = []
    for line in rows.split("\n"):
        if "|" not in line:
            continue
        src, dst = line.split("|")[:2]
        partner = dst if src == cid else src
        if partner not in partners:
            partners.append(partner)
    for partner in partners:
        res = c.call_json("memory_resolve", {"circle": circle, "conceptAId": cid, "conceptBId": partner})
        note("pair dismissal %s <-> %s -> %s" % (cid[:8], partner[:8], str(res)[:100]))


def main():
    print("== scenario 14: detach journey (store %s, circle %s) ==" % (STORE, CIRCLE))
    c = MonetClient(STORE)
    try:
        listing = c.tools_list()
        names = [t.get("name") for t in (listing or {}).get("tools", [])] if isinstance(listing, dict) else []
    except Exception as exc:
        names = []
        note("tools/list failed: %r" % (exc,))
    if names:
        check("a0_detach_on_roster", "memory_detach" in names, "roster=%d tools" % len(names))

    # ---------------- ARM A — a merged keeper with four observations ----------------
    # One near-identical template with a noun swapped: verified to dedup-merge into ONE
    # concept (test10's growth pattern), which is exactly the "wrong merge" state this
    # tool exists to undo.
    template = "Detach probe %s confirmed that a merged keeper gives up its evidence one observation at a time."
    stay = []
    src = None
    for noun in ("alpha", "beta", "gamma", "delta"):
        r = c.call_json("memory_store", {"circle": CIRCLE, "kind": "decision",
                                         "content": template % noun})
        if not isinstance(r, dict):
            note("store failed: %s" % why(r))
            break
        if src is None:
            src = r.get("conceptId")
        stay.append((r.get("action"), r.get("conceptId")))
    check("a1_first_store_created", stay and stay[0][0] == "created" and bool(src),
          "action=%s" % (stay[0][0] if stay else None))
    check("a2_three_more_attached_same_concept",
          len(stay) == 4 and all(a == "attached" and cid == src for a, cid in stay[1:]),
          "acks=%s" % [(a, (cid or "")[:8]) for a, cid in stay])
    if not src:
        print("STALE: no source concept could be created in %s" % STORE)
        return 5

    obs, src_card = obs_of(c, src)
    if obs is None:
        print("STALE: memory_fetch did not return an evidence page (%s)" % why(src_card))
        return 5
    n0 = src_card.get("observationCount")
    check("a3_four_observations_on_source", n0 == 4 and len(obs) == 4,
          "count=%s page=%d" % (n0, len(obs)))
    check("a4_source_kind_is_decision", src_card.get("kind") == "decision",
          "kind=%r" % src_card.get("kind"))
    if n0 != 4:
        print("STALE: dedup did not merge the template stores into one 4-observation concept "
              "(count=%s) — the split arms need the merged state" % n0)
        return 5
    if not sql("SELECT 1;"):
        print("STALE: could not read the isolated store %s for alias assertions" % DB)
        return 5

    # ---------------- ARM B — default split forms a NEW concept ----------------
    moving = obs[0]                      # newest-first page: obs[0] is the newest
    r = c.call_json("memory_detach", {"circle": CIRCLE, "conceptId": src,
                                      "observationIds": [moving["id"]]})
    d1 = r.get("destConceptId") if isinstance(r, dict) else None
    check("b1_dest_action_created", isinstance(r, dict) and r.get("destAction") == "created",
          "destAction=%s" % (r.get("destAction") if isinstance(r, dict) else why(r)))
    check("b2_observations_moved_one", isinstance(r, dict) and r.get("observationsMoved") == 1,
          "moved=%s" % (r.get("observationsMoved") if isinstance(r, dict) else None))
    check("b3_source_not_deleted", isinstance(r, dict) and r.get("sourceDeleted") is False,
          "sourceDeleted=%s" % (r.get("sourceDeleted") if isinstance(r, dict) else None))
    check("b4_dest_is_a_different_concept", bool(d1) and d1 != src,
          "dest=%s src=%s" % ((d1 or "")[:8], src[:8]))
    check("b5_ack_message_created", isinstance(r, dict) and "created new concept" in str(r.get("message", "")).lower(),
          "message=%s" % str(r.get("message", ""))[:90])

    s_card = card(c.call_json("memory_fetch", {"id": src, "circle": CIRCLE}))
    check("b6_source_recomputed_to_three", s_card.get("observationCount") == 3,
          "count=%s" % s_card.get("observationCount"))
    check("b7_source_body_lost_moved_evidence", moving["content"] not in str(s_card.get("body", "")),
          "moved_text_still_present=%s" % (moving["content"] in str(s_card.get("body", ""))))
    check("b8_source_rearmed_synthesis", s_card.get("needsSynthesis") is True,
          "needsSynthesis=%s" % s_card.get("needsSynthesis"))

    d1_card = card(c.call_json("memory_fetch", {"id": d1, "circle": CIRCLE}))
    check("b9_dest_holds_moved_evidence", d1_card.get("observationCount") == 1
          and moving["content"] in str(d1_card.get("body", "")),
          "count=%s" % d1_card.get("observationCount"))
    check("b10_dest_in_same_circle", d1_card.get("circle") == CIRCLE, "circle=%s" % d1_card.get("circle"))
    check("b11_dest_carries_source_kind",
          sql("SELECT kind FROM concepts WHERE id='%s';" % d1) == "decision",
          "db_kind=%s" % sql("SELECT kind FROM concepts WHERE id='%s';" % d1))
    check("b12_dest_flagged_for_synthesis", d1_card.get("needsSynthesis") is True,
          "needsSynthesis=%s" % d1_card.get("needsSynthesis"))

    # ---------------- ARM C — attach the detached evidence to an EXISTING concept ----------------
    other_topic = ("Quarterly ledger %s reconciliation for the harbour inventory batch runs on the "
                   "first business day." % TOKEN)
    ro = c.call_json("memory_store", {"circle": CIRCLE, "content": other_topic})
    d2 = ro.get("conceptId") if isinstance(ro, dict) else None
    check("c1_second_concept_created", isinstance(ro, dict) and ro.get("action") == "created" and bool(d2),
          "action=%s" % (ro.get("action") if isinstance(ro, dict) else why(ro)))
    check("c2_second_concept_is_separate", bool(d2) and d2 not in (src, d1),
          "d2=%s" % (d2 or "")[:8])

    moving2 = obs[1]
    r = c.call_json("memory_detach", {"circle": CIRCLE, "conceptId": src,
                                      "observationIds": [moving2["id"]], "destConceptId": d2})
    check("c3_dest_action_attached", isinstance(r, dict) and r.get("destAction") == "attached",
          "destAction=%s" % (r.get("destAction") if isinstance(r, dict) else why(r)))
    check("c4_attached_to_named_dest", isinstance(r, dict) and r.get("destConceptId") == d2
          and r.get("sourceDeleted") is False,
          "dest=%s sourceDeleted=%s" % ((r.get("destConceptId") or "")[:8] if isinstance(r, dict) else None,
                                        r.get("sourceDeleted") if isinstance(r, dict) else None))
    d2_card = card(c.call_json("memory_fetch", {"id": d2, "circle": CIRCLE}))
    check("c5_dest_grew_and_holds_evidence", d2_card.get("observationCount") == 2
          and moving2["content"] in str(d2_card.get("body", "")),
          "count=%s" % d2_card.get("observationCount"))
    check("c6_source_shrank_again",
          card(c.call_json("memory_fetch", {"id": src, "circle": CIRCLE})).get("observationCount") == 2,
          "count=%s" % card(c.call_json("memory_fetch", {"id": src, "circle": CIRCLE})).get("observationCount"))
    check("c7_split_concept_untouched",
          card(c.call_json("memory_fetch", {"id": d1, "circle": CIRCLE})).get("observationCount") == 1,
          "d1_count=%s" % card(c.call_json("memory_fetch", {"id": d1, "circle": CIRCLE})).get("observationCount"))

    # ---------------- ARM D — consolidation deletes the source ----------------
    s_slug = sql("SELECT slug FROM concepts WHERE id='%s';" % src)
    remaining = [o["id"] for o in obs[2:]]
    check("d0_two_observations_left", len(remaining) == 2, "remaining=%d" % len(remaining))
    r = c.call_json("memory_detach", {"circle": CIRCLE, "conceptId": src,
                                      "observationIds": remaining, "destConceptId": d1})
    check("d1_source_deleted", isinstance(r, dict) and r.get("sourceDeleted") is True,
          "sourceDeleted=%s" % (r.get("sourceDeleted") if isinstance(r, dict) else why(r)))
    check("d2_all_remaining_moved", isinstance(r, dict) and r.get("observationsMoved") == len(remaining),
          "moved=%s" % (r.get("observationsMoved") if isinstance(r, dict) else None))
    check("d3_consolidation_message", isinstance(r, dict)
          and "consolidated into" in str(r.get("message", "")).lower(),
          "message=%s" % str(r.get("message", ""))[:90])
    gone = call_capture(c, "memory_fetch", {"id": src, "circle": CIRCLE})
    check("d4_source_not_found_after_consolidation",
          refused(gone, "concept not found"), why(gone))
    check("d5_source_row_gone", sql("SELECT COUNT(*) FROM concepts WHERE id='%s';" % src) == "0",
          "rows=%s" % sql("SELECT COUNT(*) FROM concepts WHERE id='%s';" % src))
    d1_after = card(c.call_json("memory_fetch", {"id": d1, "circle": CIRCLE}))
    check("d6_keeper_holds_all_evidence", d1_after.get("observationCount") == 3,
          "count=%s" % d1_after.get("observationCount"))
    aliases = sql("SELECT aliases FROM concepts WHERE id='%s';" % d1)
    check("d7_source_slug_and_id_carried_as_aliases",
          bool(aliases) and src in aliases and bool(s_slug) and s_slug in aliases,
          "aliases=%s" % (aliases[:120] if aliases else "<none>"))
    found = c.call_json("memory_search", {"query": template % "alpha", "circle": CIRCLE, "limit": 5})
    hits = [h.get("id") for h in (found.get("results") or [])] if isinstance(found, dict) else []
    check("d8_moved_evidence_retrievable_on_keeper", d1 in hits,
          "hits=%s" % [h[:8] for h in hits])
    if d1 in hits and d2 in hits:
        check("d9_keeper_outranks_the_other_holder", hits.index(d1) < hits.index(d2),
              "rank d1=%d d2=%d" % (hits.index(d1), hits.index(d2)))
    # Alias boundary: the carry is real (d7) but it is NOT id resolution on tool params — every
    # conceptId entry point resolves through `circleOf(id)` (id-only SQL) / `resolveCircle`, so a
    # caller holding only the removed concept's slug or uuid gets "concept not found", never the
    # survivor. Aliases serve ASSERTED `#slug` references internally (`resolveRef` alias fallback),
    # which no MCP param exposes. Asserted here so the carry's scope is on record, not inferred.
    by_slug = call_capture(c, "memory_fetch", {"id": s_slug, "circle": CIRCLE})
    check("d10_removed_slug_is_not_a_fetchable_id",
          refused(by_slug, "concept not found"), "slug=%r -> %s" % (s_slug, why(by_slug)))
    by_uuid = call_capture(c, "memory_fetch", {"id": src, "circle": CIRCLE})
    check("d11_removed_uuid_is_not_a_fetchable_id",
          refused(by_uuid, "concept not found"), why(by_uuid))

    # ---------------- ARM E — refusals (and no side effects from them) ----------------
    solo = c.call_json("memory_store", {"circle": CIRCLE,
                                        "content": "Solo guard %s records that a single observation cannot be split away." % TOKEN})
    z = solo.get("conceptId") if isinstance(solo, dict) else None
    z_obs, _ = obs_of(c, z) if z else (None, None)
    check("e0_solo_concept_ready", bool(z) and bool(z_obs) and len(z_obs) == 1,
          "obs=%s" % (len(z_obs) if z_obs else None))

    zid = z_obs[0]["id"] if z_obs else "missing"
    r = call_capture(c, "memory_detach", {"circle": CIRCLE, "conceptId": z, "observationIds": [zid]})
    check("e1_last_observation_refused", refused(r, "cannot detach the last observation"), why(r))

    d2_obs, _ = obs_of(c, d2)
    d2_first = d2_obs[0]["id"] if d2_obs else "missing"
    r = call_capture(c, "memory_detach", {"circle": CIRCLE, "conceptId": d2,
                                          "observationIds": [d2_first], "destConceptId": d2})
    check("e2_self_destination_refused", refused(r, "must differ from the source"), why(r))

    r = call_capture(c, "memory_detach", {"circle": CIRCLE, "conceptId": d2, "observationIds": [zid]})
    check("e3_foreign_observation_refused", refused(r, "does not belong to concept"), why(r))

    r = call_capture(c, "memory_detach", {"circle": OTHER, "conceptId": d2, "observationIds": [d2_first]})
    check("e4_wrong_circle_source_refused", refused(r, "concept not found"), why(r))

    outside = c.call_json("memory_store", {"circle": OTHER,
                                           "content": "Outside circle anchor %s for the destination scope guard." % TOKEN})
    out_id = outside.get("conceptId") if isinstance(outside, dict) else None
    r = call_capture(c, "memory_detach", {"circle": CIRCLE, "conceptId": d2,
                                          "observationIds": [d2_first], "destConceptId": out_id})
    check("e5_wrong_circle_dest_refused", refused(r, "destconceptid concept not found"), why(r))

    r = call_capture(c, "memory_detach", {"circle": CIRCLE, "conceptId": d2, "observationIds": []})
    check("e6_empty_observation_list_refused", isinstance(r, dict) and "_rawText" in r and len(wtext(r)) > 5, why(r))

    r = call_capture(c, "memory_detach", {"circle": CIRCLE, "conceptId": d2,
                                          "observationIds": ["obs-does-not-exist-%s" % TOKEN]})
    check("e7_unknown_observation_refused", refused(r, "does not belong to concept"), why(r))

    cp = c.call_json("memory_checkpoint", {"circle": CIRCLE,
                                           "workstream": {"title": "w14-%s" % TOKEN, "status": "active",
                                                          "open": [{"kind": "step", "text": "probe detach guard %s" % TOKEN}]}})
    ws = ((cp or {}).get("workstream") or {}).get("id")
    check("e8_workstream_minted", bool(ws), "ack=%s" % str(cp)[:90])
    if ws:
        # The kind guard runs BEFORE observation validation: a bogus id still proves the refusal.
        r = call_capture(c, "memory_detach", {"circle": CIRCLE, "conceptId": ws,
                                              "observationIds": ["obs-bogus-%s" % TOKEN]})
        check("e9_workstream_source_refused", refused(r, "cannot detach from a workstream concept"), why(r))

    dismiss_dup_pairs(c, CIRCLE, z)
    ret = c.call_json("memory_retire", {"circle": CIRCLE, "id": z})
    check("e10_retire_for_guard", isinstance(ret, dict) and not ("_rawText" in ret),
          "ack=%s" % str(ret)[:90])
    r = call_capture(c, "memory_detach", {"circle": CIRCLE, "conceptId": z, "observationIds": [zid]})
    check("e11_retired_source_refused", refused(r, "retired"), why(r))

    d2_now = card(c.call_json("memory_fetch", {"id": d2, "circle": CIRCLE}))
    d2_rows = sql("SELECT COUNT(*) FROM observations WHERE concept_id='%s';" % d2)
    check("e12_refusals_left_dest_intact", d2_now.get("observationCount") == 2 and d2_rows == "2",
          "card=%s db=%s" % (d2_now.get("observationCount"), d2_rows))
    check("e13_source_untouched_by_refusals",
          card(c.call_json("memory_fetch", {"id": d1, "circle": CIRCLE})).get("observationCount") == 3,
          "d1_count=%s" % card(c.call_json("memory_fetch", {"id": d1, "circle": CIRCLE})).get("observationCount"))
    c.close()

    # ---------------- ARM F — fresh-process readback ----------------
    c2 = MonetClient(STORE)
    f1 = card(c2.call_json("memory_fetch", {"id": d1, "circle": CIRCLE}))
    check("f1_split_and_consolidation_durable", f1.get("observationCount") == 3
          and (template % "alpha") in "".join(o.get("content", "") for o in
                                             ((c2.call_json("memory_fetch", {"id": d1, "circle": CIRCLE, "observations": True})
                                               .get("observations")) or [])),
          "count=%s" % f1.get("observationCount"))
    f2 = call_capture(c2, "memory_fetch", {"id": src, "circle": CIRCLE})
    check("f2_deleted_source_stays_deleted", refused(f2, "concept not found"), why(f2))
    check("f3_other_holder_durable",
          card(c2.call_json("memory_fetch", {"id": d2, "circle": CIRCLE})).get("observationCount") == 2,
          "count=%s" % card(c2.call_json("memory_fetch", {"id": d2, "circle": CIRCLE})).get("observationCount"))
    c2.close()

    print("\n== %d passed, %d failed, %d notes ==" % (len(PASS), len(FAIL), len(NOTES)))
    if FAIL:
        print("FAILED: %s" % ", ".join(FAIL))
        return 1
    # ONE line: run_all.py greps the RESULT: line, so a wrapped RESULT loses the rest of the verdict.
    print("RESULT: detach journey — %d checks green: split-to-new, attach-to-existing, full "
          "consolidation (source deleted + slug/id aliased), recompute/synthesis re-arm, 11 "
          "refusals and the alias/id boundary held on the live path (store -> detach -> fetch/search "
          "-> fresh open)." % (len(PASS),))
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
