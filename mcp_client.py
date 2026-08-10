#!/usr/bin/env python3
"""Minimal MCP stdio client for Monet E2E tests (no external deps).

Implements the MCP JSON-RPC protocol over stdin/stdout:
  initialize -> notifications/initialized -> tools/list -> tools/call
Newline-delimited JSON-RPC 2.0. Server stderr is captured separately so
startup logs never corrupt the protocol stream.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time

# --- Environment / resolution -------------------------------------------------
# MONET_CLI: path to the Monet CLI (cli.js). Defaults to `monet` on PATH.
# MONET_NODE_PATH: optional node bin dir to prepend to PATH (e.g. node@22).
# MONET_TEST_DIR: where test data (SQLite DB) lives. Defaults to ~/.monet-test.
CLI = os.environ.get("MONET_CLI") or shutil.which("monet") or "monet"
NODE_PATH = os.environ.get("MONET_NODE_PATH", "")
DATA = os.environ.get("MONET_TEST_DIR", os.path.expanduser("~/.monet-test"))


class MonetClient:
    def __init__(self, data_dir, log_prefix="monet"):
        env = dict(os.environ)
        if NODE_PATH:
            env["PATH"] = NODE_PATH + ":" + env.get("PATH", "")
        self.proc = subprocess.Popen(
            [CLI, "start", "-d", data_dir],
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

    def _drain_stderr(self):
        for line in self.proc.stderr:
            self.stderr_lines.append(line.decode("utf-8", "replace").rstrip())

    def _send(self, obj):
        self.proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def _read_line(self, timeout=60):
        """Read one stdout line with timeout (non-blocking via select loop)."""
        import select

        deadline = time.time() + timeout
        buf = b""
        while time.time() < deadline:
            r, _, _ = select.select([self.proc.stdout], [], [], 0.5)
            if r:
                chunk = os.read(self.proc.stdout.fileno(), 65536)
                if not chunk:
                    return None
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    return line.decode("utf-8", "replace")
        return None

    def request(self, method, params=None, timeout=60):
        mid = self.next_id
        self.next_id += 1
        msg = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)
        while True:
            line = self._read_line(timeout=timeout)
            if line is None:
                raise RuntimeError("server closed stdout / timeout; stderr=" + self.stderr()[-5:])
            try:
                resp = json.loads(line)
            except json.JSONDecodeError:
                # non-protocol banner line — log and skip
                print(f"[stray stdout] {line}", file=sys.stderr)
                continue
            if resp.get("id") != mid:
                continue
            if "error" in resp:
                raise RuntimeError(f"MCP error {resp['error']}")
            return resp.get("result")

    def notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)

    def initialize(self, protocol_version="2025-06-18"):
        result = self.request(
            "initialize",
            {
                "protocolVersion": protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "monet-e2e-test", "version": "0.1.0"},
            },
        )
        self.notify("notifications/initialized")
        return result

    def tools_list(self):
        return self.request("tools/list")

    def call(self, tool, arguments=None, timeout=180):
        return self.request("tools/call", {"name": tool, "arguments": arguments or {}}, timeout=timeout)

    def call_json(self, tool, arguments=None, timeout=180):
        """Call a tool and parse the JSON inside the first text content block."""
        raw = self.call(tool, arguments, timeout=timeout)
        blocks = raw.get("content") if isinstance(raw, dict) else []
        for b in blocks or []:
            if b.get("type") == "text":
                try:
                    return json.loads(b["text"])
                except (json.JSONDecodeError, KeyError):
                    return {"_rawText": b.get("text", "")}
        return raw

    def stderr(self):
        return "\n".join(self.stderr_lines[-20:])

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
            self.proc.wait()


def main():
    """Smoke check: spawn, initialize, list tools."""
    data_dir = sys.argv[1] if len(sys.argv) > 1 else DATA
    c = MonetClient(data_dir)
    try:
        init = c.initialize()
        print("INIT_OK protocol=%s server=%s" % (init.get("protocolVersion"), init.get("serverInfo", {}).get("name")))
        tools = c.tools_list()
        names = sorted(t["name"] for t in tools.get("tools", []))
        print("TOOLS(%d): %s" % (len(names), ", ".join(names)))
    finally:
        c.close()
        if c.stderr_lines:
            print("--- server stderr (tail) ---")
            print(c.stderr())


if __name__ == "__main__":
    main()
