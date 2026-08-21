#!/usr/bin/env python3
"""RE-30 (sources-sync.md): repo-md `source_sync` fails on macOS with EACCES.

First E2E exercise of the sources/sync subsystem. Registers a repo-md source
(a local git worktree of Markdown) in an ISOLATED store, then drives
`source_list` / `source_status` / `source_sync` / `source_path` over MCP.

Reverse-engineering finding (v1.6.1, readable TS source):
`source-materializer.ts` `sealSnapshot()` chmods the staged snapshot tree to
`0o500` (read-only, no write bits) before `renameSync(tree, snapshotPath)`
publishes it. The code even stages `tree` "beside the final variant" because
"macOS refuses to move a non-writable directory between parents"
(source-materializer.ts:2225-2226). On macOS 15.x that mitigation is
INSUFFICIENT: APFS still refuses the in-place (same-parent) rename of a
`0o500` directory, returning `EACCES: permission denied, rename '...' -> '...'`.
The whole `source_sync` feature therefore fails hard on macOS.

This test documents the DESIRED contract: `source_sync` should publish a
snapshot (filesIndexed > 0, freshness leaves 'unknown', `source_path` returns a
real sealed path). It also records a second, related finding (RE-29): the
sourceStorageDir defaults to `~/.monet/sources` via `homedir()` and is NOT
scoped by `-d`; the harness isolates it here by redirecting HOME to a temp dir.

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: source_sync still fails with EACCES (bug present) — expected
  3   = XPASS: source_sync published a snapshot (bug appears fixed)
"""
import os
import shutil
import subprocess
import sys
import tempfile

ISSUE = "RE-30"
CLI = os.environ.get("MONET_CLI") or "/Users/codalee/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js"
NODE = os.environ.get("MONET_NODE_PATH") or "/opt/homebrew/opt/node@22/bin"
CALLER = "e2e-caller"
PROJECT = "e2e-project"

# Real home, captured before any HOME override so the isolation check can tell
# the redirect actually worked (see the source_storage_isolated_via_home check).
REAL_HOME = os.path.expanduser("~")

# The HOME redirect below (to isolate source storage, RE-29) also moves the
# embedder model cache (~/.monet/models) into the fake home, which is empty, so
# the server re-downloads the ~550 MB bge-m3 model every run. Point the cache
# back at the REAL location so the cached model is reused (read-only) and the
# server never re-downloads — this also hardens the test against a full disk
# (ENOSPC on model download was observed failing these tests on 2026-08-16).
REAL_MODEL_CACHE = os.path.join(REAL_HOME, ".monet", "models")
os.environ["MONET_MODEL_CACHE"] = REAL_MODEL_CACHE

# mcp_client resolves MONET_CLI / MONET_NODE_PATH at import time, so they must
# be set in the environment BEFORE the import below.
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


def env_for(home):
    e = dict(os.environ)
    e["PATH"] = NODE + ":" + e.get("PATH", "")
    e["HOME"] = home
    e["MONET_CALLER_ID"] = CALLER
    e["MONET_PROJECT_ID"] = PROJECT
    return e


