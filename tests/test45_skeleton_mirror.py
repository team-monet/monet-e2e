#!/usr/bin/env python3
"""Scenario (pure-source driver): core/skeleton-mirror.ts line coverage (test45).

DIRECTION follow-on (monet-e2e#19 / coverage pipeline): core/skeleton-mirror.ts
was 44.3% (90/203). It is a self-contained pure module (node:crypto/fs/path
only) exporting the skeleton-mirror staleness contract: parseManifest (private),
skeletonBlock (private), skeletonStateHash, hasCoveringSkeletonSurface, and
inspectSkeletonMirrors. The MCP/cli bundle only reaches a slice of it (via
mcp-server.ts / engine.ts — the write/cover side); the read/inspection edge
cases (manifest-shape rejections, BEGIN-no-END / no-marker blocks, block-edited
and store-moved staleness, alias-resolved circle scoping) were never executed.

Like test42/test44's pure-core drivers: a DIRECT driver bundled from source
(alias @skeleton-src -> packages/core/src/skeleton-mirror.ts; only node
builtins + its own code, so the bundle is self-contained) exercises all 3
exported functions and the private helpers indirectly through them. Bundled to
~/.monet-test/build/skeleton.coverage.js (gitignored), cov-map attributes it
back to core/skeleton-mirror.ts by short name.

Isolation (GR-01): no store, no embedder, no ~/.monet touched. Fixtures are
written to a throwaway os.tmpdir() and removed.

CONTRACT UNDER TEST (all pinned from source):
  - skeletonStateHash: sha256 of the canonical JSON, sorted by conceptId in
    raw code-unit order; strips extra member fields; order-invariant;
    deterministic; sensitive to body/breadth.
  - hasCoveringSkeletonSurface: null store / missing / malformed manifest ->
    false; global surface covers global breadth only; circle-scoped surface
    covers local breadth for a matching (alias-resolved) circle only.
  - inspectSkeletonMirrors: global/local covered derivation; block-missing
    (no materialized entry, no markers, BEGIN-but-no-END) / block-edited
    (blockHash mismatch) / store-moved (skeletonState mismatch); stale list +
    instruction only when stale; irrelevant-circle surfaces excluded.
"""
import os
import subprocess
import sys

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
    skel_src = os.path.join(repo, "packages", "core", "src", "skeleton-mirror.ts")
    driver = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "skeleton_mirror_driver.mjs")
    node = os.path.join(NODE_PATH, "node") if NODE_PATH else "node"

    for p, name in [(cli_dir, "packages/cli"), (skel_src, "skeleton-mirror.ts"), (driver, "driver")]:
        check(f"setup_{name}_exists", os.path.exists(p), p)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
        return 1

    build_script = os.path.join(cli_dir, ".e2e-skeleton-build.mjs")
    with open(build_script, "w") as f:
        f.write(
            'import { build } from "esbuild";\n'
            "await build({\n"
            "  entryPoints: [process.env.E2E_DRIVER],\n"
            "  outfile: process.env.E2E_OUT,\n"
            '  bundle: true, platform: "node", format: "esm", target: "node22",\n'
            '  sourcemap: "inline", sourcesContent: true, minify: false, legalComments: "none",\n'
            "  alias: { \"@skeleton-src\": process.env.E2E_SKELETON },\n"
            '  logLevel: "warning",\n'
            "});\n"
            'console.log("built");\n'
        )

    build_dir = os.path.join(test_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    out_bundle = os.path.join(build_dir, "skeleton.coverage.js")
    env = dict(os.environ)
    env.update({
        "E2E_DRIVER": driver,
        "E2E_OUT": out_bundle,
        "E2E_SKELETON": skel_src,
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
