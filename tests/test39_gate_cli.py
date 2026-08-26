#!/usr/bin/env python3
"""Scenario (CLI surface): `monet gate` — retired-stub contract (test39, 1.9.0).

The offline gate mirror evaluator (gate-cli.ts, the five-outcome exit-code
mirror: USAGE_ERROR 1 / SILENCE 0 / STAGE_HIT 10 / ADVISORY 20 / BLOCKING 30 /
OVERFLOW 40, tested against the GATE_MIRROR_FORMAT=4 mirror) was RETIRED in
@team-monet/monet 1.9.0. `monet gate` is now a stub: it no longer evaluates any
hook payload and answers with silence, failing OPEN so nothing is blocked:

  monet gate: Monet's gate is retired — this hook no longer evaluates anything
  and is failing OPEN (nothing is blocked). Run `monet uninstall` to remove it
  from your Claude Code settings, then restart Claude Code. This notice is shown
  once.\n                        <- rc 0

This pins the retired-stub wire contract that replaced the evaluator:
  - `monet gate --help` documents the retirement + recovery (`monet uninstall`)
  - a bare `monet gate` invocation is a clean rc=0 fail-open (never blocks)
  - the notice names the recovery path (uninstall) and the fail-open intent
  - the old evaluator contracts are gone: no mirror is read (an explicit
    --mirror/--circle no longer drives a five-outcome decision)

Isolation (GR-01): HOME + MONET_STORAGE_DIR redirected to temp dirs; GateClimbs
nothing, loads no embedder, touches no store. This status is the retired-stub
baseline; a later Monet release that revives gate evaluation must re-baseline
this test (flip back to a real evaluator contract).

Exit codes: 0 = PASS, 1 = FAIL (unexpected).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import run_cli

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
    with tempfile.TemporaryDirectory() as td:
        home = os.path.join(td, "home")
        store = os.path.join(td, "store")
        os.makedirs(home)
        os.makedirs(store)
        env = {"HOME": home, "MONET_STORAGE_DIR": store, "MONET_CIRCLE": "e2e-gate"}

        # G0. help documents the retirement + recovery path.
        rc, out, err = run_cli(["gate", "--help"], env_extra=env)
        text = out + "\n" + err
        check("G_help_retired", "retired" in text.lower(), f"help={text.strip()[:80]!r}")
        check("G_help_recovery", "uninstall" in text, "help names uninstall recovery")

        # G1. a bare invocation is a clean rc=0 fail-open (nothing blocked).
        rc, out, err = run_cli(["gate"], env_extra=env)
        text = out + "\n" + err
        check("G_bare_rc0_fail_open", rc == 0, f"rc={rc}")
        check("G_notice_retired", "retired" in text and "no longer evaluates" in text,
              f"msg={text.strip()[-90:]!r}")
        check("G_notice_uninstall_path", "uninstall" in text,
              "notice names the uninstall recovery path")
        check("G_notice_fail_open", "failing OPEN" in text or "nothing is blocked" in text,
              "notice states fail-open / nothing blocked")

        # G2. the OLD evaluator surface is gone: an explicit --mirror/--circle no
        #     longer drives a decision. Fail-open is preserved: rc is ALWAYS 0 — the
        #     stub either names the retirement notice OR answers with SILENCE (empty
        #     stdout when it tries to read a mirror that does not exist); never a
        #     blocking exit code.
        rc, out, err = run_cli(
            ["gate", "--circle", "e2e-gate", "--mirror", os.path.join(td, "nonexistent-mirror.json")],
            env_extra=env)
        text = out + "\n" + err
        check("G_mirror_fail_open_nonblocking", rc == 0 and (not text.strip() or "retired" in text.lower()),
              f"rc={rc} empty_out={not text.strip()}")

        # G3. `monet uninstall` still exists as the recovery command (rc 0, clean).
        rc, out, err = run_cli(["uninstall"], env_extra=env)
        check("G_uninstall_recovery_exists", rc == 0 and ("no Monet hook entries" in (out + err)),
              f"rc={rc}")

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
        return 1
    print(f"\nRESULT: PASS — `monet gate` retired-stub contract pinned "
          f"(fail-open, uninstall recovery, no evaluator surface) ({len(PASS)} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())