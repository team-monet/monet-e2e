#!/usr/bin/env python3
"""RE-58 (upstream #107) — the SHIPPED 1.11.0 has no schema-version ceiling: a
store stamped ABOVE this build's supported schema opens, is bootstrapped, and is
served to the agent as if it were understood.

Why this test exists
--------------------
Upstream #107 ("The engine constructor has no schema-version ceiling: a
newer-than-supported store opens successfully where repair refuses it") states
its own limit verbatim:

    "Inferred, not reproduced. That the resulting failure is deferred to the
     first statement naming a column this build does not know is read off the
     code's structure. No fixture was built that stamps `user_version` above the
     ladder and opens the store, so the actual observed failure mode — which
     statement throws first, what the message says, and whether anything writes
     before it does — is not established here."

This test closes that gap on the published artifact (dist 1.11.0) using public
surfaces only (`monet doctor`, `monet repair`, `monet start` over MCP).

Measured on 1.11.0 (2026-09-15, isolated temp store)
---------------------------------------------------
- `monet start` on a store stamped `user_version = supported+1` with ZERO tables:
  **no refusal** — stderr says "Monet started"; the engine bootstrap creates 27
  tables and flips the journal to WAL; the agent then stores + searches normally
  and the row survives a second, independent session. `user_version` stays
  `supported+1`, so the store keeps claiming a schema this build cannot name.
  => no statement throws at all; the first write is the engine's own bootstrap.
- `monet doctor` on the same store: `Schema: <stamp> (supported: <N>)`,
  `Assessment: unknown` (rc 2).
- `monet repair --target …` on the same store REFUSES:
  "Store schema <stamp> is newer than supported schema <N>; refusing repair."
  => the asymmetry #107 reports, confirmed on the shipped binary.
- A real store with content, then stamped above the ceiling, is likewise opened
  and its pre-existing concept is returned to search by the older build.

Desired contract (asserted below — pre-registered flip candidate for the next
release bump): `monet start` refuses to open a store newer than this build.
PR #155 lands that ceiling in `main` (unreleased as of 1.11.0). The flip signal
is the REFUSAL only; #156 records that the fixed CLI still writes the circle map
before the refusal, so this test does not assert a write-free store.

Exit codes:
  0/1 = setup broke (test itself wrong)
  2   = XFAIL: no ceiling on the shipped build (above-ceiling store opens + is served)
  3   = XPASS: `monet start` refuses an above-ceiling store (fixed)
"""
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import CLI, NODE_PATH, MonetClient  # noqa: E402

ISSUE = "RE-58"
os.environ.setdefault("MONET_CLI", CLI)
os.environ.setdefault("MONET_NODE_PATH", NODE_PATH)
UPSTREAM = "#107 (ceiling) / #156 (circle-map write before the refusal)"

PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def run_cli(args, env=None, timeout=180):
    import subprocess

    e = dict(os.environ)
    if NODE_PATH:
        e["PATH"] = NODE_PATH + ":" + e.get("PATH", "")
    if env:
        e.update(env)
    p = subprocess.run([CLI] + args, capture_output=True, text=True, env=e, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def state(store):
    """Store facts read with stdlib sqlite3 (fixture inspection, not product probing)."""
    db = os.path.join(store, "monet.db")
    if not os.path.exists(db):
        return {"exists": False, "user_version": None, "n_tables": 0, "tables": [], "files": sorted(os.listdir(store))}
    con = sqlite3.connect(db)
    uv = con.execute("PRAGMA user_version").fetchone()[0]
    tables = sorted(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    obs = con.execute("SELECT count(*) FROM observations").fetchone()[0] if "observations" in tables else 0
    con.close()
    return {"exists": True, "user_version": uv, "n_tables": len(tables), "tables": tables,
            "observations": obs, "files": sorted(os.listdir(store))}


def stamp(store, version):
    con = sqlite3.connect(os.path.join(store, "monet.db"))
    con.execute(f"PRAGMA user_version={int(version)}")
    con.commit()
    con.close()


def journey(store):
    """Public-surface journey: start the MCP server against the stamped store.

    Returns (refused, served, detail). `served` means the server completed the
    MCP handshake and listed tools — i.e. this build accepted the store.
    """
    c = MonetClient(store)
    refused = served = False
    detail = {}
    try:
        try:
            init = c.initialize()
            served = True
            detail["server"] = (init.get("serverInfo") or {}).get("version")
            detail["tools"] = len(c.tools_list().get("tools", []))
        except RuntimeError as ex:
            refused = True
            detail["error"] = str(ex)[:200]
    finally:
        c.close()
        detail["stderr"] = c.stderr()
        detail["exit_code"] = c.proc.returncode
    return refused, served, detail


def main():
    base = tempfile.mkdtemp(prefix="monet-re58-e2e-")
    real = os.path.join(base, "real")
    bare = os.path.join(base, "bare")
    os.makedirs(real)
    check("isolated_store", base.startswith(tempfile.gettempdir()), f"base={base}")

    fixed = False
    bug_present = False
    try:
        # --- fixture A: a REAL store with content (the downgrade journey) ------
        c = MonetClient(real)
        try:
            c.initialize()
            seeded = c.call_json("memory_store", {
                "content": "RE58-MARKER: an observation stored while the store was still "
                           "on the supported schema, before it was stamped newer.",
                "circle": "e2e-re58",
                "sourceRefs": ["e2e:test58"],
            })
        finally:
            c.close()
        pre_real = state(real)
        check("A_real_store_built", pre_real["exists"] and pre_real["n_tables"] > 20 and pre_real["observations"] >= 1,
              f"tables={pre_real['n_tables']} obs={pre_real['observations']} uv={pre_real['user_version']}")
        real_seed_id = seeded.get("conceptId")

        # supported schema comes from the product's own doctor, not a hardcoded 13
        _rc, out, err = run_cli(["doctor", "-d", real])
        doc_real = out + err
        m = re.search(r"Schema:\s*(\d+)\s*\(supported:\s*(\d+)\)", doc_real)
        schema_line = next((l.strip() for l in doc_real.splitlines() if l.strip().startswith("Schema:")), "none")
        check("A_supported_schema_visible", bool(m), schema_line)
        if not m:
            return 1
        supported = int(m.group(2))
        stamp_v = supported + 1

        # --- fixture B: bare store, zero tables, stamped above the ceiling -----
        # (byte-for-byte the fixture upstream #156 reproduces with)
        os.makedirs(bare)
        con = sqlite3.connect(os.path.join(bare, "monet.db"))
        con.execute(f"PRAGMA user_version={stamp_v}")
        con.commit()
        con.close()
        pre_bare = state(bare)
        check("B_bare_pre_state", pre_bare["user_version"] == stamp_v and pre_bare["n_tables"] == 0,
              f"uv={pre_bare['user_version']} tables={pre_bare['n_tables']}")

        stamp(real, stamp_v)
        check("A_real_stamped", state(real)["user_version"] == stamp_v, f"uv={stamp_v} (supported {supported})")

        # --- stable invariants (hold before AND after the fix) -----------------
        rc_d, out_d, err_d = run_cli(["doctor", "-d", bare])
        doc = out_d + err_d
        check("B_doctor_reports_newer_schema", re.search(rf"Schema:\s*{stamp_v}\s*\(supported:\s*{supported}\)", doc),
              next((l.strip() for l in doc.splitlines() if l.strip().startswith("Schema:")), "none"))
        check("B_doctor_assessment_unknown", "Assessment: unknown" in doc)

        rc_r, out_r, err_r = run_cli(["repair", "-d", bare, "--target", "Xenova/bge-m3:cls:q8"])
        rep = out_r + err_r
        check("B_repair_refuses_newer_store", "newer than supported" in rep and rc_r != 0,
              f"rc={rc_r} msg={[l.strip() for l in rep.splitlines() if 'newer than supported' in l]}")

        # --- the journey: does `monet start` refuse the above-ceiling store? ---
        refused_a, served_a, det_a = journey(bare)
        print(f"    [arm A] refused={refused_a} served={served_a} exit={det_a.get('exit_code')} "
              f"stderr={det_a.get('stderr', '')[:160]!r}")
        refused_b, served_b, det_b = journey(real)
        print(f"    [arm B] refused={refused_b} served={served_b} exit={det_b.get('exit_code')} "
              f"stderr={det_b.get('stderr', '')[:160]!r}")

        post_bare, post_real = state(bare), state(real)

        if refused_a or refused_b:
            # ceiling present: assert the refusal is the documented one and that
            # the store was not re-versioned by it.
            check("refusal_names_both_versions",
                  "newer than supported" in (det_a.get("stderr", "") + det_b.get("stderr", "")),
                  f"A={refused_a} B={refused_b}")
            check("refusal_exit_nonzero",
                  det_a.get("exit_code") not in (None, 0) or det_b.get("exit_code") not in (None, 0),
                  f"A={det_a.get('exit_code')} B={det_b.get('exit_code')}")
            check("post_refusal_store_version_unchanged",
                  post_bare["user_version"] == stamp_v and post_real["user_version"] == stamp_v,
                  f"A={post_bare['user_version']} B={post_real['user_version']}")
            print(f"    post-refusal residue: bare tables={post_bare['n_tables']} "
                  f"(new: {[t for t in post_bare['tables'] if t not in pre_bare['tables']]}), "
                  f"files={post_bare['files']}  # #156 documents the circle-map write")
            fixed = not FAIL
        else:
            # ceiling absent: the store is accepted AND served. Verify the
            # reproduction itself (a failed reproduction = this test is wrong).
            bug_present = True
            print(f"    -> the above-ceiling store was accepted: bare tables "
                  f"{pre_bare['n_tables']}->{post_bare['n_tables']}, journal/file add "
                  f"{[f for f in post_bare['files'] if f not in pre_bare['files']]}")
            check("repro_bootstrap_wrote_tables", post_bare["n_tables"] > pre_bare["n_tables"],
                  f"{pre_bare['n_tables']}->{post_bare['n_tables']}")

            c = MonetClient(bare)
            try:
                c.initialize()
                r = c.call_json("memory_store", {
                    "content": "RE58-MARKER: written AFTER the store was stamped newer than "
                               "this build's supported schema.",
                    "circle": "e2e-re58",
                    "sourceRefs": ["e2e:test58"],
                })
                s = c.call_json("memory_search", {"query": "RE58-MARKER stamped newer than supported",
                                                  "circle": "e2e-re58", "limit": 3})
                hit_write = any(x.get("id") == r.get("conceptId") for x in (s.get("results") or []))
            finally:
                c.close()
            check("repro_write_and_search_on_newer_store", hit_write,
                  f"conceptId={r.get('conceptId')} hits={len(s.get('results') or [])}")

            c = MonetClient(real)
            try:
                c.initialize()
                s2 = c.call_json("memory_search", {"query": "RE58-MARKER observation stored while the store was still",
                                                   "circle": "e2e-re58", "limit": 3})
                hit_seed = any(x.get("id") == real_seed_id for x in (s2.get("results") or []))
            finally:
                c.close()
            check("repro_older_build_serves_pre_existing_rows", hit_seed,
                  f"seed={real_seed_id} hits={len(s2.get('results') or [])}")

            check("post_journey_store_version_unchanged",
                  state(bare)["user_version"] == stamp_v and state(real)["user_version"] == stamp_v,
                  f"A={state(bare)['user_version']} B={state(real)['user_version']}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if fixed:
        print(f"\nRESULT: XPASS {ISSUE} — `monet start` refuses a store newer than this build "
              f"(upstream {UPSTREAM})")
        return 3
    assert bug_present
    print(f"\nRESULT: XFAIL {ISSUE} — dist 1.11.0 has no schema ceiling: an above-ceiling store "
          f"opens, is bootstrapped and served, while `monet repair` refuses the same store "
          f"(upstream {UPSTREAM}; PR #155 unreleased)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
