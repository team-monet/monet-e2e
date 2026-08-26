#!/usr/bin/env python3
"""Scenario (CLI surface): `monet uninstall` — retired gate-hook removal (test37).

`monet install` (the Claude Code gate-hook installer, install-cli.ts) was
REMOVED in @team-monet/monet 1.9.0 — `monet gate` is now a RETIRED stub
("this hook no longer evaluates anything and is failing OPEN") and the only
hook-management command left is `monet uninstall`, which removes the retired
gate-hook entries from Claude Code settings (uninstall-cli.ts, the new surface
that replaced the installer's write path).

This drives `monet uninstall` through the process boundary and pins its on-disk
contract (mirror of the removed-test37 install arms, now on the removal side):
  - no-hook state -> clean rc=0 no-op ("no Monet hook entries found")
  - the scan-path message proves isolation (HOME/.monet/gate-hook.mjs AND the
    MONET_STORAGE_DIR gate-hook.mjs are both listed -> storage-path resolution
    is -d/env-honoured)
  - --dry-run is read-only (a settings.local.json with a gate-hook reference
    is left byte-identical)
  - a real run REMOVES the gate-hook handler from settings.local.json
  - `monet gate --help` documents the retired/fail-open contract + uninstall hint

Isolation (GR-01): HOME + MONET_STORAGE_DIR + MONET_CIRCLE redirected to temp
dirs; no prod path touched, no embedder loaded (pure file/CLI command).

Exit codes: 0 = PASS, 1 = FAIL (unexpected). No XFAIL (no tracked bug here —
this is the adapted surface-baseline for the removed installer).
"""
import json
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
    # Assert `monet install` is genuinely gone (the premise of the adaptation):
    probe = run_cli(["install"], env_extra={"HOME": "/tmp/x", "MONET_STORAGE_DIR": "/tmp/y"})
    gone = probe[0] == 1 and ("unknown command" in (probe[1] + probe[2]) or
                              "Did you mean uninstall" in (probe[1] + probe[2]))
    check("install_command_removed", gone, f"rc={probe[0]} msg={(probe[1]+probe[2]).strip()[-60:]!r}")

    # ---- no-hook state: clean no-op ----
    with tempfile.TemporaryDirectory() as td:
        home = os.path.join(td, "home")
        store = os.path.join(td, "store")
        os.makedirs(home)
        os.makedirs(store)
        env = {"HOME": home, "MONET_STORAGE_DIR": store, "MONET_CIRCLE": "e2e-uninstall"}
        # U1. real run with no hook -> rc 0, "nothing to remove".
        rc, out, err = run_cli(["uninstall"], env_extra=env)
        text = out + "\n" + err
        check("U_no_hook_rc0", rc == 0, f"rc={rc}")
        check("U_no_hook_noop", "no Monet hook entries found" in text or "nothing to remove" in text,
              f"msg={text.strip()[-70:]!r}")
        # U2. the scan-path message lists BOTH the HOME wrapper AND the storage-dir wrapper
        #     (storage-path resolution honours MONET_STORAGE_DIR / -d, not a hardcoded ~/.monet).
        check("U_scan_lists_home_wrapper",
              os.path.join(home, ".monet", "gate-hook.mjs") in text,
              "home wrapper listed")
        check("U_scan_lists_storage_wrapper",
              os.path.join(store, "gate-hook.mjs") in text,
              "storage-dir wrapper listed")

        # ---- --dry-run read-only: a real hook reference is NOT removed ----
        settings_dir = os.path.join(home, ".claude")
        os.makedirs(settings_dir)
        sp = os.path.join(settings_dir, "settings.json")
        wrapper = os.path.join(store, "gate-hook.mjs")
        seeded = {
            "hooks": {
                "PostToolUse": [{"matcher": "^Bash$", "hooks": [
                    {"type": "command", "command": "node", "args": [wrapper, "--circle", "e2e-uninstall"]}]}]
            }
        }
        with open(sp, "w") as f:
            json.dump(seeded, f)
        before = open(sp, "rb").read()
        rc, out, err = run_cli(["uninstall", "--dry-run"], env_extra=env)
        check("U_dry_run_rc0", rc == 0, f"rc={rc}")
        after = open(sp, "rb").read()
        check("U_dry_run_read_only", after == before, "settings byte-identical")

        # ---- real run removes the gate-hook handler ----
        rc, out, err = run_cli(["uninstall"], env_extra=env)
        check("U_real_rc0", rc == 0, f"rc={rc}")
        data = json.load(open(sp))
        still_refs = wrapper in json.dumps(data)
        check("U_real_removes_hook", not still_refs, f"settings={json.dumps(data)[:90]!r}")

    # ---- retired gate stub is documented + fail-open ----
    # Note: the gate notice is shown ONCE (stateful marker in the storage dir), so
    # use a FRESH storage dir here — a reused dir whose once-marker is already set
    # returns SILENCE (that is the stub's own persisted state, not a failure).
    with tempfile.TemporaryDirectory() as gtd:
        rc, out, err = run_cli(["gate"], env_extra={"HOME": os.path.join(gtd, "home"),
                                                    "MONET_STORAGE_DIR": os.path.join(gtd, "store")})
        text = out + "\n" + err
        check("G_retired_rc0", rc == 0, f"rc={rc}")
        check("G_retired_notice", "retired" in text.lower() and "uninstall" in text,
              f"msg={text.strip()[-90:]!r}")

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
        return 1
    print(f"\nRESULT: PASS — `monet uninstall` surface green; install removed, gate retired-stub "
          f"contract pinned ({len(PASS)} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())