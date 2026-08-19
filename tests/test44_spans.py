#!/usr/bin/env python3
"""Scenario (pure-source driver): core/spans.ts line coverage (test44).

DIRECTION priority #3 (monet-e2e#20): core/spans.ts was 39.8% (78/196). It is a
self-contained pure module (NO imports — only local types + regexes) exporting
the span:// transcript-address URI parse/format pair. The MCP suite only
reaches a slice of it (via lifecycle-edges / engine), so the URI bijection edge
cases (every rejection branch of formatSpan/parseSpan, the opaque-anchor rule
for unknown hosts, the claude-code L-start-L-end anchor grammar) were never
executed.

Like test43's cli/db driver (and test42's conformance driver): a DIRECT driver
bundled from core source exercises all exports. spans.ts has no imports, so the
esbuild bundle is fully self-contained (no core stub needed). The driver is
built to ~/.monet-test/build/spans.coverage.js (gitignored) and cov-map
attributes it back to core/spans.ts by short name.

Isolation (GR-01): no store, no embedder, no ~/.monet touched.

CONTRACT UNDER TEST (all pinned from source):
  - SPAN_SCHEME / CLAUDE_CODE_HOST constants.
  - isSpanRef = prefix test only (deliberately NOT parseSpan!==null).
  - formatSpan canonical URI + host grammar + throws on bad host / empty
    session-anchor / known-host-invalid anchor / lone-surrogate (encodeField).
  - parseSpan strict + bijective: parseSpan(formatSpan(x))==x AND
    formatSpan(parseSpan(s))==s; rejects no-scheme / missing-extra # / no '/' /
    raw '/' in session / invalid host / empty fields / bad escapes /
    non-canonical spellings / known-host-invalid anchors; unknown hosts opaque.
  - parseClaudeCodeAnchor / formatClaudeCodeAnchor grammar + round-trip.
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
    spans_src = os.path.join(repo, "packages", "core", "src", "spans.ts")
    driver = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "spans_driver.mjs")
    node = os.path.join(NODE_PATH, "node") if NODE_PATH else "node"

    for p, name in [(cli_dir, "packages/cli"), (spans_src, "spans.ts"), (driver, "driver")]:
        check(f"setup_{name}_exists", os.path.exists(p), p)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
        return 1

    build_script = os.path.join(cli_dir, ".e2e-spans-build.mjs")
    with open(build_script, "w") as f:
        f.write(
            'import { build } from "esbuild";\n'
            "await build({\n"
            "  entryPoints: [process.env.E2E_DRIVER],\n"
            "  outfile: process.env.E2E_OUT,\n"
            '  bundle: true, platform: "node", format: "esm", target: "node22",\n'
            '  sourcemap: "inline", sourcesContent: true, minify: false, legalComments: "none",\n'
            "  alias: { \"@spans-src\": process.env.E2E_SPANS },\n"
            '  logLevel: "warning",\n'
            "});\n"
            'console.log("built");\n'
        )

    build_dir = os.path.join(test_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    out_bundle = os.path.join(build_dir, "spans.coverage.js")
    env = dict(os.environ)
    env.update({
        "E2E_DRIVER": driver,
        "E2E_OUT": out_bundle,
        "E2E_SPANS": spans_src,
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
            check("driver_full_pass_count", passed >= 48, f"passed={passed}")
    finally:
        try:
            os.remove(build_script)
        except OSError:
            pass

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
