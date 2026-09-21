#!/usr/bin/env python3
"""Scenario 12 — storage RESOLUTION: which store does a bare `monet` call serve?

Monet resolves the store through a ladder, and every entry point must agree on the
result:

    MONET_STORAGE_DIR (`--dir`/`-d`) -> <projectDir>/.monet (only if it EXISTS)
                                     -> $HOME/.monet
    projectDir = MONET_PROJECT_DIR || CLAUDE_PROJECT_DIR || cwd   (EXACT, no upward search)

This test is the POSITIVE regression guard for that ladder (scenario 12). For each
arm it asserts that `status` stdout, `status` stderr, `doctor --json`, `monet
config` (which pins MONET_STORAGE_DIR) and a BARE `monet start` all name the SAME
store, that the store is the one the ladder predicts, and that diagnosis never
materialises a project `.monet` directory that did not exist before. The final arm
proves the write LANDS in the resolved store, survives a fresh process, and is
physically present in that store's SQLite file.

Arms that are KNOWN-BAD on the released build live in their own XFAIL guards —
test64 (RE-62: operator blind spot below the project root + silent flip) and test65
(RE-63: relative MONET_STORAGE_DIR printed verbatim). They are deliberately not
asserted here: their DESIRED assertions would fail this positive guard.

Isolation: each arm gets a throwaway sandbox (temp HOME + projects) and the embedder
model cache is pointed at the REAL ~/.monet/models read-only, so no arm touches the
prod store and no arm re-downloads the 587 MB model. Requires node@22 on PATH
(`harness/run_suite.sh` does that).

Exit: 0 = PASS, 1 = FAIL (a state the ladder contract forbids).
"""

import contextlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "harness"))
from mcp_client import CLI, MonetClient, run_cli  # noqa: E402

REAL_HOME = os.path.expanduser("~")
REAL_MODEL_CACHE = os.path.join(REAL_HOME, ".monet", "models")

# Every rung input must be cleared per arm, otherwise the outer environment (or a
# sibling agent's shell) silently decides the outcome.
CLEARED = (
    "MONET_STORAGE_DIR", "MONET_PROJECT_DIR", "CLAUDE_PROJECT_DIR",
    "MONET_CIRCLE", "MONET_CALLER_ID", "MONET_PROJECT_ID", "MONET_AGENT_ID",
)
PROJECTS = (("projA", True), ("projB", True), ("projC", False), ("projD", True))
KEEP = bool(os.environ.get("MONET_KEEP_STORE"))

PASSED = 0
FAILED = 0
SANDBOXES = []


def check(name, cond, detail=None):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("  [PASS] %s" % name)
    else:
        FAILED += 1
        print("  [FAIL] %s%s" % (name, (" :: %s" % (detail,)) if detail is not None else ""))


def real(path):
    return os.path.realpath(path) if path else None


@contextlib.contextmanager
def process_env(env):
    """Swap the process environment for the duration of a block (MonetClient and
    the run_cli helper both read os.environ at spawn time)."""
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


def sandbox(tag):
    root = tempfile.mkdtemp(prefix="s12-%s-" % tag)
    sbx = {"root": root, "home": os.path.join(root, "home")}
    os.makedirs(sbx["home"], exist_ok=True)
    os.makedirs(os.path.join(sbx["home"], ".monet"), exist_ok=True)
    for name, with_monet in PROJECTS:
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


# --- surfaces ------------------------------------------------------------------

STATUS_RE = re.compile(r"^Storage:\s+(\S.*?)\s*$", re.M)
STORE_RE = re.compile(r"^store:\s+(\S.*?)\s*$", re.M)
COUNT_RE = {k: re.compile(r"^%s:\s+(\d+)\s*$" % k, re.M)
            for k in ("Concepts", "Observations")}


