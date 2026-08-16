#!/usr/bin/env python3
"""RE-44 (materialize-cli.md): `monet materialize` renders a dirty skeleton body.

Reverse-engineering finding (readable TS `materialize-cli.ts` + `engine.ts`,
core 0.9.0, upstream issue #23): `skeletonMemberRows` selects `c.body` with a
filter on `status='active'` + latest `verdict IN ('approve','re-ratify')` but
has NO `dirty`/`needsSynthesis` guard. So a principle amended via
`memory_declare` (re-declare with near-identical content → ATTACH → dirty →
`body` becomes the unreconciled concatenation of the old and new paragraphs)
is materialized VERBATIM as governing text, and `mirrorStale` reports green on
the same turn because the block hash faithfully matches the store's
`canonicalSkeletonState` (which is computed from that same dirty body). A
standing surface emits a verdict ("mirror current") where it holds a
not-known ("mirror matches a body nobody reconciled").

This test documents the DESIRED contract: a dirty (needsSynthesis) skeleton
member must not be emitted as governing text — `materialize` must either
refuse (naming the concept and what to run), or render only a reconciled
body. Either way, the unreconciled old+new concatenation must NOT reach the
standing file.

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: materialize still renders the dirty concatenation as governing text
  3   = XPASS: materialize refuses or renders only a reconciled body (bug appears fixed)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient

ISSUE = "RE-44"
CLI = os.environ.get("MONET_CLI") or "/Users/codalee/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js"
NODE = os.environ.get("MONET_NODE_PATH") or "/opt/homebrew/opt/node@22/bin"

os.environ["MONET_CLI"] = CLI
os.environ["MONET_NODE_PATH"] = NODE

PASS = []
FAIL = []

# Near-identical so the re-declaration ATTACHES (score >= tauAttach) rather than
# forks; the two markers make the unreconciled concatenation unambiguously
# detectable (each appears in exactly one of the two paragraphs).
OLD_MARKER = "primary region"
NEW_MARKER = "secondary region"
OLD = f"Before migrating, always back up the production database to the {OLD_MARKER}."
NEW = f"Before migrating, always back up the production database to the {NEW_MARKER}."


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def run_cli(args, store, base):
    env = dict(os.environ)
    env["PATH"] = NODE + ":" + env.get("PATH", "")
    env["MONET_STORAGE_DIR"] = store
    env["MONET_PROJECT_DIR"] = base
    env["MONET_MODEL_CACHE"] = os.path.expanduser("~/.monet/models")
    p = subprocess.run([CLI] + args, capture_output=True, text=True, env=env, timeout=120)
    return p


def main():
    base = tempfile.mkdtemp(prefix="monet-re44-e2e-")
    store = os.path.join(base, "store")
    os.makedirs(store)
    surface = os.path.join(base, "AGENTS.md")
    circle = "re44"

    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")

    bug_fixed = False
    try:
        # ---- setup: declare a principle, then amend it (re-declare -> attach) ----
        c = MonetClient(store)
        try:
            c.initialize()
            r1 = c.call_json("memory_declare", {
                "species": "principle", "circle": circle, "content": OLD,
                "exitsEvidence": "a migration ran with no backup",
                "sourceRefs": ["e2e:test34"]})
            cid = r1.get("conceptId")
            check("declare_created", r1.get("action") == "created" and bool(cid), f"id={cid}")

            r2 = c.call_json("memory_declare", {
                "species": "principle", "circle": circle, "content": NEW,
                "exitsEvidence": "a migration ran with no backup",
                "sourceRefs": ["e2e:test34"]})
            check("amend_attached_same_concept", r2.get("action") == "attached" and r2.get("conceptId") == cid,
                  f"action={r2.get('action')} id={r2.get('conceptId')}")

            f = c.call_json("memory_fetch", {"id": cid, "observations": True})
            check("dirty_needsSynthesis", f.get("needsSynthesis") is True, f"needsSynthesis={f.get('needsSynthesis')}")
            check("two_observations", f.get("observationCount") == 2, f"obs={f.get('observationCount')}")
            body = f.get("body") or ""
            check("body_is_concatenation", OLD_MARKER in body and NEW_MARKER in body,
                  f"body has both markers (unreconciled)")
        finally:
            c.close()

        # ---- materialize the dirty skeleton to a standing surface ----
        p_add = run_cli(["materialize", "add", surface, "--circle", circle], store, base)
        check("add_registered", p_add.returncode == 0, f"rc={p_add.returncode} {p_add.stderr.strip()[-120:]}")

        p_mat = run_cli(["materialize"], store, base)
        # NB: rc of `materialize` is NOT itself the bug signal — a future fix may
        # legitimately refuse here (rc != 0) and that is the DESIRED behavior.
        print(f"  [RE-44] materialize rc={p_mat.returncode}")

        surface_text = ""
        if os.path.exists(surface):
            surface_text = open(surface, encoding="utf-8").read()

        # DESIRED contract: the unreconciled concatenation must not be emitted.
        old_present = OLD_MARKER in surface_text
        new_present = NEW_MARKER in surface_text
        dirty_leaked = old_present and new_present
        bug_fixed = not dirty_leaked
        print(f"  [RE-44] surface_has_old={old_present} surface_has_new={new_present} "
              f"dirty_leaked={dirty_leaked}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if bug_fixed:
        print(f"\nRESULT: XPASS {ISSUE} — materialize no longer emits the dirty concatenation (bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — materialize still renders the dirty/unsynthesized body as governing text "
          f"({len(PASS)} setup checks passed)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
