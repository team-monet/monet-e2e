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

Desired contract (asserted below — pre-registered flip candidate, but ONLY for a
release whose contents actually include the #155 ceiling change; a version bump
alone does not flip this guard): `monet start` refuses to open a store newer than
this build.
The ceiling fix is PR #155. ~~which is **OPEN and NOT merged**~~ **[CORRECTED
2026-09-19, run 121 — the run-116/117/118 claim was superseded: #155 is now
**MERGED** at `2026-09-18T23:22:24Z`, `main` HEAD moved `9fa38c2` → `d920bc2`
(direct `gh pr view 155 --json state,mergedAt,headRefOid` this run). The fix is
still in **NO published release** — 1.11.0 shipped 2026-09-01, before the merge
— so the guard correctly stays XFAIL on the shipped bundle: 0 occurrences of
`readStoredSchemaVersion` / `refusing to open` / `newer than this build` remain.
The flip contract is unchanged (a RELEASE containing the fix, not a version
bump). What run 121 added is the first execution of this guard against a build
that CONTAINS the fix: a source bundle built from `d920bc2` (esbuild, via
`coverage-build.mjs`) refuses on **all four arms** — `verdict=xpass`, exit 3,
`user_version` unchanged on every arm, refusal text
"Store schema 14 is newer than supported schema 13; refusing to open. Upgrade
Monet first." on the `null`-preflight stray shapes (orphan `-wal`, hot
`-journal`) too. So the next release carrying #155 should flip this guard
cleanly; the pre-release prediction is recorded in
`reverse-engineering/schema-migration.md`. The flip signal is the REFUSAL only;
#156 records that the fixed CLI still writes the circle map before the refusal,
so this test does not assert a write-free store — **and run 121 measured that
residue on the FIXED build for the first time** (see schema-migration.md).]

Flip-time arm set and classification (added 2026-09-18, run 118)
----------------------------------------------------------------
Run 117 folded the round-4 review's *measured* evidence into the flip contract
(`reverse-engineering/schema-migration.md` §Flip-time assertion constraints).
Two of those constraints are about THIS guard, and the guard did not honour them:

1. The fix **branches on the store's sidecar shape**; the shapes that route
   through the fix's least-verified `null` preflight (orphan `-wal` without
   `-shm`; `-journal` present) were **not probed at all** — the two original arms
   (bare header store, real header store) both take the conclusive header path,
   and a release can regress the `null`/live-recheck path unnoticed.
2. On those shapes the ceiling is decided only **after the write port opens**, so
   a refusal can surface as `database is locked`. The old code treated ANY
   `RuntimeError` from `initialize()` as "refused" and, if *any* arm's stderr
   carried the refusal text, printed **XPASS** — i.e. a lock or a timeout could be
   reported as *the fix having landed*. Constraint 2 says a lock result is
   **inconclusive: neither flip-failure nor flip-success**.

