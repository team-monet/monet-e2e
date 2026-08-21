#!/usr/bin/env python3
"""RE-21 (dashboard.md): graphDensity includes possible_duplicate_of edges.

Reverse-engineering finding: `/api/graph` computes
`graphDensity = edgesLive / concepts`, and `edgesLive` counts ALL live
`memory_edge` rows INCLUDING `possible_duplicate_of` edges (a dedup-resolution
signal, not a structural/knowledge edge). On the 75 MB E2E store that was
184/5751 ≈ 3.2% of edges, so "graph density" slightly overstates structural
density (reverse-engineering/dashboard.md, RE-21).

This test documents the DESIRED contract: graphDensity should measure
STRUCTURAL density — i.e. `(edgesLive - live possible_duplicate_of edges) /
concepts` — excluding dedup pair-flag edges.

To produce a possible_duplicate_of pair deterministically, two same-circle
`memory_store` calls with a shared distinctive token but distinct sentence
structure land in the ambiguous band and get a bidirectional
`possible_duplicate_of` pair flag (3/3 in run 17; test20 Finding 21).

Exit codes:
  0/1 = normal pass/fail (setup broke -> the test itself is wrong)
  2   = XFAIL: bug still present (graphDensity counts dup edges) — expected
  3   = XPASS: bug appears fixed (graphDensity excludes dup edges)
"""
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient, CLI, NODE_PATH

ISSUE = "RE-21"
TS = str(int(time.time()))
CIRCLE = f"e2e-re21-{TS}"
TOK = f"re21-{TS}"

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def raw_request(port, path, host=None):
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    host_hdr = host or f"127.0.0.1:{port}"
    req = f"GET {path} HTTP/1.1\r\nHost: {host_hdr}\r\nConnection: close\r\n\r\n"
    s.sendall(req.encode())
    data = b""
    while True:
        try:
            chunk = s.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        data += chunk
    s.close()
    head, _, body = data.partition(b"\r\n\r\n")
    status = int(head.split(b" ")[1])
    headers = {}
    for line in head.split(b"\r\n")[1:]:
        if b":" in line:
            k, v = line.split(b":", 1)
            headers[k.strip().lower().decode()] = v.strip().decode()
    if headers.get("transfer-encoding", "").lower() == "chunked":
        out = b""
        rest = body
        while rest:
            size_line, _, rest = rest.partition(b"\r\n")
            try:
                size = int(size_line.split(b";")[0].strip(), 16)
            except ValueError:
                break
            if size == 0:
                break
            out += rest[:size]
            rest = rest[size + 2:]
        body = out
    return status, headers, body


