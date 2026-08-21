#!/usr/bin/env python3
"""RE-23 (sources-sync.md): source surface silently hides sources when the
server starts with a fallback identity.

REFINEMENT OF RE-23 (measured against installed 1.6.1, 2026-08-14):

The run-19 reverse-engineering read only `dist/index.js` (the core). It
recorded RE-23 as "the 4 source tools are hard-gated on MONET_CALLER_ID +
MONET_PROJECT_ID; with them unset the tools fail with an opaque 'trusted
source authorization context is unavailable'". That is NOT what the installed
1.6.1 does, because the CLI `start` command pre-populates the identity BEFORE
the server reads it:

    process.env.MONET_CALLER_ID  = yb();   // deriveCallerId -> env || "local-agent"
    process.env.MONET_PROJECT_ID = vb(t);  // deriveProjectId -> env || git-origin || "<basename>-<sha8>"

so `deriveOptsFromEnv` (core `J4`) always sees BOTH vars and always builds a
`sourceAuthorizationContext`. The "context unavailable" throw is unreachable
via `monet start`. The real, observable behavior with the env vars unset is:

  - source_list   -> { "sources": [] }   (SILENT empty — the registered source
                                           is filtered out by authorizeSource
                                           and the caller is given no signal
                                           that anything is hidden)
  - source_status / source_path / source_sync -> "source is unavailable"
                                           (non-disclosing by design: denied
                                           and removed ids share one message)

The residual bug (this test's contract): a caller who registers a source under
a specific caller id but forgets to export MONET_CALLER_ID/MONET_PROJECT_ID
before `monet start` gets a SILENT empty list from source_list, with no hint
that the source exists but is identity-hidden. The DESIRED contract is that the
identity mismatch be DISCOVERABLE: source_list must either surface the source
with an authorization flag, or return an error/warning naming the identity
cause — not a bare `[]`.

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: source_list silently returns [] (bug present) — expected
  3   = XPASS: source_list returns a discoverable result (bug appears fixed)
"""
import os
import shutil
import subprocess
import sys
import tempfile

ISSUE = "RE-23"
CLI = os.environ.get("MONET_CLI") or "/Users/codalee/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js"
NODE = os.environ.get("MONET_NODE_PATH") or "/opt/homebrew/opt/node@22/bin"
CALLER = "e2e-caller"
PROJECT = "e2e-project"
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


def env_for(home):
    e = dict(os.environ)
    e["PATH"] = NODE + ":" + e.get("PATH", "")
    e["HOME"] = home
    e["MONET_CALLER_ID"] = CALLER
    e["MONET_PROJECT_ID"] = PROJECT
    return e


def main():
    # Sources subsystem removed in @team-monet/monet 1.7.0 (`source` subcommand +
    # MCP source_* tools gone) -> RE-23 obsolete-by-removal; SKIP instead of failing.
    import subprocess as _sp
    _p = _sp.run([CLI, "source"], capture_output=True, text=True, env=env_for(os.path.expanduser("~")))
    if _p.returncode == 1 and "unknown command" in (_p.stderr or ""):
        print("  SKIP: the `source` CLI subcommand was removed in 1.7.0 " +
              "(sources subsystem retired) — RE-23 obsolete-by-removal.")
        print("\nRESULT: 0 passed, 0 failed (SKIP)")
        return 0

    base = tempfile.mkdtemp(prefix="monet-re23-e2e-")
    repo = os.path.join(base, "repo")
    store = os.path.join(base, "store")
    fakehome = os.path.join(base, "home")
    for d in (repo, store, fakehome):
        os.makedirs(d)

    # Process env so MonetClient (which passes os.environ through) also gets
    # the HOME redirect + CLI/node resolution.
    os.environ["MONET_CLI"] = CLI
    os.environ["MONET_NODE_PATH"] = NODE
    os.environ["HOME"] = fakehome

    def run(args, cwd=None, identity=True):
        e = env_for(fakehome) if identity else dict(os.environ)
        e["PATH"] = NODE + ":" + e.get("PATH", "")
        return subprocess.run(args, cwd=cwd, env=e, capture_output=True, text=True)

    src_id = None
    bug_fixed = False
    try:
        # ---- setup: a real git worktree of Markdown + a registered source ----
        with open(os.path.join(repo, "a.md"), "w") as f:
            f.write("# RE-23 probe\n\nIdentity discoverability test document.\n")
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

        # ---- control: WITH the correct identity, source_list sees the source ----
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

        # ---- bug probe: WITHOUT identity, the server falls back to local-agent ----
        os.environ.pop("MONET_CALLER_ID", None)
        os.environ.pop("MONET_PROJECT_ID", None)
        c2 = MonetClient(store)
        try:
            c2.initialize()
            r = c2.call_json("source_list", {})
            sources = r.get("sources")
            raw = r.get("_rawText", "")
            print(f"  [RE-23] source_list (fallback identity) -> sources={sources!r} raw={raw[:120]!r}")

            # Supplementary observation (by-design, not asserted): the other
            # three tools return the non-disclosing "source is unavailable".
            try:
                st = c2.call_json("source_status", {"sourceId": src_id})
                print(f"  [RE-23] source_status (fallback identity) -> {st!r}"[:160])
            except RuntimeError as e:
                print(f"  [RE-23] source_status (fallback identity) -> RuntimeError {str(e)[:120]!r}")

            # DESIRED contract: the mismatch is discoverable — NOT a bare [].
            discoverable = bool((raw or "").strip()) or (isinstance(sources, list) and len(sources) > 0)
            bug_fixed = discoverable
        finally:
            c2.close()

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
        print(f"\nRESULT: XPASS {ISSUE} — source_list surfaces the identity mismatch (bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — source_list silently returns [] under a fallback identity "
          f"({len(PASS)} setup checks passed)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
