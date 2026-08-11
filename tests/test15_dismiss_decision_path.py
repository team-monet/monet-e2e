#!/usr/bin/env python3
"""Scenario 6 extension: contradiction DISMISS decision path.

Open question from run 9 (next step #2): "Contradiction: `dismiss` decision
path — what state does it leave (body/flag/revisions)? Guard message mentions
it as the no-verdict option."

Contrasts with test14 (accept-new): accept-new on a multi-observation concept
REFUSES without a reconciled body (anti-guess guard). Dismiss is the no-verdict
option — hypotheses to verify:
1. dismiss succeeds WITHOUT `body` even on a multi-observation concept
   (it does not supersede any prior claim, so no guess is being made).
2. dismiss closes the contradiction: openContradictions empty, disputed=0.
3. dismiss does NOT change the concept body (no verdict -> no rewrite).
4. dismiss does NOT write a concept_revisions row (body unchanged).
5. dismiss does NOT add observations (obsCount unchanged).
6. needsSynthesis stays True if a contradiction observation re-armed it
   (resolve is not a synthesize — same as accept-new, finding 13).
7. Data layer: contradiction row retained with a terminal status and
   resolved_at/resolved_by populated; body column unchanged.

Dual-verdict comparison: the same fixture is run twice (fresh circles) — once
resolved accept-new-with-body, once dismissed — to pin down the delta in the
data layer (revision row + body vs no revision + same body).
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
                        {"content": f"dismiss-path probe observation {i} topic {TOKEN}",
                         "circle": circle, "sourceRefs": ["e2e:test15"]})
        if cid is None:
            cid = r.get("conceptId")
    corr = f"dismiss-path probe CORRECTION: the opposite is true on topic {TOKEN}."
    r = c.call_json("memory_store", {"content": corr, "circle": circle,
                                     "kind": "correction", "sourceRefs": ["e2e:test15"]})
    cont_id = (r.get("contradiction") or {}).get("id")
    assert cid and cont_id, f"failed to open contradiction: cid={cid} cont={cont_id}"
    return cid, cont_id


def main():
    c = MonetClient(DATA)
    try:
        c.initialize()

        # ================= ARM A: DISMISS on a multi-observation concept =================
        circle_a = "e2e-s15a-" + TS
        cid_a, cont_a = build_and_open(c, circle_a)
        body_before_a = c.call_json("memory_fetch", {"id": cid_a}).get("body")
        obs_before_a = c.call_json("memory_fetch", {"id": cid_a, "observations": True}).get("observationCount")
        f_a = c.call_json("memory_fetch", {"id": cid_a, "observations": True})
        flag_before_a = f_a.get("needsSynthesis")

        # dismiss WITHOUT body — the no-verdict option (contrast: accept-new refuses)
        r_d = c.call_json("memory_resolve", {"contradictionId": cont_a, "decision": "dismiss",
                                             "circle": circle_a, "resolvedBy": "monet-e2e-test"})
        check("dismiss_no_body_succeeds", r_d.get("status") == "active",
              f"dismiss without body works on multi-obs concept: {str(r_d)[:100]}")

        ov_a = c.call_json("memory_overview", {"circle": circle_a})
        check("dismiss_clears_open", len(ov_a.get("openContradictions") or []) == 0,
              f"open={len(ov_a.get('openContradictions') or [])}")
        check("dismiss_clears_disputed", ov_a.get("counts", {}).get("disputed", 0) == 0,
              f"disputed={ov_a.get('counts', {}).get('disputed')}")

        f_after_a = c.call_json("memory_fetch", {"id": cid_a, "observations": True})
        check("dismiss_keeps_body", f_after_a.get("body") == body_before_a,
              f"body unchanged by dismiss (no verdict -> no rewrite)")
        check("dismiss_keeps_obs", f_after_a.get("observationCount") == obs_before_a,
              f"obs={f_after_a.get('observationCount')} (dismiss writes no observation)")
        check("dismiss_does_not_clear_needsSynthesis", f_after_a.get("needsSynthesis") == flag_before_a,
              f"needsSynthesis={f_after_a.get('needsSynthesis')} (resolve is not a synthesize)")

        # ============ ARM B: ACCEPT-NEW on the same fixture for the delta ============
        circle_b = "e2e-s15b-" + TS
        cid_b, cont_b = build_and_open(c, circle_b)
        body_before_b = c.call_json("memory_fetch", {"id": cid_b}).get("body")
        r_a = c.call_json("memory_resolve", {"contradictionId": cont_b, "decision": "accept-new",
                                             "circle": circle_b, "resolvedBy": "monet-e2e-test",
                                             "body": f"RECONCILED-B: verdict on topic {TOKEN}."})
        check("accept_new_with_body_succeeds", r_a.get("status") == "active", str(r_a)[:100])
        f_after_b = c.call_json("memory_fetch", {"id": cid_b})
        check("accept_new_replaces_body", f_after_b.get("body") != body_before_b,
              "accept-new with body rewrites the concept body (dismiss does not)")
    finally:
        c.close()

    # ================= Data layer =================
    # Contradiction row: retained after dismiss, terminal status, resolved fields set
    d_status = sql(f"SELECT status FROM contradictions WHERE id='{cont_a}';")
    check("dismiss_contradiction_row_status_terminal", d_status in ("dismissed", "resolved", "closed"),
          f"status={d_status} (row retained, no longer open)")
    d_meta = sql(f"SELECT resolved_by || '|' || COALESCE(resolved_at,'') FROM contradictions WHERE id='{cont_a}';")
    check("dismiss_sets_resolved_meta", "monet-e2e-test" in d_meta and d_meta.split("|")[1] != "",
          f"resolved_by/resolved_at populated: {d_meta}")
    d_kind = sql(f"SELECT kind FROM contradictions WHERE id='{cont_a}';")
    check("dismiss_retains_kind", d_kind == "value-conflict", f"kind={d_kind}")

    # Body column: dismiss does not inject a verdict text (observation appends
    # DO land in the body at store time — CORRECTION text is expected there —
    # but a dismiss must not rewrite it with a reconciled/verdict body).
    d_body = sql(f"SELECT body FROM concepts WHERE id='{cid_a}';")
    check("dismiss_body_column_unchanged", "RECONCILED" not in d_body and "CORRECTION" in d_body,
          f"body keeps observation appends, no verdict text injected under dismiss")

    # Revisions: dismiss writes NO revision row (body unchanged); accept-new writes one
    rev_a = sql(f"SELECT COUNT(*) FROM concept_revisions WHERE concept_id='{cid_a}';")
    rev_b = sql(f"SELECT COUNT(*) FROM concept_revisions WHERE concept_id='{cid_b}';")
    check("dismiss_writes_no_revision", int(rev_a) == 0, f"revisions(dismiss)={rev_a}")
    check("accept_new_writes_revision", int(rev_b) == 1, f"revisions(accept-new)={rev_b}")

    # Observations: unchanged by both verdicts (N + 1 correction only)
    obs_a = sql(f"SELECT COUNT(*) FROM observations WHERE concept_id='{cid_a}';")
    obs_b = sql(f"SELECT COUNT(*) FROM observations WHERE concept_id='{cid_b}';")
    check("dismiss_obs_rows", int(obs_a) == N + 1, f"obs(dismiss)={obs_a}")
    check("accept_new_obs_rows", int(obs_b) == N + 1, f"obs(accept-new)={obs_b}")

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
