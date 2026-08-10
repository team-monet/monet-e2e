#!/usr/bin/env python3
"""Scenario 7: schema migration (real old-version fixture -> current).

Fixture: <MONET_TEST_DIR>/fixtures/schema4/monet.db — created with
@team-monet/monet@1.2.4 (schema 4, 15 tools, all-MiniLM-L6-v2 embedder) via
make_fixture_schema4.py. This test copies the pristine fixture to a fresh
scratch dir each run (re-run safe, GR-06), then:

  1. NEW (1.5.1) doctor detects the old schema: Schema 4 (supported: 12),
     Assessment unknown (schema too old to prove liveness).
  2. Opening the NEW server auto-migrates the DB (schema 4 -> 12).
  3. Post-migration: store + search work, OLD observation is preserved.
  4. doctor afterwards reports Schema 12, Integrity ok, durable pin set.
"""
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import MonetClient, CLI, NODE_PATH, DATA

FIXTURE = os.path.join(DATA, "fixtures", "schema4")
TOKEN = str(int(time.time()))
SCRATCH = os.path.join(DATA, f"run-mig7-{TOKEN}")
CIRCLE = "e2e-c7-" + TOKEN
SRC = ["e2e:test07"]

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def run_cli(args):
    env = dict(os.environ)
    if NODE_PATH:
        env["PATH"] = NODE_PATH + ":" + env.get("PATH", "")
    p = subprocess.run([CLI] + args, capture_output=True, text=True, env=env, timeout=300)
    return p.stdout + p.stderr


def main():
    # 0. pristine copy of the old-schema fixture
    os.makedirs(SCRATCH, exist_ok=True)
    for f in os.listdir(FIXTURE):
        shutil.copy2(os.path.join(FIXTURE, f), os.path.join(SCRATCH, f))
    check("fixture_copy", os.path.exists(os.path.join(SCRATCH, "monet.db")))

    # 1. new doctor detects old schema
    out1 = run_cli(["doctor", "-d", SCRATCH, "--check-provider"])
    check("detect_schema4", "4 (supported: 12)" in out1,
          [l.strip() for l in out1.splitlines() if l.strip().startswith("Schema")][:1])
    check("detect_unknown", "Assessment: unknown" in out1)

    # 2. open new server -> auto-migration
    c = MonetClient(SCRATCH)
    migrated_ok = False
    try:
        init = c.initialize()
        check("server_init_after_open", init.get("serverInfo", {}).get("name") is not None,
              init.get("serverInfo", {}))
        # post-migration store/search works
        r = c.call_json("memory_store", {"content": f"Post-migration observation {TOKEN}: schema now twelve.", "circle": CIRCLE, "sourceRefs": SRC})
        new_id = r.get("conceptId")
        check("store_post_migration", bool(new_id), f"id={new_id}")
        # old observation preserved (search by phrase from fixture content)
        rs = c.call_json("memory_search", {"query": "schema four fixture observation", "circle": "e2e", "limit": 3})
        hit_old = any("schema four fixture" in str(card.get("slug", "")) or "schema-four-fixture" in str(card.get("slug", ""))
                      for card in (rs.get("results") or []))
        check("old_obs_preserved", hit_old, f"top={[card.get('slug') for card in (rs.get('results') or [])[:3]]}")
        migrated_ok = True
    finally:
        c.close()

    # 3. doctor after migration
    out2 = run_cli(["doctor", "-d", SCRATCH, "--check-provider"])
    check("schema_now_12", "12 (supported: 12)" in out2,
          [l.strip() for l in out2.splitlines() if l.strip().startswith("Schema")][:1])
    check("integrity_ok", "Integrity:  ok" in out2)
    check("pin_set_after_migration", "Pin:" in out2 and "unknown" not in out2.split("Pin:")[1][:20],
          [l.strip() for l in out2.splitlines() if l.strip().startswith("Pin")][:1])
    check("migration_sentinel_known", "Migration:" in out2 and "unknown" not in out2.split("Migration:")[1][:20],
          [l.strip() for l in out2.splitlines() if l.strip().startswith("Migration")][:1])

    # 4. cleanup scratch dir (keep pristine fixture)
    shutil.rmtree(SCRATCH, ignore_errors=True)

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
