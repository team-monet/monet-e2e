#!/usr/bin/env python3
"""Scenario 10 extension: needsSynthesis flag LIFECYCLE across store→synth→store→synth.

Open question from run 6 (Finding 9 / next steps): "does needsSynthesis
re-flag when a NEW observation attaches after a synthesize?" Test11 proved
the flag is True at creation and clears on memory_synthesize; test12 proved
it stays cleared while no new observations arrive. This test drives the full
lifecycle:

1. N near-identical stores dedup into ONE concept (needsSynthesis=True).
2. memory_synthesize -> needsSynthesis=False, body = synthesized body.
3. NEW stores on the same topic AFTER the synthesize:
   - do they attach to the same concept (dedup vs the synthesized body)?
   - does needsSynthesis re-flag to True? (the open question)
4. Second memory_synthesize clears it again -> full loop is repeatable.
5. Data layer: concept_revisions gains a second row; observationCount keeps
   accumulating (synthesize never destroys observations).
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, DATA

DB = os.path.join(DATA, "monet.db")
CIRCLE = "e2e-s13-" + str(int(time.time()))
N = 5
K = 3  # post-synthesize stores

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
    try:
        c.initialize()

        # ---- Phase A: build a multi-observation concept (pre-synthesize) ----
        for i in range(N):
            r = c.call_json("memory_store",
                            {"content": f"lifecycle probe observation {i} on the reflag topic",
                             "circle": CIRCLE, "sourceRefs": ["e2e:test13"]})
            if concept_id is None:
                concept_id = r.get("conceptId")
                check("first_store_created", r.get("action") == "created", f"action={r.get('action')}")
        f = c.call_json("memory_fetch", {"id": concept_id, "observations": True})
        check("obs_count_N_before", f.get("observationCount") == N, f"obs={f.get('observationCount')}")
        check("needsSynthesis_true_before", f.get("needsSynthesis") is True,
              f"needsSynthesis={f.get('needsSynthesis')}")

        # ---- Phase B: synthesize -> flag clears ----
        body1 = "SYNTH ONE: all lifecycle observations agree on the reflag topic."
        ack1 = c.call_json("memory_synthesize", {"id": concept_id, "body": body1, "circle": CIRCLE})
        check("synth1_stored", ack1.get("message") == "synthesis stored", f"ack={str(ack1)[:100]}")
        f1 = c.call_json("memory_fetch", {"id": concept_id, "observations": True})
        check("needsSynthesis_cleared_after_synth1", not f1.get("needsSynthesis"),
              f"needsSynthesis={f1.get('needsSynthesis')}")
        check("body1_set", f1.get("body") == body1, f"body={str(f1.get('body'))[:60]}")

        # ---- Phase C: NEW stores AFTER synthesize (the open question) ----
        actions = []
        for i in range(K):
            r = c.call_json("memory_store",
                            {"content": f"lifecycle probe observation {N + i} on the reflag topic",
                             "circle": CIRCLE, "sourceRefs": ["e2e:test13"]})
            actions.append(r.get("action"))
            if concept_id is None:
                concept_id = r.get("conceptId")
        check("post_synth_attached_same_concept", all(a == "attached" for a in actions),
              f"actions={actions}")
        f2 = c.call_json("memory_fetch", {"id": concept_id, "observations": True})
        check("obs_count_accumulates", f2.get("observationCount") == N + K,
              f"obs={f2.get('observationCount')} (synthesize does NOT destroy observations)")
        check("needsSynthesis_REFLAGS_after_new_store", f2.get("needsSynthesis") is True,
              f"needsSynthesis={f2.get('needsSynthesis')} (open question answered: flag re-arms on new attach)")
        # body behavior after new attach: synthesized body preserved or overwritten?
        body_after = f2.get("body", "")
        check("body_kept_or_updated", isinstance(body_after, str) and len(body_after) > 0,
              f"body_len={len(body_after)} body={str(body_after)[:60]}")

        # ---- Phase D: second synthesize -> clears again (loop repeatable) ----
        body2 = "SYNTH TWO: the reflag topic gained post-synthesize observations."
        ack2 = c.call_json("memory_synthesize", {"id": concept_id, "body": body2, "circle": CIRCLE})
        check("synth2_stored", ack2.get("message") == "synthesis stored", f"ack={str(ack2)[:100]}")
        f3 = c.call_json("memory_fetch", {"id": concept_id, "observations": True})
        check("needsSynthesis_cleared_again", not f3.get("needsSynthesis"),
              f"needsSynthesis={f3.get('needsSynthesis')}")
        check("body2_last_wins", f3.get("body") == body2, f"body={str(f3.get('body'))[:60]}")
        check("obs_preserved_after_synth2", f3.get("observationCount") == N + K,
              f"obs={f3.get('observationCount')}")
    finally:
        c.close()

    # ---- Phase E: data layer (server closed -> sqlite3 safe) ----
    revs = sql(f"SELECT COUNT(*) FROM concept_revisions WHERE concept_id='{concept_id}';")
    check("revisions_2_rows", int(revs) == 2, f"rows={revs} (one per synthesize)")
    obs_rows = sql(f"SELECT COUNT(*) FROM observations WHERE concept_id='{concept_id}';")
    check("obs_rows_NplusK", int(obs_rows) == N + K, f"obs={obs_rows}")

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
