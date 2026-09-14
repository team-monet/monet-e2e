#!/usr/bin/env python3
"""RE-57 (upstream #120) — `monet doctor --json` drops `startupFailure` on the failure path.

Context: `monet doctor --json` is the machine-readable operator/CI surface for a
damaged store. The success path carries `startupFailure: {"status":"none"}`, but
the FAILURE path (exactly where the record matters) omitted the key entirely on
the published 1.11.0, even while the same invocation's stderr surfaced the
startup-failure sidecar ("last recorded startup failure ... SQLITE_NOTADB") and
the sidecar file was on disk with `phase: "store-open"` + `error.code`.
Operator/CI reading the JSON therefore saw ONLY `RepairOperationError (not-sqlite)`
and lost the causal startup record -- the RE-50 out-of-band diagnosis (1.7.1,
guarded by test52 on the TEXT surface) was not reachable from `--json`.

Signal: upstream #120 was fixed by PR #153 (commit 9fa38c2, merged 2026-09-14)
which is IN `main` but NOT in any published release as of 1.11.0 -> this test is
the pre-registered flip candidate for the next release bump.

Contract asserted (3 states preserved verbatim, none|unreadable|found):
  - failure path + well-formed sidecar -> `startupFailure.status == "found"`,
    with `phase` and `error.code` intact;
  - fresh/success path -> key present, `status == "none"` (already true on 1.11.0).

Exit codes:
  0/1 = setup broke (test itself wrong)
  2   = XFAIL: failure-path `--json` omits/degrades `startupFailure` (bug present)
  3   = XPASS: failure-path `--json` carries the startup record (bug fixed)
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

ISSUE = "RE-57"
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


def run_cli(args, env=None, timeout=180):
    e = dict(os.environ)
    if NODE_PATH:
        e["PATH"] = NODE_PATH + ":" + e.get("PATH", "")
    if env:
        e.update(env)
    p = subprocess.run([CLI] + args, capture_output=True, text=True, env=e, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def last_json(text):
    for line in reversed([l for l in text.strip().splitlines() if l.strip()]):
        try:
            return json.loads(line)
        except Exception:
            continue
    return None


def main():
    base = tempfile.mkdtemp(prefix="monet-re57-e2e-")
    store = os.path.join(base, "store")
    fresh = os.path.join(base, "fresh")
    os.makedirs(store)
    os.makedirs(fresh)
    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")

    bug_present = False
    fixed = False
    try:
        # --- ARM A: failure path (real startup death, real sidecar) -----------
        with open(os.path.join(store, "monet.db"), "w") as f:
            f.write("this is not a sqlite database at all " * 50)

        rc, _o, err = run_cli(["start", "-d", store], env={"MONET_STORAGE_DIR": store})
        check("A_start_fails_closed", rc != 0, f"rc={rc}")

        sidecars = glob.glob(os.path.join(store, "*.startup-failure.json"))
        check("A_sidecar_written", len(sidecars) >= 1, f"n={len(sidecars)}")
        code = phase = None
        if sidecars:
            try:
                rec = json.load(open(sidecars[0]))
                phase = rec.get("phase")
                code = (rec.get("error") or {}).get("code")
                check("A_sidecar_names_cause", bool(phase) and bool(code),
                      f"phase={phase} code={code}")
            except Exception as e:
                check("A_sidecar_json_valid", False, f"parse err={e}")

        # text surface: already shipped + guarded by test52/RE-50 (must not regress)
        rc_t, out_t, err_t = run_cli(["doctor", "-d", store])
        text = (out_t + err_t).lower()
        check("A_text_doctor_surfaces_sidecar",
              "last recorded startup failure" in text and "startup-failure.json" in text,
              f"rc={rc_t}")

        # machine-readable surface: the surface #120 is about
        rc_j, out_j, err_j = run_cli(["doctor", "-d", store, "--json"])
        doc = last_json(out_j)
        check("A_json_parses", isinstance(doc, dict),
              f"keys={sorted(doc.keys()) if isinstance(doc, dict) else out_j[:120]!r}")
        if not isinstance(doc, dict):
            return 1
        check("A_failure_ok_false", doc.get("ok") is False, f"ok={doc.get('ok')!r}")

        sf = doc.get("startupFailure")
        print(f"    failure-path --json keys: {sorted(doc.keys())}")
        print(f"    failure-path startupFailure = {json.dumps(sf)}")
        surfaced = isinstance(sf, dict) and sf.get("status") == "found"
        if surfaced:
            check("A_json_startupFailure_found", True, json.dumps(sf)[:160])
            check("A_json_carries_phase", sf.get("phase") == phase, f"{sf.get('phase')}")
            check("A_json_carries_error_code", (sf.get("error") or {}).get("code") == code,
                  f"{(sf.get('error') or {}).get('code')}")
            fixed = True
        else:
            bug_present = True
            print("    -> the sidecar exists but the machine-readable failure document "
                  "does not carry it (#120)")

        # --- ARM B: success path keeps the key (hard contract, true on 1.11.0) -
        rc_b, out_b, _e_b = run_cli(["doctor", "-d", fresh, "--json"])
        doc_b = last_json(out_b)
        check("B_json_parses", isinstance(doc_b, dict), f"keys={sorted(doc_b.keys()) if isinstance(doc_b, dict) else None}")
        if isinstance(doc_b, dict):
            sf_b = doc_b.get("startupFailure")
            check("B_success_path_startupFailure_none",
                  isinstance(sf_b, dict) and sf_b.get("status") == "none",
                  f"startupFailure={json.dumps(sf_b)}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if fixed:
        print(f"\nRESULT: XPASS {ISSUE} — `doctor --json` failure path carries the startup "
              f"record (status: found, phase + error.code intact): upstream #120 fixed")
        return 3
    assert bug_present
    print(f"\nRESULT: XFAIL {ISSUE} — `doctor --json` failure path drops `startupFailure` "
          f"(sidecar on disk + text surface shows it); upstream #120 merged in main "
          f"(9fa38c2/PR #153) but NOT in the published release yet")
    return 2


if __name__ == "__main__":
    sys.exit(main())