def main():
    # The sources subsystem was REMOVED in @team-monet/monet 1.7.0 (the `source`
    # CLI subcommand and all MCP source_* tools are gone). The RE-29/RE-30 bugs
    # this test verifies are now obsolete-by-removal, so when the binary has no
    # `source` subcommand we SKIP (exit 0) instead of failing setup.
    import subprocess as _sp
    _p = _sp.run([CLI, "source"], capture_output=True, text=True, env=env_for(os.path.expanduser("~")))
    if _p.returncode == 1 and "unknown command" in (_p.stderr or ""):
        print("  SKIP: the `source` CLI subcommand was removed in 1.7.0 " +
              "(sources subsystem retired) — RE-29/RE-30 obsolete-by-removal.")
        print("\nRESULT: 0 passed, 0 failed (SKIP)")
        return 0

    base = tempfile.mkdtemp(prefix="monet-src-e2e-")
    repo = os.path.join(base, "repo")
    store = os.path.join(base, "store")
    fakehome = os.path.join(base, "home")
    os.makedirs(repo)
    os.makedirs(fakehome)

    # Set process env so MonetClient (which passes os.environ through) also
    # gets the HOME redirect + server identity + CLI/node resolution.
    os.environ["MONET_CLI"] = CLI
    os.environ["MONET_NODE_PATH"] = NODE
    os.environ["MONET_CALLER_ID"] = CALLER
    os.environ["MONET_PROJECT_ID"] = PROJECT
    os.environ["HOME"] = fakehome

    bug_fixed = False
    src_id = None
    try:
        # ---- setup: a real git worktree of Markdown ----
        for name, body in {
            "guide.md": "# Monet Source E2E Guide\n\nTest document.\n\n## Getting started\n\nRegister a source.\n\n## Chunking\n\nHeadings chunk content.\n",
            "reference.md": "# Monet Reference\n\nReference material.\n\n## Access policy\n\nCallers and projects.\n",
        }.items():
            with open(os.path.join(repo, name), "w") as f:
                f.write(body)

        def run(args, cwd=None):
            return subprocess.run(args, cwd=cwd, env=env_for(fakehome), capture_output=True, text=True)

        run(["git", "init", "-q"], cwd=repo)
        run(["git", "add", "-A"], cwd=repo)
        run(["git", "-c", "user.email=e2e@test.local", "-c", "user.name=E2E", "commit", "-qm", "init"], cwd=repo)
        head = run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
        check("git_worktree_ready", bool(head) and len(head) == 40, f"head={head[:12]}")

        # ---- register a repo-md source (isolated store, server identity) ----
        r = run([CLI, "source", "add", "--type", "repo-md", "--path", repo,
                 "--circle", "e2e-src", "--refresh", "manual",
                 "--allow-caller", CALLER, "--allow-project", PROJECT,
                 "-d", store, "e2e-src"])
        check("source_registered", "Registered source" in (r.stdout or "") and "repo-md" in (r.stdout or ""),
              f"rc={r.returncode} out={r.stdout.strip()[:80]!r} err={r.stderr.strip()[:80]!r}")

        out = run(["sqlite3", os.path.join(store, "monet.db"), "SELECT id FROM knowledge_sources LIMIT 1;"])
        src_id = out.stdout.strip()
        check("source_id_from_db", bool(src_id), f"id={src_id}")

        # ---- MCP: the sources surface ----
        c = MonetClient(store)
        try:
            c.initialize()

            r = c.call_json("source_list", {})
            sources = r.get("sources") or []
            check("source_list_returns_one", len(sources) == 1 and sources[0].get("type") == "repo-md"
                  and sources[0].get("name") == "e2e-src", f"sources={sources}")

            # ---- THE bug assertion: sync should publish a snapshot ----
            sync = c.call_json("source_sync", {"sourceId": src_id}, timeout=180)
            raw = sync.get("_rawText", "")
            sync_failed = "failed" in raw or bool(raw)
            print(f"  [RE-30] source_sync -> {raw[:140]!r}")

            status = c.call_json("source_status", {"sourceId": src_id})
            files = status.get("filesIndexed", 0)
            fresh = status.get("freshness")
            print(f"  [RE-30] source_status -> filesIndexed={files} freshness={fresh} lastError={status.get('lastError')!r}")

            path = c.call_json("source_path", {"sourceId": src_id})
            path_raw = path.get("_rawText", "")
            has_snapshot = "_rawText" not in path or "no published snapshot" not in path_raw
            print(f"  [RE-30] source_path -> {json_safe(path)}")

            bug_fixed = (not sync_failed) and files > 0 and has_snapshot

            # ---- RE-29 documentation check: HOME redirect isolated source storage ----
            real_sources = os.path.join(REAL_HOME, ".monet", "sources")
            fake_sources = os.path.join(fakehome, ".monet", "sources")
            check("source_storage_isolated_via_home", os.path.isdir(fake_sources) and not os.path.isdir(real_sources),
                  f"fake={os.path.isdir(fake_sources)} real(~/.monet/sources)={os.path.isdir(real_sources)}")
        finally:
            c.close()
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if bug_fixed:
        print(f"\nRESULT: XPASS {ISSUE} — source_sync published a snapshot (bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — source_sync still fails with EACCES on macOS "
          f"({len(PASS)} setup checks passed)")
    return 2


def json_safe(obj):
    import json
    return json.dumps(obj, ensure_ascii=False)[:120]


if __name__ == "__main__":
    sys.exit(main())
