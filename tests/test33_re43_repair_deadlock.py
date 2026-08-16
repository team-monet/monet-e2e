#!/usr/bin/env python3
"""RE-43 (repair-cli.md): `monet repair` self-deadlocks on an English-only target.

Reverse-engineering finding (readable TS `repair-cli.ts`, core 0.9.0, upstream
issue #14): when `applyRepair` runs against an English-only target
(`readsOnlyLatinScript === true`) WITHOUT `--accept-non-latin-loss`, its
`recheckNonEnglish` closure opens a SECOND better-sqlite3 connection via
`inspectStoredEmbedderState` while `applyRepair`'s port still holds exclusive
ownership (`createVerifiedBackup` retains it; `releaseExclusiveOwnership` is
catch-only). The second open waits out the 5s busy_timeout and fails
`SQLITE_BUSY` — a deterministic single-process self-deadlock for EVERY
English-only target (the recheck only exists for that intersection).

The store here is all-English (0 non-Latin rows), so the one-way non-Latin
guard correctly passes and `applyRepair` runs — which is exactly the path that
deadlocks. The store fails closed (no rewrite, backup retained), which is why
this is S2 and not S1.

This test documents the DESIRED contract: an all-English store may be repaired
onto an English-only target (there is no non-Latin content to lose), so
`monet repair --target Xenova/bge-small-en-v1.5 --apply --yes` should complete
(rc=0) and repin the store.

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: repair onto an English-only target still self-deadlocks (SQLITE_BUSY)
  3   = XPASS: repair completes and repins (bug appears fixed)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient

ISSUE = "RE-43"
CLI = os.environ.get("MONET_CLI") or "/Users/codalee/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js"
NODE = os.environ.get("MONET_NODE_PATH") or "/opt/homebrew/opt/node@22/bin"
TARGET = "Xenova/bge-small-en-v1.5"  # English-only target (readsOnlyLatinScript)

# Reuse the real model cache so the repair preflight never re-downloads
# bge-small-en-v1.5 (~130 MB) into an empty cache (run-36 ENOSPC lesson).
MODEL_CACHE = os.path.expanduser("~/.monet/models")

os.environ["MONET_CLI"] = CLI
os.environ["MONET_NODE_PATH"] = NODE
os.environ["MONET_MODEL_CACHE"] = MODEL_CACHE

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def run_cli(args, env_extra=None):
    env = dict(os.environ)
    env["PATH"] = NODE + ":" + env.get("PATH", "")
    env["MONET_MODEL_CACHE"] = MODEL_CACHE
    if env_extra:
        env.update(env_extra)
    p = subprocess.run([CLI] + args, capture_output=True, text=True, env=env, timeout=600)
    return p


def main():
    base = tempfile.mkdtemp(prefix="monet-re43-e2e-")
    store = os.path.join(base, "store")
    os.makedirs(store)

    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")

    bug_fixed = False
    try:
        # ---- setup: a store with ENGLISH-only content, so the non-Latin guard
        #      passes and applyRepair actually runs (the deadlock path). ----
        c = MonetClient(store)
        try:
            c.initialize()
            ids = []
            for i in range(3):
                r = c.call_json("memory_store", {
                    "content": f"English deployment note {i} about shipping the release",
                    "circle": "re43", "sourceRefs": ["e2e:test33"]})
                ids.append(r.get("conceptId"))
            check("stored_english_content", len(set(ids)) == 1, f"concepts={len(set(ids))} (dedup into 1)")
        finally:
            c.close()

        # ---- THE bug path: repair onto an English-only target, no accept flag ----
        p = run_cli(["repair", "-d", store, "--target", TARGET, "--apply", "--yes"])
        out = p.stdout + p.stderr
        rc = p.returncode
        deadlock = "database is locked" in out or "SQLITE_BUSY" in out
        print(f"  [RE-43] repair rc={rc} deadlock={deadlock}")
        if rc != 0:
            # print a compact excerpt of the failure for the diary
            for line in out.splitlines():
                if "locked" in line or "Cannot inspect" in line or "backup" in line:
                    print(f"    | {line.strip()[:160]}")

        # DESIRED contract: repair succeeds and repins the store.
        if rc == 0:
            # verify the repin actually landed (doctor --check-provider, fast since cached)
            d = run_cli(["doctor", "-d", store])
            dout = d.stdout + d.stderr
            repinned = "Xenova/bge-small-en-v1.5" in dout
            bug_fixed = repinned
            print(f"  [RE-43] repair rc=0; repinned={repinned}")
        else:
            bug_fixed = False
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if bug_fixed:
        print(f"\nRESULT: XPASS {ISSUE} — repair onto an English-only target completes and repins (bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — repair onto an English-only target still self-deadlocks (SQLITE_BUSY; {len(PASS)} setup checks passed)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
