#!/usr/bin/env python3
"""RE-63 guard — a RELATIVE `MONET_STORAGE_DIR` is echoed verbatim by some surfaces
while others print the absolute resolved path.

Measured on the LIVE `monet` path (fresh sandbox, HOME + cwd + ALL rung env vars
cleared, only `MONET_STORAGE_DIR=rel-store` relative to the cwd):

    `status` stdout   -> rel-store/monet.db      (VERBATIM, relative)
    `status` stderr   -> /private/var/.../rel-store/monet.db   (absolute)
    `doctor --json`   -> dbPath absolute
    bare `monet start`-> Storage: absolute

So the resolution itself is fine and the store is unambiguous on disk; the defect is
that the human-facing `status` line reports a path that only means something together
with the cwd it was printed in. Any tool that greps `monet status` for the store
(there is precedent: storage-resolution probes and operator scripts do exactly this)
reads a path that resolves against the READER's cwd, i.e. a different file.

This guard asserts the DESIRED behaviour: every surface that reports the store prints
an ABSOLUTE path, and all of them agree after realpath normalization. Exit 2 (XFAIL)
while broken, 3 (XPASS) once fixed, 1 (FAIL) if the repro assertions do not hold (a
probe that cannot see the relative string must not report a product verdict).

Isolation: throwaway sandbox (temp HOME + project), real model cache read-only.
"""

import contextlib
import json
import os
import re
import shutil
import subprocess
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
REL_DIR = "rel-store"
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


STATUS_RE = re.compile(r"^Storage:\s+(\S.*?)\s*$", re.M)
STORE_RE = re.compile(r"^store:\s+(\S.*?)\s*$", re.M)


def main():
    t0 = time.time()
    print("RE-63 guard | CLI=%s" % CLI)
    print("model cache=%s" % REAL_MODEL_CACHE)

    root = tempfile.mkdtemp(prefix="re63-")
    SANDBOXES.append(root)
    home = os.path.join(root, "home")
    proj = os.path.join(root, "projB")
    os.makedirs(os.path.join(home, ".monet"), exist_ok=True)
    os.makedirs(os.path.join(proj, ".monet"), exist_ok=True)

    env = dict(os.environ)
    for key in CLEARED:
        env.pop(key, None)
    env["HOME"] = home
    env.pop("USERPROFILE", None)
    env["MONET_MODEL_CACHE"] = REAL_MODEL_CACHE
    env["MONET_STORAGE_DIR"] = REL_DIR  # RELATIVE to cwd on purpose
    expect = os.path.join(proj, REL_DIR, "monet.db")

    surfaces = {}
    with process_env(env):
        rc, out, err = run_cli(["status"], cwd=proj, timeout=180)
        m = STORE_RE.search(err)
        surfaces["status_stdout"] = STATUS_RE.search(out).group(1) if STATUS_RE.search(out) else None
        surfaces["status_stderr"] = m.group(1) if m else None

        rc2, out2, err2 = run_cli(["doctor", "--json"], cwd=proj, timeout=180)
        path = None
        try:
            path = json.loads(out2.strip().splitlines()[0]).get("dbPath")
        except Exception:
            pass
        surfaces["doctor_dbPath"] = path

        with chdir(proj):
            c = MonetClient(None)
            try:
                c.initialize()
                for line in c.stderr_lines:
                    if line.startswith("Storage:"):
                        surfaces["bare_start"] = line.split("Storage:", 1)[1].strip()
            finally:
                c.close()

    print("     expect(absolute)=%s" % expect)
    for k in ("status_stdout", "status_stderr", "doctor_dbPath", "bare_start"):
        print("     %-14s = %r" % (k, surfaces.get(k)))

    present = [k for k, v in surfaces.items() if v]
    repro("all_surfaces_report_a_path", len(present) == 4,
          "missing=%s" % sorted(set(surfaces) - set(present)))

    # the defect: the relative string survives verbatim into a reported surface
    relative_seen = {k: v for k, v in surfaces.items()
                     if v and not os.path.isabs(v)}
    repro("a_surface_echoes_the_relative_dir_verbatim", bool(relative_seen), relative_seen)
    repro("relative_surface_is_the_verbatim_override",
          any(v == os.path.join(REL_DIR, "monet.db") or v == REL_DIR
              for v in relative_seen.values()), relative_seen)

    # the truth is available: the non-relative surfaces agree, so a fix is display-only
    absolute = {k: real(v) for k, v in surfaces.items() if v and os.path.isabs(v)}
    repro("absolute_surfaces_agree_on_the_resolved_store",
          len(set(absolute.values())) == 1 and real(expect) in set(absolute.values()),
          absolute)

    desired("all_surfaces_print_an_absolute_path",
            not relative_seen, "relative=%s" % relative_seen)
    desired("all_surfaces_agree_after_realpath",
            len({real(v) for v in surfaces.values() if v}) == 1,
            {k: real(v) for k, v in surfaces.items()})

    if not KEEP:
        for p in SANDBOXES:
            shutil.rmtree(p, ignore_errors=True)

    repro_broken = [n for n, ok, _ in REPRO if not ok]
    desired_unmet = [n for n, ok, _ in DESIRED if not ok]
    print("\nRESULT: REPRO %d/%d ok, DESIRED %d/%d met (%.1fs)"
          % (len(REPRO) - len(repro_broken), len(REPRO),
             len(DESIRED) - len(desired_unmet), len(DESIRED), time.time() - t0))
    if repro_broken:
        print("REPRO BROKEN (probe/harness fault, not a product verdict): %s" % repro_broken)
        return 1
    if desired_unmet:
        print("RE-63 PRESENT (XFAIL): %s" % desired_unmet)
        return 2
    print("RE-63 APPEARS FIXED (XPASS) — update reverse-engineering/ISSUES.md")
    return 3


if __name__ == "__main__":
    sys.exit(main())
