#!/usr/bin/env python3
"""Scenario 10 extension: synthesis transition + growth curve (API + data layer).

Phase A — needsSynthesis transition:
1. N near-identical stores in a fresh circle dedup into ONE concept.
2. needsSynthesis=True appears once a concept has multiple observations.
3. memory_synthesize stores a coherent body, CLEARS needsSynthesis, records a
   concept_revisions row (version bump), and preserves observationCount.

Phase B — growth curve (data layer, after server close):
4. M larger-scale near-identical stores: observation_segments stays 1:1 with
   observations, observation_tokens accumulate (no loss), body accumulates.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, DATA

DB = os.path.join(DATA, "monet.db")
CIRCLE = "e2e-s11-" + str(int(time.time()))
N = 10
M = 30

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

        # ---- Phase A: synthesis transition ----
        concept_id = None
        actions = []
        for i in range(N):
            content = f"needs synthesis observation number {i} about the same shared topic"
            r = c.call_json("memory_store", {"content": content, "circle": CIRCLE, "sourceRefs": ["e2e:test11"]})
            actions.append(r.get("action"))
            if concept_id is None:
                concept_id = r.get("conceptId")
            if i == 1:
                f2 = c.call_json("memory_fetch", {"id": concept_id, "observations": True})
                check("needsSynthesis_after_2_stores", f2.get("needsSynthesis") is True,
                      f"needsSynthesis={f2.get('needsSynthesis')}")
        check("first_store_created", actions[0] == "created", f"actions={actions}")
        check("all_attached_after_first", all(a == "attached" for a in actions[1:]), f"actions={actions}")

        f = c.call_json("memory_fetch", {"id": concept_id, "observations": True})
        check("needsSynthesis_before_syn", f.get("needsSynthesis") is True,
              f"needsSynthesis={f.get('needsSynthesis')}")
        check("obs_count_10", f.get("observationCount") == N, f"obs={f.get('observationCount')}")

        syn_body = "SYNTHESIS TEST: all observations agree the shared topic stays consistent across stores."
        ack = c.call_json("memory_synthesize", {"id": concept_id, "body": syn_body, "circle": CIRCLE})
        check("synth_ack_ok", ack.get("message") == "synthesis stored", f"ack={str(ack)[:120]}")
        check("synth_version_pos", isinstance(ack.get("version"), int) and ack.get("version", 0) >= 1,
              f"version={ack.get('version')}")
        check("synth_dirty_false", ack.get("dirty") is False, f"dirty={ack.get('dirty')}")

        f2 = c.call_json("memory_fetch", {"id": concept_id, "observations": True})
        check("needsSynthesis_cleared", not f2.get("needsSynthesis"), f"needsSynthesis={f2.get('needsSynthesis')}")
        check("body_replaced", f2.get("body") == syn_body, f"body={str(f2.get('body'))[:60]}")
        check("obs_preserved_after_syn", f2.get("observationCount") == N, f"obs={f2.get('observationCount')}")

        # ---- Phase B: growth curve (another topic, M stores) ----
        g_id = None
        for i in range(M):
            content = f"growth curve record {i} for the load test topic keeps the same shape"
            r = c.call_json("memory_store", {"content": content, "circle": CIRCLE, "sourceRefs": ["e2e:test11"]})
            if g_id is None:
                g_id = r.get("conceptId")
                check("growth_first_created", r.get("action") == "created", f"action={r.get('action')}")
        g = c.call_json("memory_fetch", {"id": g_id, "observations": True})
        check("growth_obs_30", g.get("observationCount") == M, f"obs={g.get('observationCount')}")
        body = g.get("body", "")
        check("growth_body_accumulates", sum(f"record {i}" in body for i in range(M)) == M,
              f"lines={body.count(chr(10)) + 1}")
    finally:
        c.close()

    # ---- data layer (server closed -> sqlite3 safe) ----
    for label, cid, expected in (("synth", concept_id, N), ("growth", g_id, M)):
        obs = int(sql(f"SELECT COUNT(*) FROM observations WHERE concept_id='{cid}';"))
        seg = int(sql(f"SELECT COUNT(*) FROM observation_segments WHERE observation_id IN (SELECT id FROM observations WHERE concept_id='{cid}');"))
        tok = int(sql(f"SELECT COUNT(*) FROM observation_tokens WHERE observation_id IN (SELECT id FROM observations WHERE concept_id='{cid}');"))
        check(f"{label}_segments_1to1", seg == obs, f"obs={obs} seg={seg}")
        check(f"{label}_tokens_accumulate", tok >= obs, f"obs={obs} tok={tok}")

    if concept_id:
        rev_body = sql(f"SELECT body FROM concept_revisions WHERE concept_id='{concept_id}' ORDER BY version DESC LIMIT 1;")
        check("revision_row_recorded", rev_body == syn_body, f"rev_len={len(rev_body)}")

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
