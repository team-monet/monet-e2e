#!/usr/bin/env python3
"""Scenario 8: repair regression (post-migration state).

Verifies the isolated store is in the repaired/migrated state:
- doctor: Assessment=safe, Schema 12/12, Integrity ok
- Pin = Xenova/paraphrase-multilingual-MiniLM-L12-v2 (source: migrated)
- embedding populations fully populated (no zero/malformed)
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import CLI, NODE_PATH, DATA


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
    out = run_cli(["doctor", "-d", DATA, "--check-provider"])
    check("assessment_safe", "Assessment: safe" in out, out.split("Assessment:")[1][:40] if "Assessment:" in out else "?")
    check("schema_12", "Schema:     12 (supported: 12)" in out or "Schema: 12 (supported: 12)" in out)
    check("integrity_ok", "Integrity:  ok" in out)
    check("pin_multilingual", "Xenova/paraphrase-multilingual-MiniLM-L12-v2" in out and "source: migrated" in out,
          [l for l in out.splitlines() if l.startswith("Pin")][:1])
    check("native_obs_embedded",
          "nativeObservations: rows " in out and "malformed 0" in out and "zero 0" in out)
    check("backup_exists", os.path.isdir(os.path.join(DATA, "backups")) and len(os.listdir(os.path.join(DATA, "backups"))) >= 1)

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
