#!/usr/bin/env python3
"""Scenario 10: dedup growth observation (data-layer).

Stores N near-identical observations in a fresh circle and verifies the dedup
pattern at both API and DB layer:
1. first store creates a concept; later near-identical stores ATTACH to it
   (same conceptId, no concept explosion)
2. observationCount grows 1:1 with stores; body accumulates every observation
3. clearly distinct content stays in a separate concept (control)
4. DB layer (after server close): observation_segments rows == observations
   (1:1), observation_tokens accumulate per observation (no token loss)
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, DATA

DB = os.path.join(DATA, "monet.db")
CIRCLE = "e2e-s10-" + str(int(time.time()))
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
    try:
        c.initialize()

        # 1-3. near-identical stores -> one concept, observations accumulate
        actions = []
        for i in range(N):
            content = f"dedup growth observation number {i} about the same underlying topic"
            r = c.call_json("memory_store", {"content": content, "circle": CIRCLE, "sourceRefs": ["e2e:test10"]})
            actions.append(r.get("action"))
            if concept_id is None:
                concept_id = r.get("conceptId")
            else:
                check(f"dedup_attach_{i}", r.get("conceptId") == concept_id, f"action={r.get('action')}")
        check("first_store_created", actions[0] == "created", f"actions={actions}")
        check("all_attached_after_first", all(a == "attached" for a in actions[1:]), f"actions={actions}")

        r = c.call_json("memory_fetch", {"id": concept_id, "observations": True})
        check("observation_count_grows", r.get("observationCount") == N, f"obs={r.get('observationCount')}")
        body = r.get("body", "")
        check("body_accumulates", sum(f"number {i}" in body for i in range(N)) == N, f"body_lines={body.count(chr(10)) + 1}")

        # control: clearly distinct content must NOT merge into the same concept
        r2 = c.call_json("memory_store", {"content": "completely unrelated topic about kangaroos and eucalyptus", "circle": CIRCLE, "sourceRefs": ["e2e:test10"]})
        check("distinct_stays_separate", r2.get("conceptId") != concept_id and r2.get("action") == "created",
              f"action={r2.get('action')} new={str(r2.get('conceptId'))[:8]}")
    finally:
        c.close()

    # 4. DB layer (server closed -> sqlite3 can read safely)
    if concept_id:
        obs = int(sql(f"SELECT COUNT(*) FROM observations WHERE concept_id='{concept_id}';"))
        seg = int(sql(f"SELECT COUNT(*) FROM observation_segments WHERE observation_id IN (SELECT id FROM observations WHERE concept_id='{concept_id}');"))
        tok = int(sql(f"SELECT COUNT(*) FROM observation_tokens WHERE observation_id IN (SELECT id FROM observations WHERE concept_id='{concept_id}');"))
        check("segments_1to1", seg == obs, f"obs={obs} seg={seg}")
        check("tokens_accumulate", tok >= obs and tok <= obs * 40, f"obs={obs} tok={tok}")

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
