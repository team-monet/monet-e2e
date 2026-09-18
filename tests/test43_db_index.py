#!/usr/bin/env python3
"""Scenario (pure-source driver): cli/db/index.ts line coverage (test43).

DIRECTION priority #2 (monet-e2e#19): cli/db/index.ts was 27.9% (43/154) — the
storage-path resolution helper imported by nearly every CLI subcommand, but
never directly driven. The unified CLI bundle only reaches the handful of
lines a given subcommand happens to call; the full branch surface
(MONET_STORAGE_DIR / project-.monet-exists / HOME / USERPROFILE / baseDir rung
order, the ENV-only chain of getMonetDir, the deliberately-divergent
getGateJournalPath, ensureMonetDir creation/idempotence) was never exercised.

cli/db/index.ts is pure (node path/fs/os + one core constant), so like test42's
conformance driver this routes around any MCP/CLI surface with a DIRECT driver
bundled from source:

  assets/db_index_driver.mjs imports the 6 exports from cli/src/db/index.ts
  (alias @dbindex-src) and the 3 symbols it needs from @team-monet/core —
  MOMENT_SPOOL_FILENAME, STARTUP_FAILURE_SUFFIX, startupFailurePath — aliased to
  a GENERATED BARREL that re-exports the REAL core modules (moment-spool.ts,
  startup-diagnosis.ts; both pure node builtins). The 1-line hand-copied
  constant stub this replaces is exactly how the test went STALE in run 119: core
  renamed GATE_JOURNAL_FILENAME, the stub kept the old value, and the driver
  built clean while pinning a fiction. esbuild bundles it inline-sourcemapped
  into ~/.monet-test/build/db_index.coverage.js (gitignored), cov-map attributes
  it back to cli/db/index.ts by short name.

Isolation (GR-01): no store, no embedder, no ~/.monet touched — the driver only
manipulates process.env + temp dirs under os.tmpdir().

CONTRACT UNDER TEST (pinned, all from source; RE-BASELINED run 119):
  - getMonetDir rung order: MONET_STORAGE_DIR -> project-local ./.monet (only
    if it already EXISTS) -> HOME -> USERPROFILE -> baseDir.
  - getDbPath / getMaterializePath = join(getMonetDir, const) for the store and
    the materialize manifest.
  - getMomentSpoolPath DELIBERATELY diverges: NOT routed through getMonetDir,
    no baseDir param, two rungs (MONET_STORAGE_DIR -> os.homedir()/.monet), home
    = os.homedir() (NOT the HOME env var on its own terms — POSIX follows $HOME)
    so it agrees with the out-of-process spool writer contract. Pinned: it
    ignores a fake HOME's project-local .monet and USERPROFILE. (This function
    REPLACES getGateJournalPath, which did the same divergence.)
  - getStartupFailurePath = startupFailurePath(getDbPath(baseDir)): a sidecar of
    the STORE FILE (store name + STARTUP_FAILURE_SUFFIX, resolved beside it),
    so two stores in one directory never share a record (upstream #79).
  - ensureMonetDir mkdirSync(recursive), returns dir, idempotent, honors env.
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import NODE_PATH

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
    repo = os.environ.get("MONET_REPO") or os.path.expanduser("~/monet/monet")
    test_dir = os.environ.get("MONET_TEST_DIR") or os.path.expanduser("~/.monet-test")
    cli_dir = os.path.join(repo, "packages", "cli")
    db_src = os.path.join(repo, "packages", "cli", "src", "db", "index.ts")
    # The two REAL core modules the generated barrel re-exports (both pure node
    # builtins, so aliasing them pulls no native dep).
    spool_src = os.path.join(repo, "packages", "core", "src", "moment-spool.ts")
    diag_src = os.path.join(repo, "packages", "core", "src", "startup-diagnosis.ts")
    driver = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "db_index_driver.mjs")
    build_template = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "db_index_build.mjs")
    node = os.path.join(NODE_PATH, "node") if NODE_PATH else "node"

    for p, name in [(cli_dir, "packages/cli"), (db_src, "db/index.ts"),
                    (spool_src, "core/moment-spool.ts"), (diag_src, "core/startup-diagnosis.ts"),
                    (driver, "driver"), (build_template, "build_template")]:
        check(f"setup_{name}_exists", os.path.exists(p), p)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
        return 1

    # 1. materialize the esbuild build script into packages/cli (esbuild resolves there).
    # It is a STATIC env-driven template under tests/assets/ copied in as-is: the
    # previous inline version embedded JS inside Python string escapes, and one
    # escaping slip silently emitted a broken build script (run 119).
    build_script = os.path.join(cli_dir, ".e2e-dbindex-build.mjs")
    shutil.copyfile(build_template, build_script)

    tmp = tempfile.mkdtemp(prefix="e2e-dbindex-")
    # The core alias is a GENERATED BARREL over the REAL core modules, not a
    # hand-copied constant stub. The stub is how this test went STALE: core
    # renamed its constant, the stub kept the old value, and the driver still
    # built clean while pinning a fiction. Both modules are pure (node:fs /
    # node:crypto / node:path), so re-exporting them pulls no native dep.
    # Joined with chr(10) on purpose: no backslash escapes in this file.
    core_barrel = os.path.join(tmp, "core_barrel.mjs")
    with open(core_barrel, "w") as f:
        f.write(chr(10).join([
            'export { MOMENT_SPOOL_FILENAME } from "%s";' % spool_src,
            'export { STARTUP_FAILURE_SUFFIX, startupFailurePath } from "%s";' % diag_src,
            '',
        ]))

    build_dir = os.path.join(test_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    out_bundle = os.path.join(build_dir, "db_index.coverage.js")
    env = dict(os.environ)
    env.update({
        "E2E_DRIVER": driver,
        "E2E_OUT": out_bundle,
        "E2E_DBINDEX": db_src,
        "E2E_CORE_BARREL": core_barrel,
        "PATH": NODE_PATH + ":" + env.get("PATH", ""),
    })
    try:
        # build
        r = subprocess.run([node, build_script], cwd=cli_dir, env=env, capture_output=True, text=True, timeout=120)
        check("build_rc0", r.returncode == 0, r.stderr[-300:])
        check("build_bundle_exists", os.path.exists(out_bundle), out_bundle)
        if r.returncode != 0:
            # STALE (5): the pure-source build no longer compiles against the
            # monorepo. Do NOT fall through to the leftover bundle — running a
            # stale bundle and reporting PASS is a false green.
            print(f"\nRESULT: STALE — driver build failed against {cli_dir}")
            print(f"  esbuild error tail: {r.stderr[-300:]}")
            print("  The db/index.ts surface moved upstream; re-baseline the driver")
            print("  (and its generated core barrel) before trusting this test again.")
            return 5

        # run the pure db/index driver
        r2 = subprocess.run([node, out_bundle], env=env, capture_output=True, text=True, timeout=60)
        check("driver_rc0", r2.returncode == 0, f"rc={r2.returncode}")
        if r2.returncode != 0:
            print(r2.stdout[-1500:])
            print(r2.stderr[-800:])

        result_line = [l for l in r2.stdout.splitlines() if l.startswith("RESULT:")]
        check("driver_result_line", bool(result_line), str(result_line)[:80])
        if result_line:
            try:
                passed = int(result_line[0].split()[1])
                failed = int(result_line[0].split()[3])
            except (IndexError, ValueError):
                passed, failed = -1, -1
            check("driver_zero_fail", failed == 0, f"failed={failed}")
            # 30 = the driver's assertion count AFTER the run-119 re-baseline:
            # the retired getGateMirrorPath block (-4) is gone, the divergent
            # resolver moved to getMomentSpoolPath (same 6 divergence checks), and
            # scenario 8 adds 4 startup-failure-sidecar checks plus 2 literal
            # core-constant pins.
            check("driver_full_pass_count", passed >= 30, f"passed={passed}")
    finally:
        try:
            os.remove(build_script)
        except OSError:
            pass

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
