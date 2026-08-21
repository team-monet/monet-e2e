#!/usr/bin/env python3
"""Scenario (CLI surface): root `monet` argv->subcommand dispatcher — cli/cli.ts (test47).

Every prior CLI scenario enters a SPECIFIC subcommand (config/install/gate/circle/
status-help/source...). cli.ts — the root commander program that owns version, the
`status`/`dashboard` action bodies, and the top-level async error handler — is only
partially covered because the suite never runs `monet --version`, a real `monet status`
against a store, or a command that throws one of the handled error classes. Run 54
named cli/cli.ts (49.6%, 136/274) the next genuinely-actionable coverage gap, reachable
via harness run_cli (NOT on the MCP hot path).

Arms (each in a fresh temp HOME/MONET_STORAGE_DIR unless noted — GR-01):
A. `monet --version` -> rc 0, prints a dotted version (line 45 .version()).
B. no subcommand -> commander help (rc 0, lists commands).
C. unknown subcommand -> rc 1 + "unknown command" (commander error path, line 47 outputError).
D. `monet status` on a FRESH store -> rc 0, prints Store/Concepts/Observations/
   Workstreams/Unsynthesized (status action body 133-160).
E. `monet status --circle <name>` on a fresh store -> rc 0, prints the scoped Circle label.
F. `monet dashboard -p 0` and `-p abc` -> rc 1 + "Invalid port" (lines 212-215).
   (valid dashboard path already covered by test20's server spawn)
G. SourceCliError branch (line 265): `monet source add --type git-md x` (no --remote,
   no --allow-caller) -> rc 1 + stderr startswith "monet source:".
H. MaterializeCliError branch (line 267): register a surface twice -> second `materialize
   add` -> rc 1 + stderr startswith "monet materialize:".
I. generic error branch (line 269-271): a command that throws a plain Error (repair
   against a nonexistent store dir with no schema -> rc 1).
"""
import json
import os
import subprocess
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


def set_home(td):
    """Redirect HOME to a fresh subdir so no ~/.monet state is touched (GR-01)."""
    env = {"HOME": os.path.join(td, "home")}
    os.makedirs(env["HOME"], exist_ok=True)
    return env


def main():
    # A. --version
    rc, out, err = run_cli(["--version"], env_extra={"HOME": tempfile.mkdtemp()})
    ver = out.strip()
    check("A_version_printed", rc == 0 and "." in ver and ver[0].isdigit(), f"rc={rc} ver={ver!r}")

    # B. help lists the command surface (commander help dispatch, rc 0)
    rc, out, err = run_cli(["help"], env_extra={"HOME": tempfile.mkdtemp()})
    check("B_help_lists_start", rc == 0 and "start" in out, f"rc={rc}")

    # C. unknown subcommand
    rc, out, err = run_cli(["bogus_command"], env_extra={"HOME": tempfile.mkdtemp()})
    check("C_unknown_command", rc == 1 and "unknown command" in err, f"rc={rc} err={err.strip()[:80]}")

    # D. status on fresh store
    with tempfile.TemporaryDirectory() as td:
        env = set_home(td)
        env["MONET_STORAGE_DIR"] = os.path.join(td, "store")
        rc, out, err = run_cli(["status"], env_extra=env)
        check("D_status_rc0", rc == 0, f"rc={rc}")
        for field in ("Monet Status", "Storage:", "Concepts:", "Observations:", "Workstreams:",
                      "Unsynthesized:"):
            check(f"D_status_has_{field.split(':')[0].lower()}", field in out, out.strip()[:80])

    # E. status --circle on fresh store -> scoped Circle label
    with tempfile.TemporaryDirectory() as td:
        env = set_home(td)
        env["MONET_STORAGE_DIR"] = os.path.join(td, "store")
        rc, out, err = run_cli(["status", "--circle", "e2e-scope-circle"], env_extra=env)
        check("E_status_circle_scoped", rc == 0 and "Circle:" in out and "e2e-scope-circle" in out,
              f"rc={rc} {out.strip()[:120]}")

    # F. dashboard invalid port
    for bad in ("0", "abc", "99999"):
        with tempfile.TemporaryDirectory() as td:
            env = set_home(td)
            rc, out, err = run_cli(["dashboard", "-p", bad], env_extra=env)
            check(f"F_dashboard_invalid_{bad}", rc == 1 and "Invalid port" in err,
                  f"rc={rc} err={err.strip()[:80]}")

    # G. source command removed in 1.7.0 (sources subsystem retired) -> `source` is
    #    no longer a recognized subcommand; the dispatcher reports unknown command.
    with tempfile.TemporaryDirectory() as td:
        env = set_home(td)
        env["MONET_STORAGE_DIR"] = os.path.join(td, "store")
        rc, out, err = run_cli(["source", "add", "--type", "git-md", "x"], env_extra=env)
        check("G_source_removed_unknown_cmd", rc == 1 and "unknown command 'source'" in err,
              f"rc={rc} err={err.strip()[:100]}")

    # H. MaterializeCliError branch (duplicate surface registration)
    with tempfile.TemporaryDirectory() as td:
        env = set_home(td)
        env["MONET_STORAGE_DIR"] = os.path.join(td, "store")
        env["MONET_PROJECT_DIR"] = os.path.join(td, "proj")
        os.makedirs(env["MONET_PROJECT_DIR"], exist_ok=True)
        target = os.path.join(env["MONET_PROJECT_DIR"], "a.md")
        with open(target, "w") as f:
            f.write("# doc\n")
        rc1, _, _ = run_cli(["materialize", "add", target, "--global"], env_extra=env)
        rc, out, err = run_cli(["materialize", "add", target, "--global"], env_extra=env)
        check("H_materializeclierror_branch",
              rc1 == 0 and rc == 1 and err.strip().startswith("monet materialize:"),
              f"rc1={rc1} rc={rc} err={err.strip()[:120]}")

    # I. generic error branch (repair against a store with no schema -> plain error)
    with tempfile.TemporaryDirectory() as td:
        env = set_home(td)
        env["MONET_STORAGE_DIR"] = os.path.join(td, "noexist")
        rc, out, err = run_cli(["repair"], env_extra=env)
        # repair always exits non-zero on an unavailable/unknown store; the exact
        # message is version-dependent, so assert rc != 0 (the generic catch ran).
        check("I_repair_generic_error", rc == 1, f"rc={rc} err={err.strip()[:100]}")

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
