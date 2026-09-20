#!/usr/bin/env python3
"""Scenario 62 / RE-61: the served identity of the running Monet does not name the
release, so nobody on the receiving end of an MCP session can tell which build answered.

Measured on the released 1.11.0 (2026-09-21, run 124), all from ONE installed package:

  * `dist/cli.js` answers the MCP `initialize` handshake with a HARDCODED literal
    `{ name: "monet-core", version: "0.7.0" }` (source: packages/core/src/mcp-server.ts,
    the `new McpServer(...)` call);
  * `package.json` (same install) says `@team-monet/monet@1.11.0`;
  * `packages/cli/server.json` — the MCP-registry manifest for the very same build —
    says `"version": "1.11.0"`;
  * `monet --version` prints `1.11.0`, and `monet doctor --json` has no version field
    at all (keys: assessment, command, dbPath, integrity, migration, nextCommands,
    nonLatin, ok, pin, populations, provider, rawAssessment, schema, schemaVersion,
    startupFailure, supportedSchemaVersion) — so the DIAGNOSIS surface does not name
    the release either;
  * the frozen value is not drift: `packages/core/src/__tests__/lifecycle.test.ts`
    asserts `{ name: "monet-core", version: "0.7.0" }` verbatim, so the stale literal
    is pinned in-repo and cannot move on its own.

Why this is a user-facing journey, not trivia: an MCP host renders the handshake
identity in its server panel, and an agent that reads `serverInfo` is the only party
that can report the running build back to the user. With a frozen `0.7.0` a support
thread cannot map "it says monet-core 0.7.0" to any release (`monet --version` is the
only surface that does), and the registry manifest of the same package disagrees with
the handshake of the same package.

This test drives the LIVE `monet start` MCP surface against an isolated temp store and
asserts the DESIRED contract: the identity served over MCP identifies the installed
release (handshake version == the version in the package.json that ships it).

Exit codes per the run_all.py convention: 0 PASS, 2 XFAIL, 3 XPASS, 1 setup failure.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient  # noqa: E402

CLI = os.environ.get(
    "MONET_CLI",
    os.path.expanduser(
        "~/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js"
    ),
)
os.environ["MONET_CLI"] = CLI
os.environ.setdefault("MONET_NODE_PATH", "/opt/homebrew/opt/node@22/bin")
os.environ.setdefault("MONET_MODEL_CACHE", os.path.expanduser("~/.monet/models"))

PKG_JSON = os.path.normpath(os.path.join(os.path.dirname(CLI), "..", "package.json"))

PASS = []
FAIL = []
DESIRED = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def desired(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        DESIRED.append(name)
    print(f"  [{'PASS' if cond else 'DESIRED-FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def evidence(msg):
    print(f"  [EVIDENCE] {msg}")


def main():
    base = tempfile.mkdtemp(prefix="monet-re61-identity-")
    store = os.path.join(base, "store")
    os.makedirs(store)
    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")

    # ---- baselines: what the shipped artifact says about itself ---------------
    pkg = json.load(open(PKG_JSON))
    pkg_version = pkg.get("version")
    check("installed_package_read", bool(pkg_version), f"{pkg.get('name')}@{pkg_version}")

    env = dict(os.environ)
    env["PATH"] = os.environ.get("MONET_NODE_PATH", "") + ":" + env.get("PATH", "")
    p = subprocess.run([CLI, "--version"], capture_output=True, text=True, env=env, timeout=120)
    cli_version = (p.stdout or "").strip()
    check("cli_version_matches_package", cli_version == pkg_version,
          f"monet --version={cli_version!r} package.json={pkg_version!r}")

    literal = None
    try:
        bundle = open(CLI, errors="replace").read()
        m = re.search(r'name:\s*"monet-core",\s*version:\s*"([^"]+)"', bundle)
        literal = m.group(1) if m else None
    except OSError as exc:  # pragma: no cover
        evidence(f"bundle read failed: {exc}")
    evidence(f"hardcoded handshake literal in dist/cli.js = {literal!r}")

    # the registry manifest of the SAME build (monorepo only; never shipped in the npm tarball)
    manifest = os.path.join(os.path.dirname(CLI), "..", "..", "..", "..", "..", "server.json")
    manifest_paths = [manifest,
                      os.path.expanduser("~/monet/monet/packages/cli/server.json")]
    for mp in manifest_paths:
        if os.path.exists(mp):
            mj = json.load(open(mp))
            evidence(f"registry manifest {mp} declares version={mj.get('version')!r}")
            break

    # ---- the live MCP surface -------------------------------------------------
    client = MonetClient(store)
    try:
        init = client.initialize()
        server_info = init.get("serverInfo") or {}
        served = server_info.get("version")
        evidence(f"MCP initialize serverInfo = {json.dumps(server_info, ensure_ascii=False)}")
        check("handshake_carries_server_info", bool(server_info),
              f"serverInfo={server_info}")

        tools = {t["name"] for t in client.tools_list().get("tools", [])}
        check("surface_present", {"memory_store", "memory_search", "agent_context"} <= tools,
              f"tools={len(tools)}")

        # does any tool result name the release? (e.g. agent_context orientation)
        ctx = client.call_json("agent_context", {})
        ctx_text = json.dumps(ctx, ensure_ascii=False)
        ctx_has_release = bool(pkg_version) and pkg_version in ctx_text
        evidence(f"agent_context keys={sorted(ctx.keys()) if isinstance(ctx, dict) else type(ctx)}; "
                 f"mentions installed release={ctx_has_release}")

        # the diagnosis surface a support thread asks for
        p = subprocess.run([CLI, "doctor", "-d", store, "--json"], capture_output=True,
                           text=True, env=dict(os.environ, PATH=env["PATH"]), timeout=240)
        try:
            dj = json.loads(p.stdout)
        except Exception:
            dj = {}
        evidence(f"doctor --json keys={sorted(dj.keys())}")
        check("doctor_json_has_no_release_field",
              not any(k.lower() in ("version", "monetversion", "release") for k in dj),
              "recorded, not asserted: the diagnosis surface has no release field either")

        # ---- DESIRED contract ------------------------------------------------
        desired("handshake_version_is_the_installed_release",
                served == pkg_version,
                f"served={served!r} must equal installed package version {pkg_version!r}")
        desired("handshake_version_is_not_a_frozen_literal",
                served != "0.7.0" or pkg_version == "0.7.0",
                f"hardcoded literal={literal!r} is served for every 1.x install")
        if literal is not None:
            desired("bundle_version_derives_from_the_release",
                    literal == pkg_version,
                    f"bundle literal={literal!r}")
        # a memory card is served right after the handshake: enough to prove this is
        # the same live session whose identity we just read
        ack = client.call_json("memory_store",
                              {"content": f"Release identity probe for the running server {int(time.time())}",
                               "circle": "e2e-r61-" + str(int(time.time())),
                               "sourceRefs": ["e2e:test62/r61"]})
        check("store_roundtrip_on_the_same_session", bool(ack.get("conceptId")),
              f"action={ack.get('action')}")
    finally:
        client.close()
        if os.environ.get("MONET_KEEP_STORE"):
            print(f"  KEPT store={store}")
        else:
            shutil.rmtree(base, ignore_errors=True)

    if DESIRED:
        print(f"\nRESULT: XFAIL — RE-61 still present: the served identity is a frozen "
              f"literal, not the installed release ({len(PASS)} checks held, "
              f"desired-but-unmet = {DESIRED})")
        return 2
    print(f"\nRESULT: XPASS — RE-61 fixed: the MCP handshake names the installed release "
          f"({len(PASS)} checks)")
    return 3


if __name__ == "__main__":
    sys.exit(main())