So the guard now runs **four arms sequentially** (single server process at a
time, never concurrent — constraint 2's lock-free requirement):

| arm | fixture | fixed-build sidecar branch |
|---|---|---|
| `A_bare_header` | bare store, `user_version` stamped, stdlib clean close | header (offset 60) |
| `B_real_header` | real MCP-built store, then stamped | header (offset 60) |
| `S1_orphan_wal` | `monet.db` + `monet.db-wal`, **no `-shm`** (authentic: copied out of a live WAL connection) | `null` → live port |
| `S2_hot_journal` | `monet.db` + `monet.db-journal` (authentic hot journal: copied mid-transaction) | `null` → live port |

Per-arm state is `served` / `ceiling_refused` (that arm's OWN stderr carries the
refusal text) / `lock` / `failure`. Verdicts:

- all four `served`  → **XFAIL (2)**: bug present.
- all four `ceiling_refused` → **XPASS (3)**: fix present, and asserted
  per-arm — refusal message names both versions, non-zero exit, `user_version`
  unchanged; residue (tables/sidecars) is printed as a **measurement**, never
  asserted (constraint 3: `-journal`/asymmetric stores are converted *before* the
  refusal, so write-freeness does not hold on every shape).
- any `lock`/`failure` arm while a flip is pending, or a mixed
  refused/served set → **INCONCLUSIVE (4)**: never flips, does not fail the
  suite; re-run on a quiet machine.

Exit codes:
  0/1 = setup broke (test itself wrong)
  2   = XFAIL: no ceiling on the shipped build (above-ceiling store opens + is served)
  3   = XPASS: `monet start` refuses an above-ceiling store on every arm (fixed)
  4   = INCONCLUSIVE: some arm did not reach a verdict (lock/timeout/partial fix)
"""
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

CEILING_RE = re.compile(r"newer than supported")
LOCK_RE = re.compile(r"database is locked|SQLITE_BUSY", re.I)
ARMS_OK = ("served", "ceiling_refused")

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
    """Store facts read with stdlib sqlite3 (fixture inspection, not product probing).

    NOTE: opening a WAL store in place materializes `-shm` and may checkpoint the
    `-wal` away, i.e. it DESTROYS a stray-sidecar fixture. Never call this on a
    stray arm — use `probe_copy()` there.
    """
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


def probe_copy(store):
    """`state()` of a COPY of the store — shape-preserving fixture inspection."""
    tmp = tempfile.mkdtemp(prefix="monet-re58-verify-")
    dst = os.path.join(tmp, "copy")
    shutil.copytree(store, dst)
    try:
        return state(dst)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def sidecars(store):
    """Files present in the store dir, bare names (the fix's shape discriminator)."""
    return sorted(os.listdir(store)) if os.path.isdir(store) else []


def stamp(store, version):
    con = sqlite3.connect(os.path.join(store, "monet.db"))
    con.execute(f"PRAGMA user_version={int(version)}")
    con.commit()
    con.close()


def make_orphan_wal(store, version):
    """Arm S1: `monet.db` + `monet.db-wal`, NO `-shm`, stamped above the ceiling.

    Built by copying `monet.db` + `monet.db-wal` out of a STILL-OPEN WAL
    connection, so the WAL holds real frames and the `-shm` is never copied. The
    fix routes this shape through its `null` preflight (live port decides).
    """
    os.makedirs(store)
    src = store + ".src"
    os.makedirs(src)
    db = os.path.join(src, "monet.db")
    con = sqlite3.connect(db, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(f"PRAGMA user_version={int(version)}")
    con.execute("CREATE TABLE marker (x INTEGER)")
    con.execute("INSERT INTO marker VALUES (1)")
    shutil.copy2(db, os.path.join(store, "monet.db"))
    shutil.copy2(db + "-wal", os.path.join(store, "monet.db-wal"))
    con.close()
    shutil.rmtree(src, ignore_errors=True)


def make_hot_journal(store, version):
    """Arm S2: `monet.db` + `monet.db-journal` (a real HOT journal), stamped above
    the ceiling. Built by copying the pair while a rollback transaction is open —
    exactly the shape the fix sends through its `null` preflight."""
    os.makedirs(store)
    src = store + ".src"
    os.makedirs(src)
    db = os.path.join(src, "monet.db")
    con = sqlite3.connect(db, isolation_level=None)
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute(f"PRAGMA user_version={int(version)}")
    con.execute("CREATE TABLE marker (x INTEGER)")
    con.execute("INSERT INTO marker VALUES (1)")
    con.execute("BEGIN IMMEDIATE")
    con.execute("INSERT INTO marker VALUES (2)")
    shutil.copy2(db, os.path.join(store, "monet.db"))
    shutil.copy2(db + "-journal", os.path.join(store, "monet.db-journal"))
    con.execute("ROLLBACK")
    con.close()
    shutil.rmtree(src, ignore_errors=True)


def journey(store):
    """Public-surface journey: start the MCP server against the stamped store.

    Returns a dict with `state` one of:
      served          — handshake + tools/list completed (this build accepted the store)
      ceiling_refused — startup failed AND **this arm's own** stderr carries the
                        ceiling refusal text
      lock            — startup failed with a lock/busy signature (INCONCLUSIVE)
      failure         — startup failed for any other reason (INCONCLUSIVE)
    """
    c = MonetClient(store)
    state_ = "served"
    detail = {}
    try:
        try:
            init = c.initialize()
            detail["server"] = (init.get("serverInfo") or {}).get("version")
            detail["tools"] = len(c.tools_list().get("tools", []))
        except RuntimeError as ex:
            state_ = "failure"
            detail["error"] = str(ex)[:200]
    finally:
        c.close()
        detail["stderr"] = c.stderr()
        detail["stray_stdout"] = list(getattr(c, "stray_stdout_lines", []))
        detail["exit_code"] = c.proc.returncode

    if state_ != "served":
        blob = "\n".join([detail["stderr"], "\n".join(detail["stray_stdout"]), detail.get("error", "")])
        state_ = classify_startup_failure(blob)
    detail["state"] = state_
    detail["shape"] = sidecars(store)
    return detail


def classify_startup_failure(blob):
    """Attribute a failed startup to the ceiling, to a lock, or to neither.

    Only the ceiling refusal may count as a flip signal — a lock/busy startup is
    INCONCLUSIVE (run-117 constraint 2), never a flip and never a plain failure.
    """
    if CEILING_RE.search(blob):
        return "ceiling_refused"
    if LOCK_RE.search(blob):
        return "lock"
    return "failure"


def verdict(states):
    """Pure decision rule for the flip guard (self-checked offline in `selfcheck`).

    Returns (verdict, detail) with verdict in {"xpass", "xfail", "inconclusive"}:
      xpass        — every arm refused with the ceiling message (fix present)
      xfail        — no arm refused (bug present on every probed shape)
      inconclusive — anything else: an unresolved arm while a flip is pending, or a
                     partial ceiling (some shapes refuse, others still serve)
    """
    refused = sorted(n for n, s in states.items() if s == "ceiling_refused")
    served = sorted(n for n, s in states.items() if s == "served")
    bad = sorted(n for n, s in states.items() if s not in ARMS_OK)
    if refused and bad:
        return "inconclusive", f"refusal on {refused} but no verdict on {[(n, states[n]) for n in bad]}"
    if refused and served:
        return "inconclusive", f"partial ceiling: refused {refused}, still served {served}"
    if refused:
        return "xpass", f"ceiling refusal on every arm {refused}"
    if served:
        return "xfail", f"bug present: no arm refused (served {served}, unresolved {bad})"
    return "inconclusive", "no arm produced a state"


def selfcheck():
    """Offline checks of the guard's OWN decision logic — the part that decides
    whether a future release gets flipped to FIXED. Runs every invocation, costs
    no product process."""
    print("  -- guard decision logic (offline) --")
    check("classify_ceiling_refusal",
          classify_startup_failure("Store schema 14 is newer than supported schema 13; refusing to open.") == "ceiling_refused")
    check("classify_lock_is_inconclusive",
          classify_startup_failure("SQLiteError: database is locked") == "lock")
    check("classify_timeout_is_not_a_flip",
          classify_startup_failure("server closed stdout / timeout; stderr=...") == "failure")
    a = "A_bare_header"
    b = "B_real_header"
    s1 = "S1_orphan_wal"
    s2 = "S2_hot_journal"
    check("verdict_all_refused_flips",
          verdict({a: "ceiling_refused", b: "ceiling_refused", s1: "ceiling_refused", s2: "ceiling_refused"})[0] == "xpass")
    check("verdict_all_served_xfails",
          verdict({a: "served", b: "served", s1: "served", s2: "served"})[0] == "xfail")
    check("verdict_lock_blocks_flip",
          verdict({a: "ceiling_refused", b: "lock", s1: "ceiling_refused", s2: "ceiling_refused"})[0] == "inconclusive")
    check("verdict_partial_is_not_a_flip",
          verdict({a: "ceiling_refused", b: "ceiling_refused", s1: "served", s2: "ceiling_refused"})[0] == "inconclusive")
    check("verdict_lock_without_refusal_still_xfails",
          verdict({a: "served", b: "served", s1: "lock", s2: "served"})[0] == "xfail")


def main():
    base = tempfile.mkdtemp(prefix="monet-re58-e2e-")
    real = os.path.join(base, "real")
    bare = os.path.join(base, "bare")
    os.makedirs(real)
    check("isolated_store", base.startswith(tempfile.gettempdir()), f"base={base}")
    selfcheck()

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

        # --- fixtures S1/S2: the STRAY sidecar shapes (run 118) ----------------
        # These are the shapes the ceiling fix sends through its least-verified
        # `null` preflight; the original two arms never reach it.
        s1 = os.path.join(base, "stray-orphan-wal")
        s2 = os.path.join(base, "stray-hot-journal")
        make_orphan_wal(s1, stamp_v)
        make_hot_journal(s2, stamp_v)
        pre_s1, pre_s2 = probe_copy(s1), probe_copy(s2)
        check("S1_orphan_wal_shape", sidecars(s1) == ["monet.db", "monet.db-wal"] and "monet.db-shm" not in sidecars(s1),
              f"{sidecars(s1)}")
        check("S1_orphan_wal_stamped", pre_s1["user_version"] == stamp_v, f"uv={pre_s1['user_version']}")
        check("S2_hot_journal_shape", sidecars(s2) == ["monet.db", "monet.db-journal"], f"{sidecars(s2)}")
        check("S2_hot_journal_stamped", pre_s2["user_version"] == stamp_v, f"uv={pre_s2['user_version']}")

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

        # --- the journeys: does `monet start` refuse the above-ceiling store? ---
        # Sequential, one server process at a time: the stray-shape probes must be
        # lock-free / single-writer (run-117 constraint 2).
        arms = [("A_bare_header", bare), ("B_real_header", real),
                ("S1_orphan_wal", s1), ("S2_hot_journal", s2)]
        # TRUE pre-journey sidecar shapes: `state()`/`probe_copy` open a COPY, whose
        # `files` list gains `-shm` and would misreport the arm's own shape.
        for _name, _store, _pre in (("A_bare_header", bare, pre_bare), ("B_real_header", real, pre_real),
                                     ("S1_orphan_wal", s1, pre_s1), ("S2_hot_journal", s2, pre_s2)):
            _pre["files"] = sidecars(_store)
        results = {}
        states = {}
        for name, store in arms:
            r = journey(store)
            results[name] = r
            states[name] = r["state"]
            print(f"    [{name}] state={r['state']} exit={r['exit_code']} shape={r['shape']} "
                  f"stderr={r['stderr'][:160]!r}")

        # B's pre-state is re-labelled to the STAMPED version: `pre_real` was captured
        # BEFORE `stamp()` ran, so printing 13 -> 14 would read as if the older build
        # bumped the schema itself (the assertion A_real_stamped already pins the stamp).
        pre = {"A_bare_header": pre_bare, "B_real_header": dict(pre_real, user_version=stamp_v),
               "S1_orphan_wal": pre_s1, "S2_hot_journal": pre_s2}
        post = {}
        for name, store in arms:
            post[name] = state(store) if name in ("A_bare_header", "B_real_header") else probe_copy(store)

        # per-arm post-state: the record's evidence (printed, not asserted — a
        # refusal may legitimately convert a -journal store before refusing)
        for name, _ in arms:
            print(f"    post [{name}]: tables {pre[name]['n_tables']}->{post[name]['n_tables']}, "
                  f"uv {pre[name]['user_version']}->{post[name]['user_version']}, "
                  f"files {pre[name]['files']} -> {post[name]['files']}")

        kind, why = verdict(states)
        print(f"    verdict={kind} ({why})")

        if kind == "inconclusive":
            # A lock/timeout arm (the ceiling is decided after the write port opens
            # on the stray shapes) or a partial ceiling: neither flip-failure nor
            # flip-success — INCONCLUSIVE, never XPASS.
            print(f"\nRESULT: INCONCLUSIVE {ISSUE} — {why}. A lock/timeout arm is neither a "
                  f"flip nor a failure (run-117 constraint 2), and a partial ceiling is not a "
                  f"fix. Re-run on a quiet machine.")
            return 4

        if kind == "xpass":
            # ceiling present on every arm: assert the documented refusal per arm
            # and that the store was not re-versioned by it. Residue is a
            # MEASUREMENT, not an assertion (#156: the CLI still writes the circle
            # map; on -journal/asymmetric shapes the store is converted BEFORE the
            # refusal — asserting write-freeness would turn the fix into a FAIL).
            for name in [n for n, _ in arms]:
                check(f"refusal_names_both_versions_{name}", bool(CEILING_RE.search(results[name]["stderr"])),
                      f"stderr={results[name]['stderr'][:120]!r}")
                check(f"refusal_exit_nonzero_{name}", results[name]["exit_code"] not in (None, 0),
                      f"exit={results[name]['exit_code']}")
                check(f"post_refusal_store_version_unchanged_{name}",
                      post[name]["user_version"] == stamp_v, f"uv={post[name]['user_version']}")
                new_tables = [t for t in post[name]["tables"] if t not in pre[name]["tables"]]
                new_files = [f for f in post[name]["files"] if f not in pre[name]["files"]]
                print(f"    post-refusal residue [{name}]: tables {pre[name]['n_tables']}->"
                      f"{post[name]['n_tables']} new={new_tables}, files {pre[name]['files']} -> "
                      f"{post[name]['files']} new={new_files}  # measurement, not asserted")
            fixed = not FAIL
        else:
            # ceiling absent: the store is accepted AND served on every arm.
            # Verify the reproduction itself (a failed reproduction = this test is wrong).
            bug_present = True
            print(f"    -> every above-ceiling arm was accepted (states={states}): "
                  f"bare tables {pre_bare['n_tables']}->{post['A_bare_header']['n_tables']}, "
                  f"S1 files {pre_s1['files']} -> {post['S1_orphan_wal']['files']}, "
                  f"S2 files {pre_s2['files']} -> {post['S2_hot_journal']['files']}")
            check("repro_bootstrap_wrote_tables", post["A_bare_header"]["n_tables"] > pre_bare["n_tables"],
                  f"{pre_bare['n_tables']}->{post['A_bare_header']['n_tables']}")

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
                s2_resp = c.call_json("memory_search", {"query": "RE58-MARKER observation stored while the store was still",
                                                        "circle": "e2e-re58", "limit": 3})
                hit_seed = any(x.get("id") == real_seed_id for x in (s2_resp.get("results") or []))
            finally:
                c.close()
            check("repro_older_build_serves_pre_existing_rows", hit_seed,
                  f"seed={real_seed_id} hits={len(s2_resp.get('results') or [])}")

            # the stray shapes are the fix's blind spot: on the shipped build they
            # must be accepted too (evidence for the next flip, not a flip signal)
            for name in ("S1_orphan_wal", "S2_hot_journal"):
                check(f"repro_stray_shape_accepted_{name}", states[name] == "served",
                      f"state={states[name]} files {pre[name]['files']} -> {post[name]['files']}")

            # ... and not merely bootstrapped: a real store→search round trip on each
            # stray shape, so a future flip is compared against measured USER-PATH
            # evidence on exactly the shape set the fix branches on.
            for name in ("S1_orphan_wal", "S2_hot_journal"):
                store = dict(arms)[name]
                token = f"RE58-STRAY-{name}-token"
                c = MonetClient(store)
                try:
                    c.initialize()
                    r = c.call_json("memory_store", {
                        "content": f"{token}: stored into an above-ceiling store whose "
                                   f"pre-journey sidecars were {pre[name]['files']}",
                        "circle": "e2e-re58-stray",
                        "sourceRefs": ["e2e:test58"],
                    })
                    s = c.call_json("memory_search", {"query": token, "circle": "e2e-re58-stray", "limit": 3})
                    hit_stray = any(x.get("id") == r.get("conceptId") for x in (s.get("results") or []))
                finally:
                    c.close()
                check(f"repro_stray_shape_served_{name}", hit_stray,
                      f"conceptId={r.get('conceptId')} hits={len(s.get('results') or [])}")

            check("post_journey_store_version_unchanged",
                  post["A_bare_header"]["user_version"] == stamp_v and post["B_real_header"]["user_version"] == stamp_v,
                  f"A={post['A_bare_header']['user_version']} B={post['B_real_header']['user_version']}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed (setup broken)")
        return 1
    if fixed:
        print(f"\nRESULT: XPASS {ISSUE} — `monet start` refuses a store newer than this build "
              f"on all four sidecar arms (header x2, orphan-wal, hot-journal) (upstream {UPSTREAM})")
        return 3
    assert bug_present
    print(f"\nRESULT: XFAIL {ISSUE} — dist 1.11.0 has no schema ceiling: an above-ceiling store "
          f"opens, is bootstrapped and served on all four sidecar arms (header x2, orphan-wal, "
          f"hot-journal), while `monet repair` refuses the same store "
          f"(upstream {UPSTREAM}; ceiling PR #155 MERGED 2026-09-18 into `main` "
          f"but in NO published release — flip pending a release)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