def start_dashboard(data_dir, port, log_path):
    shim_dir = tempfile.mkdtemp(prefix="e2e-dash-shim-")
    open_sh = os.path.join(shim_dir, "open")
    with open(open_sh, "w") as f:
        f.write("#!/bin/sh\necho FAKE_OPEN_SKIP: $@ >> " + log_path + "\nexit 0\n")
    os.chmod(open_sh, 0o755)
    env = dict(os.environ)
    env["PATH"] = shim_dir + ":" + (NODE_PATH + ":" if NODE_PATH else "") + env.get("PATH", "")
    env["PORT"] = str(port)
    proc = subprocess.Popen([CLI, "dashboard", "-d", data_dir],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    out_lines, err_lines = [], []

    def drain(pipe, sink):
        for line in pipe:
            sink.append(line.decode("utf-8", "replace").rstrip())

    threading.Thread(target=drain, args=(proc.stdout, out_lines), daemon=True).start()
    threading.Thread(target=drain, args=(proc.stderr, err_lines), daemon=True).start()
    return proc, out_lines, err_lines, shim_dir


def wait_ready(port, timeout=30):
    # Probe /api/graph (served on both 1.6.x and 1.7.x). Do NOT probe /api/sources:
    # the sources subsystem was retired in 1.7.0 and that endpoint now 404s.
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            st, _, _ = raw_request(port, "/api/graph", host=f"localhost:{port}")
            if st == 200:
                return True
        except (OSError, ValueError):
            pass
        time.sleep(0.3)
    return False


def main():
    store_dir = tempfile.mkdtemp(prefix="e2e-re21-store-")
    bug_fixed = False
    try:
        # ---- build the store: 2 similar concepts -> possible_duplicate_of pair ----
        c = MonetClient(store_dir)
        try:
            c.initialize()
            # Distinct sentence structure + a shared distinctive token lands the
            # pair in the ambiguous band -> possible_duplicate_of pair flag.
            r1 = c.call_json("memory_store", {
                "content": f"The alpha queue budget for {TOK} is 40 units.",
                "circle": CIRCLE,
                "sourceRefs": [f"e2e:test27-alpha-{TS}"],
            })
            r2 = c.call_json("memory_store", {
                "content": f"The beta pipeline flag for {TOK} is green.",
                "circle": CIRCLE,
                "sourceRefs": [f"e2e:test27-beta-{TS}"],
            })
            check("stored_2_concepts", bool(r1.get("conceptId")) and bool(r2.get("conceptId")),
                  f"ids={r1.get('conceptId')},{r2.get('conceptId')}")
            check("two_distinct_concepts", r1.get("conceptId") != r2.get("conceptId"),
                  f"a={r1.get('conceptId')} b={r2.get('conceptId')}")
        finally:
            c.close()

        # ---- read the graph via the dashboard ----
        port = free_port()
        log_path = os.path.join(tempfile.gettempdir(), f"e2e-re21-fakeopen-{TS}.log")
        proc, out_lines, err_lines, shim_dir = start_dashboard(store_dir, port, log_path)
        try:
            check("server_ready", wait_ready(port), f"port={port}")
            if not wait_ready(port):
                print("  SERVER LOG:", "\n".join(err_lines[-10:]))
                return 1

            st, _, body = raw_request(port, "/api/graph", host=f"localhost:{port}")
            g = json.loads(body.decode())
            cnt = g.get("counts", {})
            edges = g.get("edges", [])
            concepts = cnt.get("concepts")
            edges_live = cnt.get("edgesLive")
            dup_pairs = cnt.get("possibleDuplicatePairs")
            density = g.get("health", {}).get("graphDensity")

            dup_edges = [e for e in edges if e.get("type") == "possible_duplicate_of"]
            dup_edge_count = len(dup_edges)

            check("graph_concepts_2", concepts == 2, f"concepts={concepts}")
            check("setup_dup_pairs_present", dup_pairs is not None and dup_pairs >= 1,
                  f"possibleDuplicatePairs={dup_pairs}")
            check("setup_dup_edges_live", dup_edge_count >= 1,
                  f"live possible_duplicate_of edges={dup_edge_count}")
            check("setup_edges_array_matches_count", len(edges) == edges_live,
                  f"len(edges)={len(edges)} edgesLive={edges_live}")

            # ---- THE bug assertion (desired contract) ----
            # Structural density should exclude dedup pair-flag edges:
            #   correct = (edgesLive - dup_edges) / concepts
            # Buggy formula: edgesLive / concepts (dup edges inflate it).
            structural = (edges_live - dup_edge_count) * 1.0 / concepts if concepts else 0.0
            bug_fixed = density is not None and abs(density - structural) < 1e-9
            print(f"  [RE-21] edgesLive={edges_live} dupEdges={dup_edge_count} "
                  f"concepts={concepts} graphDensity={density} "
                  f"structural_density={structural:.6f} bug_fixed={bug_fixed}")
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            for d in [shim_dir, store_dir]:
                try:
                    subprocess.run(["rm", "-rf", d])
                except Exception:
                    pass
    except Exception as ex:
        check("arm_exception", False, str(ex)[:200])

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if bug_fixed:
        print(f"\nRESULT: XPASS {ISSUE} — graphDensity excludes possible_duplicate_of edges (bug appears fixed)")
        return 3
    print(f"\nRESULT: XFAIL {ISSUE} — graphDensity still counts possible_duplicate_of edges ({len(PASS)} setup checks passed)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
