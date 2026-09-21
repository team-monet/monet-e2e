#!/usr/bin/env python3
"""RE-62 guard — the undocumented project `.monet` rung is neither disclosed nor
operable from below the project root.

Upstream issue: team-monet/monet#162. Monet resolves the store through
`MONET_STORAGE_DIR` -> `<projectDir>/.monet` (only if it EXISTS) -> `$HOME/.monet`,
where `projectDir` is resolved EXACTLY (no upward search). Two user-visible harms
follow, both measured on the LIVE `monet` path (1.11.0, run 125/126):

  H1 OPERATOR BLIND SPOT — an agent host that declares its project (MONET_PROJECT_DIR
     / CLAUDE_PROJECT_DIR) records into `<project>/.monet`, and a bare `monet` call
     from the project ROOT finds it, but the same bare call from `<project>/sub`
     silently resolves `$HOME/.monet` instead: the records look lost.
  H2 SILENT FLIP — a single documented `monet start -d <project>/.monet` (the only
     way a user creates that directory) permanently changes which store every
     LATER bare `monet` call in that project serves, with no warning. A record
     stored from that directory seconds earlier becomes unreachable from the same
     directory.

This guard asserts the DESIRED behaviour (records reachable from anywhere inside the
project; a record does not become unreachable from the same cwd because a `.monet`
directory appeared). It exits 2 (XFAIL) while the behaviour is broken and 3 (XPASS)
once a release fixes it; the repro assertions must hold or the guard exits 1 (FAIL)
so a broken probe can never masquerade as a known bug.

Scope note (honest re-baseline rule): the asserted property is OPERABILITY, not the
wording of any disclosure. If upstream decides RE-62 is documentation-only and keeps
the rung, this guard stays XFAIL by design — re-baseline it explicitly and record the
decision (same treatment as the #155 strikethrough precedent), never silently delete
the assertions.

Isolation: throwaway sandbox (temp HOME + projects), real model cache read-only.
Exit: 0/1 FAIL-ish, 2 XFAIL (bug present), 3 XPASS (fixed).
"""

import contextlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "harness"))
from mcp_client import CLI, MonetClient, run_cli  # noqa: E402

REAL_HOME = os.path.expanduser("~")
REAL_MODEL_CACHE = os.path.join(REAL_HOME, ".monet", "models")
CLEARED = (
    "MONET_STORAGE_DIR", "MONET_PROJECT_DIR", "CLAUDE_PROJECT_DIR",
    "MONET_CIRCLE", "MONET_CALLER_ID", "MONET_PROJECT_ID", "MONET_AGENT_ID",
)
KEEP = bool(os.environ.get("MONET_KEEP_STORE"))

REPRO = []
DESIRED = []
SANDBOXES = []


def repro(name, cond, detail=None):
    REPRO.append((name, bool(cond), detail))
    print("  [REPRO %s] %s%s" % ("ok" if cond else "BROKEN", name,
                                 "" if detail is None else " :: %s" % (detail,)))


def desired(name, cond, detail=None):
    DESIRED.append((name, bool(cond), detail))
    print("  [DESIRED %s] %s%s" % ("met" if cond else "unmet", name,
                                   "" if detail is None else " :: %s" % (detail,)))


def real(p):
    return os.path.realpath(p) if p else None


@contextlib.contextmanager
def process_env(env):
    old = os.environ.copy()
    os.environ.clear()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)


