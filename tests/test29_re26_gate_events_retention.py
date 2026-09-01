#!/usr/bin/env python3
"""RE-26 (gates.md): gate instrumentation has NO retention/pruning.

Reverse-engineering finding (v0.9.0 readable TS): `gate_events` recorded one
row per intercepted action — including silences — from BOTH matchers
(`mechanical` = gateQuery, `recognized` = stage_lookup). The source comment was
explicit that "on a busy store it will become the largest one" (2–3 orders of
magnitude more rows than `resolution_events`; it grows with agent activity,
not memory volume). Retention was deferred, with `SOURCE_ATTEMPT_EVENT_RETENTION`
(128 immutable receipts/source) named as the precedent to copy.

In 1.7.0 the gate-instrumentation redesign replaced `gate_events` with the
store-backed `governed_moments` table (a moment opens for every intercepted
action, incl. silences, and closes with an outcome at PostToolUse). In 1.11.0
the moment ledger moved LAZY / spool-based: `governed_moments` is minted only
via `conformance_ask`, and plain `stage_lookup` appends MomentSpool records to
`<store>/moments.jsonl` instead. The retention question is UNCHANGED in spirit —
does the moment record grow unboundedly with no prune/retention surface?

This test documents the DESIRED contract: gate instrumentation has a
retention/pruning mechanism — either a CLI/doctor/MCP surface that reports and
prunes it, or an automatic cap — so a busy store does not accumulate unbounded
instrumentation. It measures the spool's interception lines as the busied-moment
proxy (the old eager-fold `governed_moments` count is obsolete on 1.11.0).

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: the moment record still accumulates unboundedly with no prune surface
  3   = XPASS: a retention/prune surface exists, or events are auto-capped
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient

ISSUE = "RE-26"
CLI = os.environ.get("MONET_CLI") or "/Users/codalee/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js"
NODE = os.environ.get("MONET_NODE_PATH") or "/opt/homebrew/opt/node@22/bin"

os.environ["MONET_CLI"] = CLI
os.environ["MONET_NODE_PATH"] = NODE

TS = str(int(time.time()))
STAGE = f"e2e-re26-stage-{TS}"
# Fire more than the 128-receipt retention precedent the source names, so an
# auto-cap at that bound would be caught; 130 lookups is a "busy store" sample.
N_FIRES = 130

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def sql(db, query):
    out = subprocess.run(["sqlite3", db, query], capture_output=True, text=True)
    return out.stdout.strip()


def main():
    base = tempfile.mkdtemp(prefix="monet-re26-e2e-")
    store = os.path.join(base, "store")
    os.makedirs(store)
    db = os.path.join(store, "monet.db")

    # Isolation guard: assert the prod store is not this path.
    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")

    bug_fixed = False
    try:
        c = MonetClient(store)
        try:
            c.initialize()

            # ---- setup: a real stage + an advisory rule bound to it ----
            r = c.call_json("memory_declare", {
                "species": "stage", "stage": STAGE,
                "patterns": ["e2e deploy to production"],
                "sourceRefs": ["e2e:test29"],
            })
            check("stage_declared", r.get("species") == "stage" and r.get("stage", {}).get("name") == STAGE,
                  f"resp={r.get('stage')}")

            r = c.call_json("memory_declare", {
                "species": "rule", "stage": STAGE, "scope": "domain",
                "content": "Run the release checklist before any production deploy.",
                "severity": "advisory", "sourceRefs": ["e2e:test29"],
            })
            check("rule_declared", r.get("species") == "rule", f"resp={r}")

            # A hit returns the bound rule, proving the gate is actually live.
            hit = c.call_json("stage_lookup", {"stage": STAGE})
            check("stage_lookup_hit_returns_rule",
                  hit.get("matched") is True and len(hit.get("rules") or []) >= 1,
                  f"rules={len(hit.get('rules') or [])}")

            # ---- generate a busy store's worth of gate activity ----
            for i in range(N_FIRES):
                c.call_json("stage_lookup", {"stage": STAGE})
        finally:
            c.close()

        # Measure moment accumulation. 1.11.0 made the moment ledger LAZY / spool-based:
        # `stage_lookup` no longer folds into the `governed_moments` table eagerly (that
        # table is minted only via `conformance_ask`); instead the interceptor appends a
        # MomentSpool record per lookup to <store>/moments.jsonl — one `interception` +
        # `read` per lookup that returns rules, plus `outcome` on close. RE-26's retention
        # question is UNCHANGED in spirit: does the moment record grow unboundedly with no
        # prune/retention surface? The spool is the truth (moment-ledger.ts: "NOTHING EVER
        # SHORTENS THE SPOOL, AND NO MECHANISM HERE RECLAIMS ITS SPACE ... Growth is
        # therefore unbounded in principle"). Count the spool's interception lines as the
        # busied-moment proxy (a `governed_moments` table may not exist until conformance_ask).
        spool = os.path.join(store, "moments.jsonl")
        spool_lines = 0
        if os.path.exists(spool):
            import json as _json
            for ln in open(spool):
                try:
                    if _json.loads(ln).get("kind") == "interception":
                        spool_lines += 1
                except Exception:
                    pass
        cnt = spool_lines
        check("moment_record_accumulated", cnt >= N_FIRES, f"spool interceptions={cnt} (fired {N_FIRES}+1)")

        # ---- DESIRED contract: a retention/prune surface exists ----
        # Enumerate the CLI + MCP surfaces that could read/prune gate_events.
        surfaces = {}
        for cmd, args in [
            ("gate", ["--help"]), ("doctor", ["--help"]), ("status", ["--help"]),
            ("resegment", ["--help"]), ("root", ["--help"]),
        ]:
            a = [CLI] + ([] if cmd == "root" else [cmd]) + args
            out = subprocess.run(a, capture_output=True, text=True).stdout
            surfaces[cmd] = out

        # MCP tool surface: any tool that reads/prunes gate_events?
        c2 = MonetClient(store)
        try:
            c2.initialize()
            tools = {t["name"] for t in c2.tools_list().get("tools", [])}
        finally:
            c2.close()

        import re
        retention_pat = re.compile(r"prun|retain|retention|trim|gate[-_]event|governed[-_]moment|moment", re.IGNORECASE)
        cli_surface = any(retention_pat.search(v) for v in surfaces.values())
        # None of the MCP tools are named for gate events / governed moments.
        mcp_surface = any(retention_pat.search(t) for t in tools)
        retention_surface_exists = cli_surface or mcp_surface
        print(f"  [RE-26] governed_moments_count={cnt} cli_surface={cli_surface} "
              f"mcp_surface={mcp_surface} tools_with_gate={[t for t in sorted(tools) if 'gate' in t.lower() or 'moment' in t.lower()]}")

        # DESIRED: either a prune/retention surface, or an automatic cap.
        auto_capped = cnt < N_FIRES
        bug_fixed = retention_surface_exists or auto_capped
        print(f"  [RE-26] retention_surface_exists={retention_surface_exists} "
              f"auto_capped={auto_capped} bug_fixed={bug_fixed}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if bug_fixed:
        print(f"\nRESULT: XPASS {ISSUE} — a retention/prune surface or auto-cap exists (bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — governed_moments grows unboundedly with no retention/prune surface "
          f"({len(PASS)} setup checks passed)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
