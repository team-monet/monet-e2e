#!/usr/bin/env python3
"""RE-33 (statement-trace.md): slow-queries.jsonl is write-only — no surface reads it.

Reverse-engineering finding (v0.9.0 readable TS): the statement tracer has TWO
outputs. The in-flight marker (`inflight-<pid>-<seq>.json`) HAS a consumer —
`readInflightStatements` names the lock holder in the storage.ts lock-contention
path. The slow log (`slow-queries.jsonl`) has NONE — nothing in doctor/CLI/MCP
reads or surfaces it, so the retrieval-degradation diagnosis it was built to
provide ("search gets worse as the corpus grows") is unreadable.

This test documents the DESIRED contract: a doctor/CLI/MCP surface reads and
surfaces the slow log (like `readInflightStatements` does for the marker).

CONTROL: with `MONET_TRACE_SQL=1`, the tracer writes its in-flight marker into
the store dir — proving the instrument is active and its artifacts live there.
With tracing off, no marker appears. The slow log is the sibling output.

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: no doctor/CLI/MCP surface reads/surfaces the slow log
  3   = XPASS: a surface now reads/surfaces the slow log (bug appears fixed)
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient

ISSUE = "RE-33"
CLI = os.environ.get("MONET_CLI") or "/Users/codalee/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js"
NODE = os.environ.get("MONET_NODE_PATH") or "/opt/homebrew/opt/node@22/bin"

os.environ["MONET_CLI"] = CLI
os.environ["MONET_NODE_PATH"] = NODE

TS = str(int(time.time()))
SURFACE_PAT = re.compile(r"slow[-_ ]quer|statement[-_ ]trace|trace[-_ ]sql|in[-_ ]?flight", re.IGNORECASE)

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def run(args, env=None):
    e = dict(os.environ)
    e["PATH"] = NODE + ":" + e.get("PATH", "")
    if env:
        e.update(env)
    return subprocess.run(args, capture_output=True, text=True, env=e)


def main():
    base = tempfile.mkdtemp(prefix="monet-re33-e2e-")
    store = os.path.join(base, "store")
    os.makedirs(store)
    db = os.path.join(store, "monet.db")

    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")

    bug_fixed = False
    try:
        # ---- CONTROL: MONET_TRACE_SQL=1 makes the tracer write its marker ----
        os.environ["MONET_TRACE_SQL"] = "1"
        c = MonetClient(store)
        try:
            c.initialize()
            c.call_json("memory_store", {
                "content": f"slow-log surface probe concept {TS}.",
                "circle": f"e2e-re33-{TS}", "sourceRefs": ["e2e:test31"],
            })
        finally:
            c.close()
        time.sleep(0.3)

        trace_files = [f for f in os.listdir(store) if f.startswith("inflight") or f.startswith("slow")]
        marker_written = any(f.startswith("inflight") for f in trace_files)
        slow_written = any(f.startswith("slow") for f in trace_files)
        check("tracer_active_inflight_marker", marker_written, f"trace_files={trace_files}")
        print(f"  [RE-33] trace_files={trace_files} slow_log_written={slow_written}")

        # ---- THE bug assertion: some surface must read/surface the slow log ----
        # Enumerate every CLI surface + the doctor output + the MCP tools.
        cli_texts = {}
        for cmd, args in [
            ("doctor", ["-d", store, "--json"]),
            ("doctor", ["--help"]),
            ("status", ["--help"]),
            ("gate", ["--help"]),
            ("resegment", ["--help"]),
            ("root", ["--help"]),
        ]:
            a = [CLI] + ([] if cmd == "root" else [cmd]) + args
            r = run(a)
            cli_texts[f"{cmd} {' '.join(args[:1])}"] = (r.stdout or "") + (r.stderr or "")

        c2 = MonetClient(store)
        try:
            c2.initialize()
            tools = {t["name"] for t in c2.tools_list().get("tools", [])}
        finally:
            c2.close()

        surface_hits = {}
        for label, text in cli_texts.items():
            if SURFACE_PAT.search(text):
                surface_hits[label] = True
        mcp_hit = [t for t in tools if SURFACE_PAT.search(t)]
        surface_exists = bool(surface_hits) or bool(mcp_hit)
        print(f"  [RE-33] cli_surface_hits={list(surface_hits)} mcp_tools_hit={mcp_hit}")

        # DESIRED: a surface reads/surfaces the slow log.
        bug_fixed = surface_exists
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if bug_fixed:
        print(f"\nRESULT: XPASS {ISSUE} — a surface now reads/surfaces the slow log (bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — slow-queries.jsonl is write-only: no doctor/CLI/MCP surface "
          f"reads it ({len(PASS)} setup checks passed)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
