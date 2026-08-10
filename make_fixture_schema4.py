#!/usr/bin/env python3
"""Create an old-schema fixture DB using the OLD monet CLI (1.2.4).

Spawns the old cli.js start against an empty fixture dir, completes the MCP
handshake, stores one observation (so the schema gets fully exercised), then
closes. Result: a real 1.2.4-era DB for schema-migration testing.

Requires an old @team-monet/monet@1.2.4 install in a prefix dir (see
README.md "Schema-7 fixture"). Point to it with MONET_OLD_CLI (defaults to
$MONET_TEST_DIR/prefix-old/...) and MONET_TEST_DIR (defaults to ~/.monet-test).
"""
import os
import subprocess
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import MonetClient, DATA, NODE_PATH

FIXTURE_DIR = os.environ.get("MONET_FIXTURE_DIR", os.path.join(DATA, "fixtures", "schema4"))
OLD_CLI = os.environ.get(
    "MONET_OLD_CLI",
    os.path.join(DATA, "prefix-old", "lib", "node_modules", "@team-monet", "monet", "dist", "cli.js"),
)


class OldMonetClient(MonetClient):
    def __init__(self, data_dir, cli, log_prefix="oldmonet"):
        env = dict(os.environ)
        if NODE_PATH:
            env["PATH"] = NODE_PATH + ":" + env.get("PATH", "")
        self.proc = subprocess.Popen(
            [cli, "start", "-d", data_dir],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self.data_dir = data_dir
        self.next_id = 1
        self.stderr_lines = []
        self._reader = threading.Thread(target=self._drain_stderr, daemon=True)
        self._reader.start()


def main():
    os.makedirs(FIXTURE_DIR, exist_ok=True)
    # verify old CLI works at all
    c = OldMonetClient(FIXTURE_DIR, OLD_CLI)
    try:
        init = c.initialize()
        print("OLD_INIT server=%s version=%s" % (init.get("serverInfo", {}).get("name"),
                                                 init.get("serverInfo", {}).get("version")))
        tools = c.tools_list()
        names = sorted(t["name"] for t in tools.get("tools", []))
        print("OLD_TOOLS(%d)" % len(names))
        r = c.call_json("memory_store", {"content": "schema four fixture observation", "circle": "e2e"})
        print("OLD_STORE conceptId=%s" % r.get("conceptId"))
    finally:
        c.close()
        if c.stderr_lines:
            print("--- old server stderr (tail) ---")
            print(c.stderr()[-800:])
    print("FIXTURE_READY", FIXTURE_DIR)


if __name__ == "__main__":
    main()
