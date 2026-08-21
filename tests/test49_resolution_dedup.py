#!/usr/bin/env python3
"""Scenario (pure-core driver): core/resolution.ts dedup band matrix (test49).

DIRECTION / run 58's recommendation #3: core/resolution.ts (the store-time
resolution / dedup DECISION engine — "find by evidence, confirm by identity")
was the one remaining "genuine" (non-upstream-tested) coverage claim above the
saturated ~84% raw-% ceiling. This driver settles it empirically.

It is PURE: no db handle, no clock, no side effects (only the exported
resolveIncoming / isDecidedResolutionMode / DECIDED_RESOLUTION_MODES). The MCP
store path executes resolveIncoming() on every memory_store, so the suite
observes the DECISION's output indirectly (action=created/attached/ambiguous)
but never isolates the decision function or its band boundaries.

`assets/resolution_driver.mjs` is that driver: it calls the exported pure
functions directly with crafted nominations/centroids and pins the ENTIRE band
matrix as 46 falsifiable assertions (GR-07) — attach / fork-signal /
ambiguous-fork / correction-attach / blur-duplicate / new, plus all the
INCLUSIVE-at-the-bottom boundary cases, the null-nomination path, the
centroid-confirms-only (never attaches) rule, isDecidedResolutionMode, and the
exact 8-mode DECIDED_RESOLUTION_MODES closed set.

COVERAGE OUTCOME (measured this run): **no line lift.** The driver alone covers
79/338 lines of resolution.ts, but the cli.coverage.js MCP bundle already covers
218/338 (64.5%) — resolution.ts sits on the memory_store hot path, so the
driver's lines are a strict SUBSET of the bundle union (same run-53/54/55
per-module-subset lesson as db/index.ts and retrieval.ts). It is retained as a
durable FUNCTIONAL REGRESSION test (the suite otherwise records the band matrix
only as side effects, never as an isolated decision contract), and record:
core/resolution.ts is now EMPIRICALLY a coverage false-lead (comment-diluted),
closing run 58's recommendation #3 — the raw-% coverage metric is saturated.

Isolation (GR-01): no store, no embedder, no ~/.monet touched. Driver imports
only core/src/resolution.ts (pure; node builtins only). esbuild step runs with
cwd=packages/cli so the monorepo's esbuild resolves (mirrors test42/44/45).
"""
import json
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
    res_src = os.path.join(repo, "packages", "core", "src", "resolution.ts")
    driver = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "resolution_driver.mjs")
    node = os.path.join(NODE_PATH, "node") if NODE_PATH else "node"

    for p, name in [(cli_dir, "packages/cli"), (res_src, "resolution.ts"), (driver, "driver")]:
        check(f"setup_{name}_exists", os.path.exists(p), p)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
        return 1

    # 1. write an esbuild build script into packages/cli (esbuild resolves there)
    build_script = os.path.join(cli_dir, ".e2e-resolution-build.mjs")
    with open(build_script, "w") as f:
        f.write(
            'import { build } from "esbuild";\n'
            "await build({\n"
            '  entryPoints: [process.env.E2E_DRIVER],\n'
            '  outfile: process.env.E2E_OUT,\n'
            '  bundle: true, platform: "node", format: "esm", target: "node22",\n'
            '  sourcemap: "inline", sourcesContent: true, minify: false, legalComments: "none",\n'
            '  alias: { "@resolution-src": process.env.E2E_RES },\n'
            '  logLevel: "warning",\n'
            "});\n"
            'console.log("built");\n'
        )

    # Stable bundle path under the repo so cov-map.cjs can read it back after a
    # NODE_V8_COVERAGE run (gitignored, never committed).
    build_dir = os.path.join(test_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    out_bundle = os.path.join(build_dir, "resolution.coverage.js")
    env = dict(os.environ)
    env.update({"E2E_DRIVER": driver, "E2E_OUT": out_bundle, "E2E_RES": res_src,
                "PATH": NODE_PATH + ":" + env.get("PATH", "")})
    try:
        # build
        r = subprocess.run([node, build_script], cwd=cli_dir, env=env, capture_output=True, text=True, timeout=120)
        check("build_rc0", r.returncode == 0, r.stderr[-300:])
        check("build_bundle_exists", os.path.exists(out_bundle), out_bundle)
        if r.returncode != 0:
            print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
            return 1

        # run the pure-resolution driver
        r2 = subprocess.run([node, out_bundle], env=env, capture_output=True, text=True, timeout=60)
        check("driver_rc0", r2.returncode == 0, f"rc={r2.returncode}")
        if r2.returncode != 0:
            print(r2.stdout[-1500:])
            print(r2.stderr[-800:])

        # parse the RESULT: line
        result_line = [l for l in r2.stdout.splitlines() if l.startswith("RESULT:")]
        check("driver_result_line", bool(result_line), str(result_line)[:80])
        if result_line:
            try:
                passed = int(result_line[0].split()[1])
                failed = int(result_line[0].split()[3])
            except (IndexError, ValueError):
                passed, failed = -1, -1
            check("driver_zero_fail", failed == 0, f"failed={failed}")
            check("driver_full_pass_count", passed >= 46, f"passed={passed}")
    finally:
        try:
            os.remove(build_script)
        except OSError:
            pass

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