def surface_status(cwd, timeout=180):
    rc, out, err = run_cli(["status"], cwd=cwd, timeout=timeout)
    m = STORE_RE.search(err)
    d = {"rc": rc,
         "stdout": STATUS_RE.search(out).group(1) if STATUS_RE.search(out) else None,
         "stderr": m.group(1) if m else None}
    for k, rx in COUNT_RE.items():
        mm = rx.search(out)
        d[k.lower()] = int(mm.group(1)) if mm else None
    return d


def surface_doctor(cwd, timeout=180):
    rc, out, err = run_cli(["doctor", "--json"], cwd=cwd, timeout=timeout)
    path = None
    try:
        j = json.loads(out.strip().splitlines()[0])
        path = j.get("dbPath") or (j.get("details") or {}).get("dbPath")
    except Exception:
        pass
    if path is None:
        m = STORE_RE.search(err)
        path = m.group(1) if m else None
    return {"rc": rc, "path": path}


def surface_config(cwd, agent="cursor", timeout=180):
    """`monet config` pins the RESOLVED store as MONET_STORAGE_DIR (a DIR)."""
    rc, out, err = run_cli(["config", "--agent", agent], cwd=cwd, timeout=timeout)
    storage = None
    try:
        j = json.loads(out)
        servers = j.get("mcp_servers") or j.get("mcpServers") or {}
        srv = servers.get("Monet") or servers.get("monet") or {}
        storage = (srv.get("env") or {}).get("MONET_STORAGE_DIR")
    except Exception:
        pass
    return {"rc": rc, "storage_dir": storage}


def surface_start(cwd):
    """BARE `monet start` (no -d): the shape an agent host actually spawns."""
    with chdir(cwd):
        c = MonetClient(None)
        try:
            c.initialize()
            for line in c.stderr_lines:
                if line.startswith("Storage:"):
                    return line.split("Storage:", 1)[1].strip()
            return None
        finally:
            c.close()


