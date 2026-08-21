#!/usr/bin/env python3
"""Scenario 11 (server surface): dashboard E2E smoke test (test20).

Pins the local-only read-only dashboard server (RE run 16 —
reverse-engineering/dashboard.md, findings RE-20..RE-22) with the harness.
The dashboard is NOT MCP — it is a plain HTTP server, so this test drives it
with raw sockets / urllib instead of MonetClient for the HTTP surface, and
uses MonetClient only to build a small populated store (arm F).

Arms:
A. empty-store shapes — no-DB dir: /api/graph exact VZ() empty shape
   (counts all 0, health nulls, empty lists), /api/entities {[],[]},
   /api/sources {sources:[],generatedAt}, static allowlist + no-store header
B. Host allowlist — evil.example.com and 127.0.0.2 -> 403; localhost and
   [::1] pass (DNS-rebinding defense)
C. 404 JSON shape on unknown path
D. snapshot lifecycle — after API requests the monet-dash-* temp dir holds
   zero .db files (per-request backup + unlink)
E. exit cleanup — SIGINT removes the whole monet-dash-* dir
F. populated store (via MCP): counts match stores; graphDensity formula
   (edgesLive/concepts, RE-21) pinned exactly; retire-guard Finding 21
   (memory_retire refused while an undismissed possible_duplicate_of pair
   flag exists -> memory_resolve pair dismissal -> retire succeeds) flips
   the et retired filter live (concepts 2->1, includeRetired=1 -> 2),
   proving snapshot-per-request freshness (no server-side cache)

GR-06: all content carries a fresh token; store dirs are unique per run.
"""
import glob
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
    """Raw HTTP GET with a custom Host header (connects to 127.0.0.1)."""
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
        # node's res.json() uses chunked TE — strip the chunk framing
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
    """Spawn `monet dashboard -d <dir>` with a fake `open` shim on PATH so no
    browser pops on the host, plus a drain thread for stdout/stderr."""
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


def dash_tmp_dirs():
    return set(glob.glob(os.path.join(tempfile.gettempdir(), "monet-dash-*")))


