#!/usr/bin/env python3
"""Scenario (pure-source driver): core/retrieval.ts line coverage (test46).

DIRECTION next gap (run 53 notes): core/retrieval.ts was 52.5% (202/385), the
largest non-deprecated core gap. It is a pure scoring module (imports only
./embedding and ./lexical-overlap, neither with native deps) whose exported
record try functions take a StoragePort-db — which a real better-sqlite3
Database satisfies structurally (`.prepare(sql).all(...params)`). So unlike the
conformance/spans/skeleton drivers (which had zero I/O), this one drives the
REAL scoring SQL against a REAL in-memory better-sqlite3 store, covering the
edge branches the MCP `memory_search` happy path never reaches:

  scoreNativeConceptsByObservation — max-over-segments; zero-vector exclusion;
  non-positive-cosine exclusion; tie -> smaller observation id; superseded
  exclusion; kind='source' exclusion; segment-less obs via the UNION-ALL
  fallback; empty candidates; lexical-arm re-order + its per-observation
  overlap max + both early-returns; nativeScoreFloorOf honour/fence rules.
  scoreSourceConcepts — non-source ignored; zero chunks excluded; MAX over
  {whole-file, every ACTIVE chunk}; no-chunks -> whole-file.

The driver is esbuild-bundled from core source (alias @retrieval-src ->
packages/core/src/retrieval.ts, which pulls embedding.ts + lexical-overlap.ts
in). better-sqlite3 is a RUNTIME require via createRequire from an absolute
.native path (E2E_BSQ3), so it stays OUT of the bundle and needs no copy into
the installed dist. The bundle lands at ~/.monet-test/build/retrieval.coverage.js
(gitignored) and cov-map.cjs attributes its coverage to core/retrieval.ts via
the multi-bundle COV_BUNDLES path.

Isolation (GR-01): in-memory DB only; no store, no embedder, no ~/.monet touched.
"""
import glob
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
    retr_src = os.path.join(repo, "packages", "core", "src", "retrieval.ts")
    driver = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "retrieval_driver.mjs")
    node = os.path.join(NODE_PATH, "node") if NODE_PATH else "node"

    bsq = glob.glob(os.path.expanduser(
        "~/.local/share/monet-node22/lib/node_modules/@team-monet/monet/node_modules/better-sqlite3/lib/index.js"
    ))

    for p, name in [(cli_dir, "packages/cli"), (retr_src, "retrieval.ts"), (driver, "driver")]:
        check(f"setup_{name}_exists", os.path.exists(p), p)
    check("setup_better_sqlite3", bool(bsq), (bsq or ["missing"])[0])

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
        return 1

    build_script = os.path.join(cli_dir, ".e2e-retrieval-build.mjs")
    with open(build_script, "w") as f:
        f.write(
            'import { build } from "esbuild";\n'
            "await build({\n"
            "  entryPoints: [process.env.E2E_DRIVER],\n"
            "  outfile: process.env.E2E_OUT,\n"
            '  bundle: true, platform: "node", format: "esm", target: "node22",\n'
            '  sourcemap: "inline", sourcesContent: true, minify: false, legalComments: "none",\n'
            '  alias: { "@retrieval-src": process.env.E2E_RETR },\n'
            '  external: ["module"],\n'
            '  logLevel: "warning",\n'
            "});\n"
            'console.log("built");\n'
        )

    build_dir = os.path.join(test_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    out_bundle = os.path.join(build_dir, "retrieval.coverage.js")
    env = dict(os.environ)
    env.update({
        "E2E_DRIVER": driver,
        "E2E_OUT": out_bundle,
        "E2E_RETR": retr_src,
        "E2E_BSQ3": bsq[0],
        "PATH": NODE_PATH + ":" + env.get("PATH", ""),
    })
    try:
        r = subprocess.run([node, build_script], cwd=cli_dir, env=env, capture_output=True, text=True, timeout=120)
        check("build_rc0", r.returncode == 0, r.stderr[-300:])
        check("build_bundle_exists", os.path.exists(out_bundle), out_bundle)
        if r.returncode != 0:
            print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
            return 1

        r2 = subprocess.run([node, out_bundle], env=env, capture_output=True, text=True, timeout=60)
        check("driver_rc0", r2.returncode == 0, f"rc={r2.returncode}")
        if r2.returncode != 0:
            print(r2.stdout[-2000:])
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
            check("driver_full_pass_count", passed >= 38, f"passed={passed}")
    finally:
        try:
            os.remove(build_script)
        except OSError:
            pass

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
