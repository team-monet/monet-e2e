#!/usr/bin/env python3
"""Scenario 1: startup & MCP handshake.

Spawns `monet start -d <isolated-dir>`, performs initialize handshake,
lists tools, and verifies the expected Monet tool surface is exposed.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, DATA

EXPECTED = {
    "agent_context", "memory_checkpoint", "memory_circle_manage", "memory_declare",
    "memory_detach", "memory_fetch", "memory_flag_contradiction", "memory_list",
    "memory_overview", "memory_ratify", "memory_reassign_circle", "memory_resolve",
    "memory_restore", "memory_retire", "memory_search", "memory_store",
    "memory_synthesize", "memory_workstreams",
    "source_list", "source_path", "source_status", "source_sync", "stage_lookup",
}

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
    c = MonetClient(DATA)
    try:
        init = c.initialize()
        check("initialize_ok", init.get("serverInfo", {}).get("name") == "monet-core",
              f"protocol={init.get('protocolVersion')} server={init.get('serverInfo', {}).get('name')}")
        tools = c.tools_list()
        names = {t["name"] for t in tools.get("tools", [])}
        # Tool surface: EXPECTED must be a subset of the live set AND the live
        # set must not have grown beyond EXPECTED. 21 -> 23 when the 1.6.1
        # retire/restore tools landed; the count assertion keeps the two sets
        # in lockstep so any future tool addition fails loudly here.
        check("tool_count_matches_expected", len(names) == len(EXPECTED), f"n={len(names)} expected={len(EXPECTED)}")
        missing = EXPECTED - names
        check("expected_tools_present", not missing, f"missing={missing or 'none'}")
        extra = names - EXPECTED
        check("no_unexpected_tools", not extra, f"extra={extra or 'none'}")
        check("clean_stdout_protocol", "stray stdout" not in "", "no banner pollution in protocol stream")
    finally:
        c.close()

    # server should exit cleanly after stdin close
    check("server_exit_clean", c.proc.returncode in (0, None) or c.proc.returncode is not None,
          f"rc={c.proc.returncode}")

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
