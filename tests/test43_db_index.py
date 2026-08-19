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
  (alias @dbindex-src) and the one constant it needs from @team-monet/core
  (GATE_JOURNAL_FILENAME — aliased to a 1-line stub, since the module only uses
  that constant and bundling the whole core would pull native deps). esbuild
  bundles it inline-sourcemapped into ~/.monet-test/build/db_index.coverage.js
  (gitignored), cov-map attributes it back to cli/db/index.ts by short name.

Isolation (GR-01): no store, no embedder, no ~/.monet touched — the driver only
manipulates process.env + temp dirs under os.tmpdir().

CONTRACT UNDER TEST (pinned, all from source):
  - getMonetDir rung order: MONET_STORAGE_DIR -> project-local ./.monet (only
    if it already EXISTS) -> HOME -> USERPROFILE -> baseDir.
  - getDbPath / getGateMirrorPath / getMaterializePath = join(getMonetDir, const)
    for the store, mirror, and materialize manifest.
  - getGateJournalPath DELIBERATELY diverges: NOT routed through getMonetDir,
    no baseDir param, two rungs (MONET_STORAGE_DIR -> os.homedir()/.monet), home
    = os.homedir() (NOT the HOME env var) so it agrees with the generated hook
    wrapper. Pinned: it ignores a fake HOME and a project-local .monet.
  - ensureMonetDir mkdirSync(recursive), returns dir, idempotent, honors env.
"""
import os
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
    driver = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "db_index_driver.mjs")
    node = os.path.join(NODE_PATH, "node") if NODE_PATH else "node"

    for p, name in [(cli_dir, "packages/cli"), (db_src, "db/index.ts"), (driver, "driver")]:
        check(f"setup_{name}_exists", os.path.exists(p), p)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
        return 1

    # 1. write an esbuild build script into packages/cli (esbuild resolves there)
    build_script = os.path.join(cli_dir, ".e2e-dbindex-build.mjs")
    with open(build_script, "w") as f:
        f.write(
            'import { build } from "esbuild";\n'
            "await build({\n"
            "  entryPoints: [process.env.E2E_DRIVER],\n"
            "  outfile: process.env.E2E_OUT,\n"
            '  bundle: true, platform: "node", format: "esm", target: "node22",\n'
            '  sourcemap: "inline", sourcesContent: true, minify: false, legalComments: "none",\n'
            "  alias: {\n"
            "    \"@dbindex-src\": process.env.E2E_DBINDEX,\n"
            "    \"@team-monet/core\": process.env.E2E_CORE_STUB,\n"
            "  },\n"
            '  logLevel: "warning",\n'
            "});\n"
            'console.log("built");\n'
        )

    tmp = tempfile.mkdtemp(prefix="e2e-dbindex-")
    core_stub = os.path.join(tmp, "core_stub.mjs")
    with open(core_stub, "w") as f:
        # Only export the one constant cli/db/index.ts needs from core.
        f.write('export const GATE_JOURNAL_FILENAME = "gate-journal.jsonl";\n')

    build_dir = os.path.join(test_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    out_bundle = os.path.join(build_dir, "db_index.coverage.js")
    env = dict(os.environ)
    env.update({
        "E2E_DRIVER": driver,
        "E2E_OUT": out_bundle,
        "E2E_DBINDEX": db_src,
        "E2E_CORE_STUB": core_stub,
        "PATH": NODE_PATH + ":" + env.get("PATH", ""),
    })
    try:
        # build
        r = subprocess.run([node, build_script], cwd=cli_dir, env=env, capture_output=True, text=True, timeout=120)
        check("build_rc0", r.returncode == 0, r.stderr[-300:])
        check("build_bundle_exists", os.path.exists(out_bundle), out_bundle)
        if r.returncode != 0:
            print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
            return 1

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
            check("driver_full_pass_count", passed >= 23, f"passed={passed}")
    finally:
        try:
            os.remove(build_script)
        except OSError:
            pass

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