def main():
    TS = str(int(time.time()))

    # ===================== ARM A-E: empty store (no DB) =====================
    empty_dir = tempfile.mkdtemp(prefix="e2e-dash-empty-")
    port = free_port()
    log_path = os.path.join(tempfile.gettempdir(), f"e2e-dash-fakeopen-{TS}.log")
    before = dash_tmp_dirs()
    proc, out_lines, err_lines, shim_dir = start_dashboard(empty_dir, port, log_path)
    try:
        check("a_server_ready", wait_ready(port), f"port={port}")
        if not wait_ready(port):
            print("  SERVER LOG:", "\n".join(err_lines[-10:]))
            return 1

        # ---- A: empty-store shapes ----
        st, hd, body = raw_request(port, "/api/graph", host=f"localhost:{port}")
        g = json.loads(body.decode())
        check("a_graph_200", st == 200, f"status={st}")
        check("a_graph_generated_at", isinstance(g.get("generatedAt"), (int, float)),
              f"generatedAt={g.get('generatedAt')}")
        counts = g.get("counts", {})
        zero_keys = ["concepts", "observations", "edgesLive",
                     "edgesDismissed", "entities", "sessions", "contradictionsOpen",
                     "contradictionsResolved", "disputed", "dirty", "possibleDuplicatePairs"]
        check("a_counts_keys_present", set(zero_keys) <= set(counts.keys()),
              f"keys={sorted(set(zero_keys) - set(counts.keys()))}")
        check("a_counts_all_zero", all(counts.get(k) == 0 for k in zero_keys),
              f"counts={ {k: counts.get(k) for k in zero_keys} }")
        health = g.get("health", {})
        check("a_health_nulls", health.get("avgConfidence") is None and health.get("graphDensity") is None,
              f"health={health}")
        for lst in ["concepts", "observations", "edges", "contradictions", "sessions",
                    "revisionsCount", "circles", "aliases"]:
            if not isinstance(g.get(lst), list) or len(g.get(lst)) != 0:
                check(f"a_empty_{lst}", False, f"len={len(g.get(lst, []))}")
                break
        else:
            check("a_graph_empty_lists", True, "8 empty lists")

        st, hd, body = raw_request(port, "/api/entities", host=f"localhost:{port}")
        e = json.loads(body.decode())
        check("a_entities_empty", st == 200 and e.get("entities") == [] and e.get("links") == [],
              f"entities={e}")

        st, hd, body = raw_request(port, "/api/sources", host=f"localhost:{port}")
        # Sources subsystem retired in 1.7.0 -> /api/sources 404s there, but served
        # an empty shape on 1.6.x. Accept either (version-tolerant).
        if st == 200:
            so = json.loads(body.decode())
            check("a_sources_legacy_empty", so.get("sources") == [] and "generatedAt" in so,
                  f"sources={so}")
        else:
            check("a_sources_removed_404", st == 404, f"status={st} (sources retired in 1.7.0)")

        st, hd, body = raw_request(port, "/", host=f"localhost:{port}")
        check("a_root_200_html", st == 200 and "text/html" in hd.get("content-type", ""),
              f"status={st} ct={hd.get('content-type')}")
        cc = hd.get("cache-control", "")
        check("a_root_no_store", "no-store" in cc and "no-cache" in cc, f"cache-control={cc}")

        st, hd, body = raw_request(port, "/app.js", host=f"localhost:{port}")
        check("a_static_appjs_200", st == 200 and "javascript" in hd.get("content-type", ""),
              f"status={st} ct={hd.get('content-type')}")

        # ---- B: Host allowlist ----
        st, _, _ = raw_request(port, "/", host="evil.example.com")
        check("b_evil_host_403", st == 403, f"status={st}")
        st, _, body = raw_request(port, "/", host="evil.example.com")
        check("b_evil_403_shape", b"Forbidden" in body, f"body={body[:60]}")
        st, _, _ = raw_request(port, "/", host="127.0.0.2")
        check("b_127_0_0_2_403", st == 403, f"status={st}")
        st, _, _ = raw_request(port, "/", host=f"localhost:{port}")
        check("b_localhost_pass", st == 200, f"status={st}")
        st, _, _ = raw_request(port, "/", host=f"[::1]:{port}")
        check("b_ipv6_pass", st == 200, f"status={st}")

        # ---- C: 404 shape ----
        st, hd, body = raw_request(port, "/nonexistent", host=f"localhost:{port}")
        nf = json.loads(body.decode())
        check("c_404_status_shape", st == 404 and nf.get("error") == "Not found" and nf.get("pathname") == "/nonexistent",
              f"status={st} body={body[:80]}")

        # ---- D: snapshot lifecycle ----
        after = dash_tmp_dirs()
        new_dirs = after - before
        check("d_snapshot_dir_created", len(new_dirs) == 1, f"new_dirs={new_dirs}")
        snap_dir = next(iter(new_dirs)) if new_dirs else None
        if snap_dir:
            dbs = [f for f in os.listdir(snap_dir) if f.endswith(".db")]
            check("d_no_db_files_after_requests", len(dbs) == 0, f"leftover={dbs}")

        # ---- E: exit cleanup ----
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=15)
            check("e_server_exited_on_sigint", True, f"rc={proc.returncode}")
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            check("e_server_exited_on_sigint", False, "timeout, killed")
        time.sleep(0.8)
        check("e_tmp_dir_removed", snap_dir is not None and not os.path.exists(snap_dir),
              f"snap_dir={snap_dir}")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        # cleanup shim + store dirs
        for d in [shim_dir, empty_dir]:
            try:
                subprocess.run(["rm", "-rf", d])
            except Exception:
                pass

    # ============ ARM F: populated store — counts, density, retired filter ============
    store_dir = tempfile.mkdtemp(prefix="e2e-dash-store-")
    tok = TS
    try:
        c = MonetClient(store_dir)
        try:
            c.initialize()
            r1 = c.call_json("memory_store", {"content": f"The alpha queue budget for {tok} is 40 units.",
                                              "circle": f"e2e-dash-{tok}",
                                              "sourceRefs": [f"e2e:test20-alpha-{tok}"]})
            r2 = c.call_json("memory_store", {"content": f"The beta pipeline flag for {tok} is green.",
                                              "circle": f"e2e-dash-{tok}",
                                              "sourceRefs": [f"e2e:test20-beta-{tok}"]})
            check("f_concepts_stored", bool(r1.get("conceptId")) and bool(r2.get("conceptId")),
                  f"ids={r1.get('conceptId')},{r2.get('conceptId')}")
            keep_id = r1.get("conceptId")
            retire_id = r2.get("conceptId")
        finally:
            c.close()

        port2 = free_port()
        log2 = os.path.join(tempfile.gettempdir(), f"e2e-dash-fakeopen-{TS}-f.log")
        before2 = dash_tmp_dirs()
        proc2, out2, err2, shim2 = start_dashboard(store_dir, port2, log2)
        try:
            check("f_server_ready", wait_ready(port2), f"port={port2}")
            if not wait_ready(port2):
                print("  SERVER2 LOG:", "\n".join(err2[-10:]))
                return 1

            st, _, body = raw_request(port2, "/api/graph", host=f"localhost:{port2}")
            g2 = json.loads(body.decode())
            cnt = g2.get("counts", {})
            check("f_graph_concepts_2", cnt.get("concepts") == 2, f"concepts={cnt.get('concepts')}")
            check("f_graph_observations_2", cnt.get("observations") == 2,
                  f"observations={cnt.get('observations')}")
            h2 = g2.get("health", {})
            check("f_health_float", isinstance(h2.get("avgConfidence"), (int, float)),
                  f"avgConfidence={h2.get('avgConfidence')}")
            dens = h2.get("graphDensity")
            exp = cnt.get("edgesLive", 0) * 1.0 / cnt.get("concepts", 1)
            check("f_density_formula_re21", dens is not None and abs(dens - exp) < 1e-9,
                  f"density={dens} expected={exp} (edgesLive={cnt.get('edgesLive')})")

            # retire one concept while the dashboard is RUNNING — proves
            # snapshot-per-request freshness (RE-20: no server-side cache).
            # Finding 21: retire REFUSES while an undismissed possible_duplicate_of
            # pair flag exists ("erasing rather than answering"); the pair must be
            # dismissed through memory_resolve(conceptAId, conceptBId) first.
            c2 = MonetClient(store_dir)
            try:
                c2.initialize()
                rr = c2.call_json("memory_retire", {"id": retire_id, "circle": f"e2e-dash-{tok}"})
                err_txt = str(rr.get("_rawText", ""))
                check("f_retire_refused_pair_flag",
                      "cannot retire" in err_txt and "undismissed pair flag" in err_txt,
                      f"err={err_txt[:100]}")
                rs = c2.call_json("memory_resolve",
                                  {"conceptAId": keep_id, "conceptBId": retire_id,
                                   "circle": f"e2e-dash-{tok}"})
                check("f_pair_dismissed",
                      rs.get("action") == "pair-flags-dismissed" and rs.get("rowsUpdated", 0) >= 1,
                      f"ack={rs}")
                rr2 = c2.call_json("memory_retire", {"id": retire_id, "circle": f"e2e-dash-{tok}"})
                check("f_retire_ack", "Retired" in str(rr2.get("message", "")),
                      f"action={rr2.get('action')}")
            finally:
                c2.close()

            st, _, body = raw_request(port2, "/api/graph", host=f"localhost:{port2}")
            g3 = json.loads(body.decode())
            check("f_retired_hidden", g3.get("counts", {}).get("concepts") == 1,
                  f"concepts={g3.get('counts', {}).get('concepts')} (et filter)")
            st, _, body = raw_request(port2, "/api/graph?includeRetired=1", host=f"localhost:{port2}")
            g4 = json.loads(body.decode())
            check("f_include_retired_delta", g4.get("counts", {}).get("concepts") == 2,
                  f"concepts={g4.get('counts', {}).get('concepts')} (includeRetired=1)")
        finally:
            if proc2.poll() is None:
                proc2.send_signal(signal.SIGINT)
                try:
                    proc2.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc2.kill()
                    proc2.wait()
            subprocess.run(["rm", "-rf", shim2, store_dir])
    except Exception as ex:
        check("f_arm_exception", False, str(ex)[:200])

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