@contextlib.contextmanager
def chdir(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def sandbox(tag, projects=(("projA", True), ("projB", True), ("projF", False))):
    root = tempfile.mkdtemp(prefix="re62-%s-" % tag)
    sbx = {"root": root, "home": os.path.join(root, "home")}
    os.makedirs(os.path.join(sbx["home"], ".monet"), exist_ok=True)
    for name, with_monet in projects:
        d = os.path.join(root, name)
        os.makedirs(d, exist_ok=True)
        sbx[name] = d
        if with_monet:
            os.makedirs(os.path.join(d, ".monet"), exist_ok=True)
    SANDBOXES.append(root)
    return sbx


def arm_env(sbx, over=None):
    env = dict(os.environ)
    for key in CLEARED:
        env.pop(key, None)
    env["HOME"] = sbx["home"]
    env.pop("USERPROFILE", None)
    env["MONET_MODEL_CACHE"] = REAL_MODEL_CACHE
    if over:
        env.update(over)
    return env


STORE_RE = re.compile(r"^store:\s+(\S.*?)\s*$", re.M)
STATUS_RE = re.compile(r"^Storage:\s+(\S.*?)\s*$", re.M)
CONCEPTS_RE = re.compile(r"^Concepts:\s+(\d+)\s*$", re.M)


def bare_status(cwd, env):
    """`monet status` with NO -d at an explicit cwd AND an explicit environment.

    GR-01 note: the env MUST be passed and applied — an unwrapped call inherits the
    real environment and resolves (and OPENS) the PROD store. That happened once on
    this guard's first run; `sandboxed()` below now turns any recurrence into a loud
    failure instead of a silent prod read.
    """
    with process_env(env):
        rc, out, err = run_cli(["status"], cwd=cwd, timeout=180)
    m = STORE_RE.search(err)
    n = CONCEPTS_RE.search(out)
    return {"rc": rc,
            "stdout": STATUS_RE.search(out).group(1) if STATUS_RE.search(out) else None,
            "stderr": m.group(1) if m else None,
            "concepts": int(n.group(1)) if n else None}


def sandboxed(path, sbx, where):
    """GR-01 hard guard: a resolved store must live inside the throwaway sandbox."""
    if not path:
        return None
    rp, rr = real(path), real(sbx["root"])
    if rp != rr and not rp.startswith(rr.rstrip(os.sep) + os.sep):
        raise RuntimeError("GR-01: %s resolved OUTSIDE the sandbox: %s (sandbox=%s)"
                           % (where, rp, rr))
    return rp


def sb_status(sbx, cwd, env, where):
    """bare_status + GR-01 hard guard on BOTH reported paths."""
    st = bare_status(cwd, env)
    sandboxed(st["stdout"], sbx, where + " (stdout)")
    sandboxed(st["stderr"], sbx, where + " (stderr)")
    return st


def bare_server(cwd, env):
    """Bare `monet start` (no -d) at an explicit cwd; returns the live client."""
    ctx = contextlib.ExitStack()
    ctx.enter_context(process_env(env))
    ctx.enter_context(chdir(cwd))
    c = MonetClient(None)
    ctx.callback(c.close)
    c.initialize()
    store = None
    for line in c.stderr_lines:
        if line.startswith("Storage:"):
            store = line.split("Storage:", 1)[1].strip()
    return ctx, c, store


def row_count(db, token):
    if not os.path.exists(db):
        return "db-absent"
    tmp = tempfile.mkdtemp(prefix="re62-copy-")
    try:
        for suf in ("", "-wal", "-shm"):
            if os.path.exists(db + suf):
                shutil.copy2(db + suf, os.path.join(tmp, "monet.db" + suf))
        con = sqlite3.connect(os.path.join(tmp, "monet.db"))
        try:
            n = con.execute("SELECT COUNT(*) FROM observations WHERE content LIKE ?",
                            ("%" + token + "%",)).fetchone()[0]
        finally:
            con.close()
        return n
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def leg_h1_blind_spot():
    print("\n--- H1: operator below the project root ---")
    sbx = sandbox("h1")
    os.makedirs(os.path.join(sbx["projA"], "sub", "deep"), exist_ok=True)
    env_host = arm_env(sbx, {"MONET_PROJECT_DIR": sbx["projA"]})
    env_plain = arm_env(sbx)
    token = "re62-h1-%d" % int(time.time())
    circle = "e2e-re62-h1-%d" % int(time.time())
    project_store = os.path.join(sbx["projA"], ".monet", "monet.db")
    home_store = os.path.join(sbx["home"], ".monet", "monet.db")

    ctx, c, served = bare_server(sbx["projB"], env_host)
    try:
        sandboxed(served, sbx, "h1 host bare start")
        ack = c.call_json("memory_store",
                          {"content": "RE-62 operator blind spot marker %s written by the host." % token,
                           "circle": circle})
    finally:
        ctx.close()

    repro("h1_host_wrote_into_project_store", real(served) == real(project_store), served)
    repro("h1_store_ack_created", (ack or {}).get("action") == "created", ack)
    repro("h1_row_present_in_project_store", row_count(project_store, token) == 1)

    root = sb_status(sbx, sbx["projA"], env_plain, "h1 project-root status")
    sub = sb_status(sbx, os.path.join(sbx["projA"], "sub"), env_plain, "h1 sub status")
    deep = sb_status(sbx, os.path.join(sbx["projA"], "sub", "deep"), env_plain, "h1 deep status")
    print("     root=%s concepts=%s | sub=%s concepts=%s | deep=%s concepts=%s"
          % (root["stdout"], root["concepts"], sub["stdout"], sub["concepts"],
             deep["stdout"], deep["concepts"]))

    repro("h1_root_bare_call_finds_the_project_store",
          real(root["stdout"]) == real(project_store) and (root["concepts"] or 0) >= 1, root)
    repro("h1_sub_bare_call_diverges_to_home_store",
          real(sub["stdout"]) == real(home_store) and real(sub["stdout"]) != real(project_store), sub)
    repro("h1_deep_bare_call_diverges_to_home_store",
          real(deep["stdout"]) == real(home_store), deep)

    desired("h1_sub_recall_sees_the_projects_records",
            real(sub["stdout"]) == real(project_store) and (sub["concepts"] or 0) >= 1, sub)

    ctx, c, served_sub = bare_server(os.path.join(sbx["projA"], "sub"), env_plain)
    try:
        sandboxed(served_sub, sbx, "h1 sub bare start")
        hits = c.call_json("memory_search", {"query": token, "circle": circle, "limit": 5})
    finally:
        ctx.close()
    n = len((hits or {}).get("results") or [])
    repro("h1_sub_server_hits_zero", n == 0, "hits=%s store=%s" % (n, served_sub))
    desired("h1_sub_server_recalls_host_record", n >= 1, "hits=%s" % n)


def leg_h2_silent_flip():
    print("\n--- H2: silent flip after a documented `-d` invocation ---")
    sbx = sandbox("h2", projects=(("projF", False),))
    env_plain = arm_env(sbx)
    token = "re62-h2-%d" % int(time.time())
    circle = "e2e-re62-h2-%d" % int(time.time())
    home_store = os.path.join(sbx["home"], ".monet", "monet.db")
    project_store = os.path.join(sbx["projF"], ".monet", "monet.db")

    # 1. store a record from projF with a bare server (lands in the user store)
    ctx, c, served0 = bare_server(sbx["projF"], env_plain)
    try:
        sandboxed(served0, sbx, "h2 baseline bare start")
        ack = c.call_json("memory_store",
                          {"content": "RE-62 silent flip marker %s stored from projF." % token,
                           "circle": circle})
        hits0 = c.call_json("memory_search", {"query": token, "circle": circle, "limit": 5})
    finally:
        ctx.close()
    repro("h2_baseline_store_is_user_store", real(served0) == real(home_store), served0)
    repro("h2_baseline_store_ack_created", (ack or {}).get("action") == "created", ack)
    repro("h2_baseline_recall", len((hits0 or {}).get("results") or []) >= 1)

    before = sb_status(sbx, sbx["projF"], env_plain, "h2 pre-flip status")
    repro("h2_before_flip_bare_call_serves_user_store",
          real(before["stdout"]) == real(home_store) and (before["concepts"] or 0) >= 1, before)

    # 2. the documented flag: `monet start -d <project>/.monet` creates the dir
    with process_env(env_plain), chdir(sbx["projF"]):
        sv = MonetClient(os.path.join(sbx["projF"], ".monet"))
        try:
            sv.initialize()
        finally:
            sv.close()
    repro("h2_documented_dash_created_project_monet",
          os.path.isdir(os.path.join(sbx["projF"], ".monet")), sbx["projF"])

    after = sb_status(sbx, sbx["projF"], env_plain, "h2 post-flip status")
    repro("h2_after_flip_bare_call_switched_store",
          real(after["stdout"]) == real(project_store)
          and real(after["stdout"]) != real(before["stdout"]), after)
    repro("h2_after_flip_project_store_is_empty", (after["concepts"] or 0) == 0, after)

    ctx, c, served1 = bare_server(sbx["projF"], env_plain)
    try:
        sandboxed(served1, sbx, "h2 post-flip bare start")
        hits1 = c.call_json("memory_search", {"query": token, "circle": circle, "limit": 5})
    finally:
        ctx.close()
    n1 = len((hits1 or {}).get("results") or [])
    repro("h2_record_still_on_disk_in_user_store", row_count(home_store, token) == 1)
    repro("h2_after_flip_recall_is_zero", n1 == 0, "hits=%s store=%s" % (n1, served1))
    desired("h2_record_stays_reachable_from_the_same_directory", n1 >= 1, "hits=%s" % n1)
    desired("h2_bare_call_store_is_stable_across_an_unrelated_dash_run",
            real(after["stdout"]) == real(before["stdout"]),
            "before=%s after=%s" % (before["stdout"], after["stdout"]))


def main():
    t0 = time.time()
    print("RE-62 guard | CLI=%s" % CLI)
    print("model cache=%s" % REAL_MODEL_CACHE)
    try:
        leg_h1_blind_spot()
        leg_h2_silent_flip()
    except RuntimeError as exc:
        print("\nGR-01 ABORT: %s" % exc)
        if not KEEP:
            for root in SANDBOXES:
                shutil.rmtree(root, ignore_errors=True)
        return 1

    if not KEEP:
        for root in SANDBOXES:
            shutil.rmtree(root, ignore_errors=True)

    repro_broken = [n for n, ok, _ in REPRO if not ok]
    desired_unmet = [n for n, ok, _ in DESIRED if not ok]
    wall = time.time() - t0
    print("\nRESULT: REPRO %d/%d ok, DESIRED %d/%d met (%.1fs)"
          % (len(REPRO) - len(repro_broken), len(REPRO),
             len(DESIRED) - len(desired_unmet), len(DESIRED), wall))
    if repro_broken:
        print("REPRO BROKEN (probe/harness fault, not a product verdict): %s" % repro_broken)
        return 1
    if desired_unmet:
        print("RE-62 PRESENT (XFAIL): %s" % desired_unmet)
        return 2
    print("RE-62 APPEARS FIXED (XPASS) — update reverse-engineering/ISSUES.md")
    return 3


if __name__ == "__main__":
    sys.exit(main())
