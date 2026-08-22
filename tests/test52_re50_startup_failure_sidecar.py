#!/usr/bin/env python3
"""RE-50 (startup-failure sidecar + doctor read) regression guard.

Startup that dies BEFORE the MCP protocol channel exists (store-open /
model-load) must write a `<db>.startup-failure.json` sidecar and `monet doctor`
must read + surface it — so the operator can see WHY it died instead of a bare
\"Connection closed\". REGRESSION-GUARD for the 1.7.1 out-of-band diagnosis
(mcp-server.ts #12/#13/#79). Fail-closed is preserved (start still dies); the
DIAGNOSIS is now available out-of-band.

Exit codes:
  0/1 = setup broke (test itself wrong)
  2   = XFAIL: bug present (silent startup death, no sidecar / doctor can't read it)
  3   = XPASS: startup-failure sidecar written + doctor reads it (bug fixed)
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import CLI, NODE_PATH

ISSUE = "RE-50"
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


def run_cli(args, env=None):
    e = dict(os.environ)
    if NODE_PATH:
        e["PATH"] = NODE_PATH + ":" + e.get("PATH", "")
    if env:
        e.update(env)
    p = subprocess.run([CLI] + args, capture_output=True, text=True, env=e, timeout=120)
    return p.returncode, p.stdout + p.stderr


def main():
    base = tempfile.mkdtemp(prefix="monet-re50-e2e-")
    store = os.path.join(base, "store")
    os.makedirs(store)
    db = os.path.join(store, "monet.db")
    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")

    sidecar_written = False
    doctor_reads = False
    try:
        # corrupt the DB so store-open fails at startup
        with open(db, "w") as f:
            f.write("this is not a sqlite database at all " * 50)

        rc, out = run_cli(["start", "-d", store], env={"MONET_STORAGE_DIR": store})
        check("start_fails_closed", rc != 0, f"rc={rc}")

        # sidecar written with error details
        sidecars = glob.glob(os.path.join(store, "*.startup-failure.json"))
        check("sidecar_written", len(sidecars) >= 1, f"n={len(sidecars)}")
        if sidecars:
            try:
                data = json.load(open(sidecars[0]))
                err = data.get("error", {})
                names_phase = ("phase" in data) and ("error" in data)
                has_cause = bool(err.get("message")) and bool(err.get("code"))
                check("sidecar_error_details", names_phase and has_cause,
                      f"phase={data.get('phase')} err={err.get('name')}:{err.get('code')}")
            except Exception as e:
                check("sidecar_json_valid", False, f"parse err={e}")
            sidecar_written = len(sidecars) >= 1

        # doctor reads the sidecar
        rc2, out2 = run_cli(["doctor", "-d", store])
        lo2 = out2.lower()
        doctor_reads = "last recorded startup failure" in lo2 and "startup-failure.json" in lo2
        check("doctor_reads_sidecar", doctor_reads)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if sidecar_written and doctor_reads:
        print(f"\nRESULT: XPASS {ISSUE} — startup-failure sidecar written + monet doctor "
              f"reads/surfaces it as out-of-band diagnosis (bug fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — startup death is silent (no sidecar / doctor can't "
          f"read it); every cause still reads as 'Connection closed'")
    return 2


if __name__ == "__main__":
    sys.exit(main())