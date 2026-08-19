#!/usr/bin/env python3
"""Scenario (pure-core driver): core/conformance.ts line coverage (test42).

DIRECTION priority #1 (monet-e2e#18): core/conformance.ts was the largest
non-deprecated core gap at 33.1% (169/510). It is NOT reachable through any
MCP/CLI surface — engine.runConformancePass(), the sole caller of
computeConformance, is not wired to any command/tool on the shipped 1.6.3
binary OR on `main` (verified: only its definition exists in the source tree).
So the conformance "cheap half" (the §4/§5 verdict decision table) can only be
exercised through a direct driver that calls the exported PURE functions with
crafted journal lines.

`assets/conformance_driver.mjs` is that driver. It is bundled from core SOURCE
with esbuild (alias @conformance-src -> packages/core/src/conformance.ts) into
an inline-sourcemapped ESM bundle, then executed with node@22. V8 coverage from
that process names the bundle `conformance.coverage.js`, which cov-map.cjs
attributes back to packages/core/src/conformance.ts (+ gate-journal.ts) via the
multi-bundle path. When the suite runs WITHOUT coverage this is still a real
functional test: it asserts the driver's own 47 verdict/tally/retirement
assertions pass, gating the conformance semantics.

CONTRACT UNDER TEST (the verdict decision table, all reverse-engineered from
source and pinned as falsifiable assertions):
  - deny + enforced            -> verdict 'changed', claimType source-observed
  - single-rule deny           -> NO verdictRuleIds (nothing to apportion)
  - mixed-severity deny, recorded blockingRuleIds -> verdictRuleIds = blocking set
  - multi-rule deny, NO recorded blocking set     -> verdictRuleIds = [] (no rule
      credited) + reason discloses "which rules blocked is unavailable"
  - deny delivered but unenforced (advisory path) -> verdict ABSENT, claimType
      'unavailable' (a deny that was never enforced is not 'changed')
  - advisory fire              -> verdict ABSENT, claimType 'unavailable'
  - non-fire dispositions (silent/stage-hit-no-rules) -> ignored
  - multi-mouth chain (parentId) folds to ONE verdict; enforced read across chain
  - retry detection: same act (actionContext || actionContextSha256) in a later
      DIFFERENT chain -> retriedUnchanged true
  - buildChainIds roots multi-hop (grandchild->root) so one evaluation isn't a retry
  - idempotence: prior conformance line suppresses re-annotation, EXCEPT on
      retry improvement and scoped-attribution migration
  - tallyByRule: all five verdicts (changed/conformed/breached/no-effect/vacuous)
      + per-rule scoping (verdictRuleIds) + awaitingJudgment for un-scoped/advisory
  - retirementCandidates: fires>0 && changed+conformed==0 && awaitingJudgment==0
      (no-effect counts as measured; all-awaiting and never-fired excluded)
  - appendConformanceAnnotations appends phase:'conformance' journal lines

Isolation (GR-01): no store, no embedder, no ~/.monet touched. The driver only
imports conformance.ts + gate-journal.ts (pure; node builtins only), writes a
temp journal, and compiles. The esbuild step runs with cwd=packages/cli so the
monorepo's esbuild resolves (mirrors the coverage-build.mjs recipe).
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
    conf_src = os.path.join(repo, "packages", "core", "src", "conformance.ts")
    driver = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "conformance_driver.mjs")
    node = os.path.join(NODE_PATH, "node") if NODE_PATH else "node"

    for p, name in [(cli_dir, "packages/cli"), (conf_src, "conformance.ts"), (driver, "driver")]:
        check(f"setup_{name}_exists", os.path.exists(p), p)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
        return 1

    # 1. write an esbuild build script into packages/cli (esbuild resolves there)
    build_script = os.path.join(cli_dir, ".e2e-conformance-build.mjs")
    with open(build_script, "w") as f:
        f.write(
            'import { build } from "esbuild";\n'
            "await build({\n"
            '  entryPoints: [process.env.E2E_DRIVER],\n'
            '  outfile: process.env.E2E_OUT,\n'
            '  bundle: true, platform: "node", format: "esm", target: "node22",\n'
            '  sourcemap: "inline", sourcesContent: true, minify: false, legalComments: "none",\n'
            '  alias: { "@conformance-src": process.env.E2E_CONF },\n'
            '  logLevel: "warning",\n'
            "});\n"
            'console.log("built");\n'
        )

    tmp = tempfile.mkdtemp(prefix="e2e-conform-")
    # Stable bundle path under the repo so cov-map.cjs can read it back after a
    # NODE_V8_COVERAGE run (it matches the script url by basename and reads the
    # bundle's inline sourcemap to attribute coverage). .gitignore'd, never committed.
    build_dir = os.path.join(test_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    out_bundle = os.path.join(build_dir, "conformance.coverage.js")
    env = dict(os.environ)
    env.update({"E2E_DRIVER": driver, "E2E_OUT": out_bundle, "E2E_CONF": conf_src, "PATH": NODE_PATH + ":" + env.get("PATH", "")})
    try:
        # build
        r = subprocess.run([node, build_script], cwd=cli_dir, env=env, capture_output=True, text=True, timeout=120)
        check("build_rc0", r.returncode == 0, r.stderr[-300:])
        check("build_bundle_exists", os.path.exists(out_bundle), out_bundle)
        if r.returncode != 0:
            print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
            return 1

        # run the pure-conformance driver
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
            check("driver_full_pass_count", passed >= 47, f"passed={passed}")
    finally:
        try:
            os.remove(build_script)
        except OSError:
            pass

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
