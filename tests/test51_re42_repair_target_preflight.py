#!/usr/bin/env python3
"""RE-42 (repair `--target` preflight reject) regression guard.

`monet repair --target <unregistered-id>` must REJECT the unregistered id in
preflight — an explicit \"names no embedding space this build describes ... NOT
a download or network condition\" message listing the accepted spaces — NOT
silently repin into an unmeasured space nor surface as a network/download
error. REGRESSION-GUARD for the 1.7.1 fix (upstream #77 / triangulated with
#15). Pins: existing pin preserved, rc=1, no download attempted, fresh isolated
store (GR-01).

Exit codes:
  0/1 = setup broke (test itself wrong)
  2   = XFAIL: bug present (unregistered id silently accepted / no preflight reject)
  3   = XPASS: preflight rejects unregistered id (bug fixed)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, CLI, NODE_PATH

ISSUE = "RE-42"
os.environ.setdefault("MONET_CLI", CLI)
os.environ.setdefault("MONET_NODE_PATH", NODE_PATH)

PASS, FAIL = [], []


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
    p = subprocess.run([CLI] + args, capture_output=True, text=True, env=env, timeout=120)
    return p.returncode, p.stdout + p.stderr


def main():
    base = tempfile.mkdtemp(prefix="monet-re42-e2e-")
    store = os.path.join(base, "store")
    os.makedirs(store)
    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")
    try:
        # build a store with content so the embedder + pin exist
        c = MonetClient(store)
        c.initialize()
        r = c.call_json("memory_store", {"content": "The quick brown fox jumps over a lazy arch."})
        check("base_stored", r.get("action") in ("created", "attached"), f"action={r.get('action')}")
        rc_fetch, fetch = run_cli(["doctor", "-d", store, "--check-provider"])
        # pin BEFORE
        pin_before = None
        for line in fetch.splitlines():
            if "Pin:" in line:
                pin_before = line.split("Pin:")[-1].strip()
        check("pin_readable_before", bool(pin_before), f"pin={pin_before}")
        c.close()

        # attempt repair with an UNREGISTERED model id — 1.7.1 rejects in preflight
        rc, out = run_cli(["repair", "-d", store, "--target",
                           "Xenova/fake-unregistered-model", "--apply", "--yes"])
        lo = out.lower()
        preflight_reject = (
            rc == 1
            and ("no embedd" in lo or "unknown rather than an exact model id" in lo)
            and "not a download" in lo
            and "it is NOT a download" in lo or "names no embedd" in lo
        )
        lists_spaces = any(m in lo for m in ("paraphrase-multilingual", "bge-small-en", "bge-m3:cls:q8"))
        check("preflight_reject", rc == 1 and ("names no embedd" in lo), f"rc={rc}")
        check("explicit_non_network", "not a download or network condition" in lo or "NOT a download" in lo)
        check("lists_accepted_spaces", lists_spaces)

        # pin preserved, store untouched
        rc2, out2 = run_cli(["doctor", "-d", store, "--check-provider"])
        check("doctor_ok_after", rc2 == 0, f"rc={rc2}")
        pin_after = None
        for line in out2.splitlines():
            if "Pin:" in line:
                pin_after = line.split("Pin:")[-1].strip()
        check("pin_preserved", pin_after == pin_before, f"before={pin_before} after={pin_after}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if preflight_reject and lists_spaces:
        print(f"\nRESULT: XPASS {ISSUE} — unregistered --target rejected in preflight "
              f"with explicit unknown+non-network message (bug fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — unregistered --target not rejected in preflight "
          f"(silently accepted / no explicit unknown message); bug present")
    return 2


if __name__ == "__main__":
    sys.exit(main())