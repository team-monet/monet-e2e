#!/usr/bin/env python3
"""RE-45 (storage.md): memory_fetch is a hidden writer — fails under write contention.

Reverse-engineering finding (readable TS `storage.ts` + `engine.ts`, core 0.9.0,
upstream issue #19): `getConcept` — the read path behind `memory_fetch` — runs an
UNPROTECTED telemetry write *before* assembling the read result:

    UPDATE concepts SET usefulness_score = usefulness_score + 1,
      usefulness_last_fetched_at = ? WHERE id = ?

with no SQLITE_BUSY catch and no transaction (`engine.ts` ~5054-5056). Under a
concurrent write burst (single WAL writer slot), that bump blocks on the write
lock for the stacked busy_timeout (~11.8s in WAL: better-sqlite3's open-time
`timeout` default + the explicit `busy_timeout=5000` pragma) and then throws, so
the ENTIRE fetch fails — a pure read is turned into a writer, and a telemetry
failure takes down the read it was only supposed to annotate.

This test documents the DESIRED contract: a fetch (a read) must not fail on a
telemetry write — the usefulness bump should be best-effort (skip or retry) and
the concept still returned. Reproduce deterministically by holding a
`BEGIN IMMEDIATE` write lock on the store's SQLite file from a second connection
while calling `memory_fetch`.

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: fetch fails "database is locked" under contention (bug present)
  3   = XPASS: fetch returns the concept despite contention (bug appears fixed)
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient

ISSUE = "RE-45"
CLI = os.environ.get("MONET_CLI") or "/Users/codalee/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js"
NODE = os.environ.get("MONET_NODE_PATH") or "/opt/homebrew/opt/node@22/bin"

# Reuse the real model cache so the server never re-downloads bge-m3 q8 (~1GB)
# into an empty cache (run-36 ENOSPC lesson).
MODEL_CACHE = os.path.expanduser("~/.monet/models")

os.environ["MONET_CLI"] = CLI
os.environ["MONET_NODE_PATH"] = NODE
os.environ["MONET_MODEL_CACHE"] = MODEL_CACHE

CONTENT = "the unique fetch-contention probe concept zeta mark"
CIRCLE = "re45"

# busy_timeout stacks to ~11.8s in WAL (verified run 43); hold the write lock
# well past that so the fetch's usefulness-bump UPDATE is deterministically
# forced to time out while the lock is still held.
HOLD_SECONDS = 20.0

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def main():
    base = tempfile.mkdtemp(prefix="monet-re45-e2e-")
    store = os.path.join(base, "store")
    os.makedirs(store)

    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")

    bug_fixed = False
    failure = ""
    try:
        # ---- setup: spawn a server, store ONE concept, control-fetch it ----
        c = MonetClient(store)
        try:
            c.initialize()
            r = c.call_json("memory_store", {
                "content": CONTENT, "circle": CIRCLE, "sourceRefs": ["e2e:test36"]})
            cid = r.get("conceptId")
            check("stored_concept", r.get("action") == "created" and bool(cid), f"id={cid}")

            db = os.path.join(store, "monet.db")
            check("db_exists", os.path.exists(db), f"size={os.path.getsize(db)}")

            # control: fetch with NO contention returns a real concept card
            f0 = c.call_json("memory_fetch", {"id": cid})
            control_ok = isinstance(f0, dict) and "_rawText" not in f0 and isinstance(f0.get("body"), str)
            check("control_fetch_returns_concept", control_ok,
                  f"keys={sorted(f0.keys()) if isinstance(f0, dict) else 'n/a'}")

            # ---- THE bug path: hold a write lock, fetch under contention ----
            time.sleep(1.0)  # let any post-commit autocheckpoint settle
            holder = sqlite3.connect(db, timeout=5.0, isolation_level=None)
            holder.execute("BEGIN IMMEDIATE")
            holder.execute("CREATE TABLE IF NOT EXISTS e2e_re45_lock (x INTEGER)")
            holder.execute("INSERT INTO e2e_re45_lock (x) VALUES (1)")
            check("write_lock_held", True, "BEGIN IMMEDIATE + insert (second connection)")

            result = {}

            def do_fetch():
                t0 = time.time()
                try:
                    result["resp"] = c.call_json("memory_fetch", {"id": cid}, timeout=120)
                    result["ok"] = True
                except Exception as e:  # noqa: BLE001 — capture any transport error
                    result["ok"] = False
                    result["err"] = str(e)
                result["elapsed"] = round(time.time() - t0, 2)

            t = threading.Thread(target=do_fetch)
            t.start()
            time.sleep(0.5)          # let the fetch reach the write lock
            time.sleep(HOLD_SECONDS)  # hold past the ~11.8s stacked busy_timeout
            holder.execute("COMMIT")
            holder.close()
            t.join(timeout=60)

            resp = result.get("resp")
            if result.get("ok") and isinstance(resp, dict) and "_rawText" not in resp:
                bug_fixed = True
            else:
                if isinstance(resp, dict) and "_rawText" in resp:
                    failure = resp["_rawText"]
                elif not result.get("ok"):
                    failure = result.get("err", "unknown error")
                else:
                    failure = f"unexpected response: {str(resp)[:120]}"
            print(f"  [RE-45] fetch_ok={result.get('ok')} elapsed={result.get('elapsed')}s "
                  f"failure={failure!r}")
        finally:
            c.close()
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if bug_fixed:
        print(f"\nRESULT: XPASS {ISSUE} — memory_fetch returns the concept under write contention "
              f"(the telemetry bump no longer takes down the read; bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — memory_fetch fails under write contention "
          f"({failure!r}; {len(PASS)} setup checks passed)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
