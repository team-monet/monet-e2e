#!/usr/bin/env python3
"""RE-52 (upstream team-monet/monet#70): `monet install` crashes (raw JS
TypeError) instead of refusing cleanly on a malformed PostToolUse hooks section.

Reverse-engineering + E2E finding (verified 2026-08-23 on installed 1.7.1):
`validateSettingsShape` (install-cli.ts) checks ONLY `hooks.PreToolUse` and
returns `{ ok: true }` early when that key is absent. `PostToolUse` /
`PostToolUseFailure` — both managed by the installer — are never shape-checked;
their (possibly malformed) values are cast into `upsertHandlerForEvent`, whose
`for (const group of existing ?? []) { ... group.hooks.filter(...) }` throws an
unhandled TypeError. Two concrete crash shapes reproduced by seeding a settings
file with only a malformed PostToolUse (PreToolUse absent → validation skipped):

  - `hooks.PostToolUse = [{"matcher":"x","hooks":"not-an-array"}]`
      -> rc=1, stderr `i.filter is not a function`
  - `hooks.PostToolUse = {"matcher":".+","hooks":[]}` (object, not array)
      -> rc=1, stderr `(t ?? []) is not iterable`

The install refuses its own input just fine for PreToolUse / wrong-shape
(arms F/G in test37: "not valid JSON", "valid JSON but not a settings file");
PostToolUse and PostToolUseFailure get no equivalent guard.

Desired contract (asserted, XFAIL while present): a malformed PostToolUse
section must be REFUSED CLEANLY (rc=1 with a validation-oriented message naming
the offending field), NOT crash with an unhandled JS TypeError stack. This
mirrors the existing wrong-shape / malformed refusal arms.

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: bug still present (raw TypeError on malformed PostToolUse) — expected
  3   = XPASS: bug appears fixed (clean validation refusal)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import run_cli

ISSUE = "RE-52"
PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def run_install_with(hooks):
    """Seed a settings file with `hooks`, run `monet install`, return (rc, out, err)."""
    with tempfile.TemporaryDirectory() as td:
        home = os.path.join(td, "home")
        proj = os.path.join(td, "project")
        os.makedirs(home)
        os.makedirs(os.path.join(proj, ".claude"))
        sp = os.path.join(proj, ".claude", "settings.local.json")
        with open(sp, "w") as f:
            json.dump({"hooks": hooks}, f)
        env = {"HOME": home, "MONET_STORAGE_DIR": os.path.join(td, "store"),
               "MONET_CIRCLE": "e2e-re52"}
        rc, out, err = run_cli(["install", "--project", proj], env_extra=env)
        return rc, out, err


def main():
    # The two concrete malformed PostToolUse shapes from #70.
    cases = {
        "group_hooks_string": [{"matcher": "x", "hooks": "not-an-array"}],
        "PostToolUse_object": {"matcher": ".+", "hooks": []},
    }
    typerr_markers = ["is not a function", "is not iterable"]
    any_crash = False

    for name, bad in cases.items():
        rc, out, err = run_install_with({"PostToolUse": bad})
        combined = out + "\n" + err
        check(f"{name}_rc1", rc == 1, f"rc={rc}")
        crashed = any(m in combined for m in typerr_markers)
        if crashed:
            any_crash = True
        print(f"  [RE-52] case {name} -> rc={rc}, crash={crashed}, err_tail="
              f"{err.strip().splitlines()[-1][:120]!r}")
        # Desired contract: a clean validation refusal, NOT an unhandled TypeError.
        clean_refusal = (
            rc == 1
            and not crashed
            and ("hook" in err.lower() or "settings" in err.lower() or "valid" in err.lower())
        )
        check(f"{name}_clean_refusal", clean_refusal, f"crashed={crashed}")

    if FAIL:
        # All FAILs here are the `clean_refusal` assertions that only fail when an
        # unhandled TypeError leaks. If that shipped crash reproduced, this is the
        # expected bug state -> XFAIL(2). Anything else -> genuine setup breakage.
        if any_crash and len(FAIL) == len(cases):
            print(f"\nRESULT: XFAIL {ISSUE} — malformed PostToolUse crashes `monet install` "
                  f"with an unhandled TypeError ({len(PASS)} setup checks passed)")
            return 2
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    print(f"\nRESULT: XPASS {ISSUE} — malformed PostToolUse refused cleanly "
          f"(no unhandled TypeError)")
    return 3


if __name__ == "__main__":
    sys.exit(main())