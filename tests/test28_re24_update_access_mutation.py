#!/usr/bin/env python3
"""RE-24 (sources-sync.md): `source update` can silently de-authorize the host.

Reverse-engineering finding: `updateSource` marks the identity fields
(id/type/repositoryIdentity/remoteUrl/localPath/branch/circle) immutable, but
the `access` policy (`allowedCallerIds` / `allowedProjectIds`) is MUTABLE. The
CLI `source update` exposes this via repeatable `--allow-caller` /
`--allow-project` flags (each REPLACES its list). So a host can mutate a
source's access list and silently de-authorize the very caller id that
registered/syncs it — the source then vanishes from `source_list` and every
`source_*` call fails with the non-disclosing "source is unavailable", with
no warning at edit time.

This test documents the DESIRED contract: an access edit that removes the
acting caller's own authorization must NOT be silent — `source update` should
either refuse the edit, emit a warning, or leave the source visible to the
acting caller (prevent self-de-authorization).

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: update succeeds silently AND the source vanishes (bug present)
  3   = XPASS: update refused/warned, or the source stays visible (bug fixed)
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

ISSUE = "RE-24"
CLI = os.environ.get("MONET_CLI") or "/Users/codalee/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js"
NODE = os.environ.get("MONET_NODE_PATH") or "/opt/homebrew/opt/node@22/bin"
CALLER = "e2e-caller"
PROJECT = "e2e-project"
ATTACKER = "e2e-attacker"
REAL_HOME = os.path.expanduser("~")

# See test25: the HOME redirect (source-storage isolation, RE-29) moves the
# model cache into the empty fake home, forcing a ~550 MB re-download. Point it
# back at the real cache so the model is reused read-only and the server never
# re-downloads (hardens against full-disk ENOSPC).
REAL_MODEL_CACHE = os.path.join(REAL_HOME, ".monet", "models")
os.environ["MONET_MODEL_CACHE"] = REAL_MODEL_CACHE

os.environ["MONET_CLI"] = CLI
os.environ["MONET_NODE_PATH"] = NODE

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def env_for(home, caller=CALLER, project=PROJECT):
    e = dict(os.environ)
    e["PATH"] = NODE + ":" + e.get("PATH", "")
    e["HOME"] = home
    e["MONET_CALLER_ID"] = caller
    e["MONET_PROJECT_ID"] = project
    return e


def main():
    # Sources subsystem removed in @team-monet/monet 1.7.0 (`source` subcommand +
    # MCP source_* tools gone) -> RE-24 obsolete-by-removal; SKIP instead of failing.
    import subprocess as _sp
    _p = _sp.run([CLI, "source"], capture_output=True, text=True, env=env_for(os.path.expanduser("~")))
    if _p.returncode == 1 and "unknown command" in (_p.stderr or ""):
        print("  SKIP: the `source` CLI subcommand was removed in 1.7.0 " +
              "(sources subsystem retired) — RE-24 obsolete-by-removal.")
        print("\nRESULT: 0 passed, 0 failed (SKIP)")
        return 0

    base = tempfile.mkdtemp(prefix="monet-re24-e2e-")
    repo = os.path.join(base, "repo")
    store = os.path.join(base, "store")
    fakehome = os.path.join(base, "home")
    for d in (repo, store, fakehome):
        os.makedirs(d)

    os.environ["MONET_CLI"] = CLI
    os.environ["MONET_NODE_PATH"] = NODE
    os.environ["HOME"] = fakehome

    def run(args, cwd=None, caller=CALLER, project=PROJECT):
        e = env_for(fakehome, caller, project)
        return subprocess.run(args, cwd=cwd, env=e, capture_output=True, text=True)

    src_id = None
    bug_fixed = False
    try:
        # ---- setup: a real git worktree of Markdown + a registered source ----
        with open(os.path.join(repo, "a.md"), "w") as f:
            f.write("# RE-24 probe\n\nAccess mutation footgun test document.\n")
        run(["git", "init", "-q"], cwd=repo)
        run(["git", "add", "-A"], cwd=repo)
        run(["git", "-c", "user.email=e2e@test.local", "-c", "user.name=E2E",
             "commit", "-qm", "init"], cwd=repo)

        r = run([CLI, "source", "add", "--type", "repo-md", "--path", repo,
                 "--circle", "e2e-src", "--refresh", "manual",
                 "--allow-caller", CALLER, "--allow-project", PROJECT,
                 "-d", store, "e2e-src"])
        check("source_registered", "Registered source" in (r.stdout or "") and "repo-md" in (r.stdout or ""),
              f"rc={r.returncode} out={r.stdout.strip()[:80]!r}")

        out = subprocess.run(["sqlite3", os.path.join(store, "monet.db"),
                              "SELECT id FROM knowledge_sources LIMIT 1;"],
                             capture_output=True, text=True)
        src_id = out.stdout.strip()
        check("source_id_from_db", bool(src_id), f"id={src_id}")

        # ---- control: with the correct identity, source_list sees the source ----
        os.environ["MONET_CALLER_ID"] = CALLER
        os.environ["MONET_PROJECT_ID"] = PROJECT
        c = MonetClient(store)
        try:
            c.initialize()
            r = c.call_json("source_list", {})
            sources = r.get("sources") or []
            check("control_source_list_with_identity_returns_one",
                  len(sources) == 1 and sources[0].get("type") == "repo-md",
                  f"sources={sources}")
        finally:
            c.close()

        # ---- bug probe: mutate access to remove the acting caller ----
        up = run([CLI, "source", "update", src_id, "--allow-caller", ATTACKER,
                  "-d", store])
        up_out = (up.stdout or "") + (up.stderr or "")
        print(f"  [RE-24] source update rc={up.returncode} out={up_out.strip()[:200]!r}")

        # Prove the mutation actually landed (allowed_caller_ids now excludes CALLER).
        row = subprocess.run(
            ["sqlite3", os.path.join(store, "monet.db"),
             "SELECT allowed_caller_ids_json FROM knowledge_sources LIMIT 1;"],
            capture_output=True, text=True).stdout.strip()
        access_mutated = (CALLER not in row) and (ATTACKER in row)
        check("access_mutated_in_db", access_mutated, f"allowed_caller_ids={row}")

        # Did the edit warn or refuse? (desired: not silent)
        update_warned_or_refused = (up.returncode != 0) or bool(
            re.search(r"warn|refus|denied|forbid|error|invalid|not allowed", up_out.lower())
        )

        # After the edit, is the source still visible to the ACTING caller?
        os.environ["MONET_CALLER_ID"] = CALLER
        os.environ["MONET_PROJECT_ID"] = PROJECT
        c2 = MonetClient(store)
        try:
            c2.initialize()
            r = c2.call_json("source_list", {})
            sources = r.get("sources")
            raw = r.get("_rawText", "")
            print(f"  [RE-24] source_list (acting caller after edit) -> "
                  f"sources={sources!r} raw={raw[:120]!r}")
            source_still_visible = isinstance(sources, list) and len(sources) == 1
        finally:
            c2.close()

        # DESIRED contract: not silent self-de-authorization.
        bug_fixed = update_warned_or_refused or source_still_visible
        print(f"  [RE-24] update_warned_or_refused={update_warned_or_refused} "
              f"source_still_visible={source_still_visible} bug_fixed={bug_fixed}")

        # ---- isolation check: HOME redirect kept source storage off prod ----
        real_sources = os.path.join(REAL_HOME, ".monet", "sources")
        fake_sources = os.path.join(fakehome, ".monet", "sources")
        check("source_storage_isolated_via_home",
              not os.path.isdir(real_sources),
              f"real(~/.monet/sources)={os.path.isdir(real_sources)}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if bug_fixed:
        print(f"\nRESULT: XPASS {ISSUE} — source update warns/refuses or leaves the source visible (bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — source update silently de-authorizes the acting caller "
          f"({len(PASS)} setup checks passed)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