def surface_dashboard(cwd, timeout=15):
    """`monet dashboard` prints `Store: <db>`; suppress the browser with a shim."""
    shim = tempfile.mkdtemp(prefix="s12-shim-")
    opener = os.path.join(shim, "open")
    with open(opener, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(opener, 0o755)
    env = dict(os.environ)
    env["PATH"] = shim + os.pathsep + env.get("PATH", "")
    p = subprocess.Popen([CLI, "dashboard"], cwd=cwd, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
    m = re.search(r"Store:\s+(\S.*?)\s*$", (out or "") + (err or ""), re.M)
    return m.group(1) if m else None


# --- arms -----------------------------------------------------------------------

def run_arm(name, cwd_rel, over_keys, expect_rel, with_dash=False, forbidden=()):
    """One resolution arm: all surfaces must agree on the predicted store."""
    print("\n=== %s | cwd=%s | over=%s | expect=%s"
          % (name, cwd_rel, sorted(over_keys or {}), expect_rel))
    sbx = sandbox(name)
    over = {k: (v.replace("<root>", sbx["root"]) if v.startswith("<root>")
                else v if os.path.isabs(v) else os.path.join(sbx["root"], v))
            for k, v in (over_keys or {}).items()}
    env = arm_env(sbx, over)
    cwd = os.path.join(sbx["root"], cwd_rel.replace("/", os.sep))
    expect = expect_rel.replace("<root>", sbx["root"])
    expect = expect if os.path.isabs(expect) else os.path.join(sbx["root"], expect)
    pre = {k: os.path.isdir(os.path.join(sbx[k], ".monet")) for k, _ in PROJECTS}

    with process_env(env):
        s = surface_status(cwd)
        d = surface_doctor(cwd)
        cfg = surface_config(cwd)
        dash = surface_dashboard(cwd) if with_dash else None
        start = surface_start(cwd)

    post = {k: os.path.isdir(os.path.join(sbx[k], ".monet")) for k, _ in PROJECTS}
    created = sorted(k for k in pre if not pre[k] and post[k])

    paths = {"status_stdout": s["stdout"], "status_stderr": s["stderr"],
             "doctor": d["path"], "start": start}
    if with_dash:
        paths["dashboard"] = dash
    print("     status_stdout=%s\n     status_stderr=%s\n     doctor=%s\n     start=%s\n     config=%s\n     config_rc=%s"
          % (s["stdout"], s["stderr"], d["path"], start, cfg["storage_dir"], cfg["rc"]))
    if with_dash:
        print("     dashboard=%s" % dash)

    present = [k for k, v in paths.items() if v]
    missing = sorted(k for k, v in paths.items() if not v)
    check("%s_all_surfaces_report_a_store" % name, not missing, "missing=%s" % missing)

    resolved = {k: real(v) for k, v in paths.items() if v}
    uniq = sorted(set(resolved.values()))
    check("%s_surfaces_agree_on_one_store" % name, len(uniq) == 1, "paths=%s" % json.dumps(resolved))
    check("%s_served_store_is_the_ladder_prediction" % name,
          real(expect) in uniq, "expect=%s got=%s" % (real(expect), uniq))

    cfg_db = os.path.join(cfg["storage_dir"], "monet.db") if cfg.get("storage_dir") else None
    check("%s_config_pins_the_same_store" % name,
          cfg_db is not None and real(cfg_db) in uniq, "config=%s" % cfg_db)

    for key in forbidden:
        bad = real(os.path.join(sbx["root"], key.replace("/", os.sep), ".monet", "monet.db"))
        check("%s_losing_rung_store_not_served(%s)" % (name, key),
              bad not in uniq, "unexpectedly served %s" % bad)

    check("%s_diagnosis_creates_no_project_dot_monet" % name, created == [],
          "created=%s" % created)
    return sbx


def run_journey():
    """Write lands in the resolved store, survives a fresh process, is on disk."""
    name = "A7-journey-write-landing"
    print("\n=== %s | host env MONET_PROJECT_DIR=projA, spawned at cwd=projB" % name)
    sbx = sandbox(name)
    for sub in ("sub", os.path.join("sub", "deep")):
        os.makedirs(os.path.join(sbx["projA"], sub), exist_ok=True)
    env_host = arm_env(sbx, {"MONET_PROJECT_DIR": sbx["projA"]})
    env_plain = arm_env(sbx)
    token = "s12-token-%d" % int(time.time())
    circle = "e2e-s12-%d" % int(time.time())
    expect_store = os.path.join(sbx["projA"], ".monet", "monet.db")
    store_used = {}

    # 1. agent host: bare start, MONET_PROJECT_DIR=projA, cwd=projB
    with process_env(env_host), chdir(sbx["projB"]):
        c = MonetClient(None)
        try:
            c.initialize()
            for line in c.stderr_lines:
                if line.startswith("Storage:"):
                    store_used["host"] = line.split("Storage:", 1)[1].strip()
            ack = c.call_json("memory_store",
                              {"content": "Storage resolution journey marker %s recorded in project A." % token,
                               "circle": circle})
            hits = c.call_json("memory_search", {"query": token, "circle": circle, "limit": 5})
        finally:
            c.close()
    hits_n = len((hits or {}).get("results") or [])
    check("%s_host_serves_the_project_store" % name,
          real(store_used.get("host")) == real(expect_store), store_used.get("host"))
    check("%s_store_ack_is_created" % name, (ack or {}).get("action") == "created", ack)
    check("%s_same_process_recall" % name, hits_n >= 1, "hits=%s" % hits_n)

    # 2. fresh host process, same env: the record must survive
    with process_env(env_host), chdir(sbx["projB"]):
        c2 = MonetClient(None)
        try:
            c2.initialize()
            for line in c2.stderr_lines:
                if line.startswith("Storage:"):
                    store_used["fresh"] = line.split("Storage:", 1)[1].strip()
            h2 = c2.call_json("memory_search", {"query": token, "circle": circle, "limit": 5})
        finally:
            c2.close()
    check("%s_fresh_process_same_store" % name,
          real(store_used.get("fresh")) == real(expect_store), store_used.get("fresh"))
    check("%s_fresh_process_recall" % name, len((h2 or {}).get("results") or []) >= 1, h2)

    # 3. operator at the project root, plain env, must land on the same store
    with process_env(env_plain):
        st = surface_status(sbx["projA"])
    check("%s_operator_at_project_root_sees_the_record" % name,
          real(st["stdout"]) == real(expect_store) and (st["concepts"] or 0) >= 1, st)

    # 4. physical proof: the row is in projA's db, not in projB's, not in $HOME's
    def rows(db, table="observations", col="content"):
        if not os.path.exists(db):
            return "db-absent"
        tmp = tempfile.mkdtemp(prefix="s12-copy-")
        for suf in ("", "-wal", "-shm"):
            if os.path.exists(db + suf):
                shutil.copy2(db + suf, os.path.join(tmp, "monet.db" + suf))
        try:
            con = sqlite3.connect(os.path.join(tmp, "monet.db"))
            try:
                n = con.execute("SELECT COUNT(*) FROM %s WHERE %s LIKE ?" % (table, col),
                                ("%" + token + "%",)).fetchone()[0]
            finally:
                con.close()
            return n
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    check("%s_physical_row_in_project_store" % name, rows(expect_store) == 1)
    check("%s_physical_row_absent_from_sibling_project" % name,
          rows(os.path.join(sbx["projB"], ".monet", "monet.db")) in (0, "db-absent"))
    check("%s_physical_row_absent_from_home_store" % name,
          rows(os.path.join(sbx["home"], ".monet", "monet.db")) in (0, "db-absent"))


def main():
    t0 = time.time()
    print("CLI=%s" % CLI)
    print("model cache=%s" % REAL_MODEL_CACHE)

    # A1: no override, cwd has no `.monet` -> user-level store
    run_arm("A1-cwd-without-dot-monet", "projC", None, os.path.join("home", ".monet", "monet.db"))
    # A2: no override, cwd HAS `.monet` -> project store
    run_arm("A2-cwd-with-dot-monet", "projA", None, os.path.join("projA", ".monet", "monet.db"))
    # A3: MONET_PROJECT_DIR diverges from cwd -> the declared project wins
    run_arm("A3-MONET_PROJECT_DIR-wins-over-cwd", "projB", {"MONET_PROJECT_DIR": "projA"},
            os.path.join("projA", ".monet", "monet.db"), with_dash=True,
            forbidden=("projB",))
    # A4: CLAUDE_PROJECT_DIR is an accepted alias for the same rung
    run_arm("A4-CLAUDE_PROJECT_DIR-wins-over-cwd", "projB", {"CLAUDE_PROJECT_DIR": "projA"},
            os.path.join("projA", ".monet", "monet.db"), forbidden=("projB",))
    # A5: precedence inside the rung
    run_arm("A5-MONET_PROJECT_DIR-beats-CLAUDE_PROJECT_DIR", "projB",
            {"MONET_PROJECT_DIR": "projA", "CLAUDE_PROJECT_DIR": "projD"},
            os.path.join("projA", ".monet", "monet.db"), forbidden=("projD", "projB"))
    # A6: explicit override outranks the project rung
    run_arm("A6-MONET_STORAGE_DIR-beats-project-rung", "projB",
            {"MONET_STORAGE_DIR": "<root>/explicit"}, os.path.join("explicit", "monet.db"),
            forbidden=("projB",))

    run_journey()

    if not KEEP:
        for root in SANDBOXES:
            shutil.rmtree(root, ignore_errors=True)

    print("\nRESULT: %d passed, %d failed (%.1fs)" % (PASSED, FAILED, time.time() - t0))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
