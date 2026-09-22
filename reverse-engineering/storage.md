# Storage port (persistence seam, lock ownership, verified backup)

Source: `src/storage.ts` (readable TS, `@team-monet/core` v0.9.0) + `src/statement-trace.ts`
(wiring) + `src/__tests__/store-busy.test.ts`, `src/__tests__/embedder-pin.test.ts`,
`src/__tests__/migrate-embeddings.test.ts` (repair-backup coverage).

## What it is

The narrow persistence seam the engine talks to, plus its shipped driver. `MonetCore`
depends ONLY on the synchronous, statement-oriented `StoragePort` interface — never on a
concrete driver — so the engine's resolve-or-create / connection-graph / synthesis logic is
independent of where the bytes live. The default adapter, `BetterSqlitePort`, is a thin
pass-through over better-sqlite3 (single local file or `:memory:`).

Two other read-only helpers live here (`readStoredEmbedderPin`, `readStoredVectorPresence`)
because — like `BetterSqlitePort` — they are the only other direct better-sqlite3 consumers
and touch only the raw driver, never `MonetCore`'s schema/migration logic.

## Key behaviors

- **WAL + busy_timeout for a shared topology.** The constructor sets `journal_mode = WAL`
  then `busy_timeout = 5000` so ONE MCP server and ONE `monet` CLI call can share a `.monet`
  DB without an immediate SQLITE_BUSY. `journal_mode = WAL` is the first statement and is
  what actually waits against a busy store (measured ~5246 ms), so it is the real contention
  point, not `new Database()` (which returns in ~0 ms even against an exclusive lock).
- **Contention is named, not just reported.** On open failure, `storeContentionError` turns
  `SQLITE_BUSY`/`SQLITE_LOCKED`/`database is locked` into a `StoreBusyError` carrying the
  dbPath, how long was waited, and the in-flight holders read from
  `readInflightStatements(dirname(dbPath))` **filtered by `dbPath`** (so several stores in one
  directory don't mis-attribute). The message deliberately distinguishes "tracing is off"
  from "no holder" — an absent record is not an absent holder.
- **Every SQL mouth goes through one `traced()` helper.** `prepare`/`run`/`get`/`all`/`exec`/
  `pragma`/`transaction`/`immediateTransaction` all route through `traced`; `db.backup()` and
  the `quick_check` verification are traced explicitly at their call sites (the async path
  cannot use the synchronous helper). The invariant is "no SQLite work outside a trace frame",
  not "no `this.db.<method>`" — four Codex review rounds each found one more mouth because
  earlier phrasings were about method names rather than the work.
- **Exclusive ownership for `repair`.** `acquireExclusiveOwnership()` / `releaseExclusiveOwnership()`
  implement the exclusive lock `repair` needs. Two FIX subtleties: (1) SQLite's EXCLUSIVE→NORMAL
  downgrade is lazy and only works if the connection's WAL/shm was materialized by a REAL page
  access first, so both acquire and release do a `warmSchemaRead()` (`SELECT name FROM
  sqlite_schema LIMIT 1`) before/after the `locking_mode` switch (9/9 unwarmed failures vs warmed
  success); (2) `locking_mode` alone does not retain the file lock until a real write, so acquire
  toggles `user_version` by ±1 inside one `BEGIN IMMEDIATE … COMMIT` (INT32_MAX-guarded) — a
  schema-independent reversible write that makes the lock effective after COMMIT. A failed
  cleanup records `uncertainExclusiveLockError` so further acquisition refuses rather than
  treating an unverified lock state as shared.
- **Verified repair backup.** `createVerifiedBackup(destination)` runs while holding exclusive
  ownership: better-sqlite3 online backup (includes committed WAL frames) → open the partial
  read-only → `PRAGMA quick_check` must return a single `ok` → `chmod 0600` → hard-link publish
  (atomic, no-clobber: EEXIST → `VerifiedBackupDestinationExistsError`, never overwrites).
  Every failure path removes only this call's unique `.partial-<pid>-<uuid>` file and its
  `-wal`/`-shm` sidecars and releases ownership. `:memory:` refuses (backups require a file).
- **Read-only peeks (no side effects).** `readStoredEmbedderPin` reads
  `sync_meta.embedder_model_id` and `readStoredVectorPresence` checks whether any semantic
  vector is committed. Both open `{ readonly: true, fileMustExist: true }`, never create/migrate
  a DB, and never change journal mode. Both are tolerant: every "nothing to read yet" shape
  (no file, not-a-DB, missing table/column, locked) collapses to `null` (pin) or `false`/`null`
  (presence) rather than throwing — a `null` from `readStoredVectorPresence` means "could not
  inspect", which callers treat conservatively as *not fresh*, not as *fresh*.

## Parameters / constants

| Parameter | Value | Role |
|-----------|-------|------|
| `journal_mode` | `WAL` | shared MCP-server + CLI topology |
| `busy_timeout` | 5 000 ms | contention wait budget |
| exclusive probe | `user_version` ±1 (INT32_MAX 2 147 483 647 guard) | reversible real write to retain the exclusive lock |
| `locking_mode` | `EXCLUSIVE` (acquire) / `NORMAL` (release) | repair ownership dance |
| `warmSchemaRead` | `SELECT name FROM sqlite_schema LIMIT 1` | real page access before/after mode switch |
| backup partial name | `.<name>.partial-<pid>-<uuid>` | per-call unique, cleaned on any failure |
| backup mode | `chmod 0600` | published backup file |
| `quick_check` gate | single `ok` row | else `VerifiedBackupVerificationError` |
| backup publish | hard-link (`link`), EEXIST → refuse | atomic + no-clobber (vs rename) |
| peek open | `readonly: true, fileMustExist: true` | no create/migrate/journal-mode change |
| holder filter | `readInflightStatements(dirname).filter(h => h.dbPath === dbPath)` | multi-store directory safety |

## Issues

- **RE-41 (S4, source)** — see `embedding.md`. The silent cross-space compare that
  `PinnedStoreEmbedderUnavailableError` (store-embedder.ts) and the graft
  `EmbedderMismatchError` exist to prevent is re-opened one level down by `cosine()`'s
  `Math.min` length handling: if a mismatched-dimension comparison ever slips past those
  guards, `cosine` returns a plausible number instead of erroring. No storage-layer bug here;
  the note is owned by `embedding.ts`.

- **RE-66 (S2, confirmed)** — the burst failure mode finally has a name: under more than the
  topology the product states ("One MCP server and one `monet` CLI call sharing a store"), a
  store call returns `store failed: database is locked` as RAW TEXT (an id-less response, no
  exception) and `monet start` can die in `phase: "store-open"` with `StoreBusyError`. Measured
  in run 128 — details + numbers in "Run 128 — the burst failure mode has a name" below.

No storage-layer issue of its own. The module is heavily reviewed (four Codex rounds on the
trace-frame invariant, PR #216 holder-filter + constructor-cleanup, #215 open-timeout budget)
and its sharp edges are documented in-line rather than open.

## Verification

- `store-busy.test.ts` pins `readInflightStatements` contract (parse/sort, empty on missing dir,
  skip foreign files, empty-result semantics) and the `StoreBusyError` holder naming.
- `embedder-pin.test.ts` + `migrate-embeddings.test.ts` cover the read-only pin/vector-presence
  peeks and the repair-backup path (quick_check gate, no-clobber, sidecar cleanup).

## Store resolution across surfaces (run 125, measured on dist 1.11.0)

**Rung order (source + measurement agree):** `MONET_STORAGE_DIR` (absolute or relative; `--dir`/`-d`
sets it) → `<projectDir>/.monet` **if that directory exists** → `$HOME/.monet`, where
`projectDir = MONET_PROJECT_DIR || CLAUDE_PROJECT_DIR || cwd` via `path.resolve` only — i.e. the
**exact** cwd, no upward search (`packages/cli/src/project-dir.ts`). The middle rung is the one no
public doc mentions.

### Surface matrix (8 arms; probes `/tmp/r125_store_res_probe2.py`, `/tmp/r125_flip_probe.py`)

Surfaces compared: `status` **stdout** (`Storage:`), `status` **stderr** (`Storage:`),
`doctor --json` (`dbPath`), `start` **stderr** (`Storage:`), `monet config --agent cursor` (pinned
`MONET_STORAGE_DIR` — the store *dir*), `monet dashboard` (`Store:`, where measured).

| Arm | Shape | Resolved store | Surfaces agree |
|-----|-------|----------------|----------------|
| A1 | no override, cwd has no `.monet` | `$HOME/.monet/monet.db` | yes |
| A2 | no override, cwd HAS `./.monet` | `<cwd>/.monet/monet.db` | yes (and ≠ the documented `~/.monet`) |
| A3 | `MONET_PROJECT_DIR=projA`, cwd=projB | `<projA>/.monet/monet.db` | yes (incl. dashboard) |
| A4 | `CLAUDE_PROJECT_DIR=projA`, cwd=projB | `<projA>/.monet/monet.db` | yes |
| A5 | both set, different | `<MONET_PROJECT_DIR>/.monet/monet.db` | yes (MONET wins) |
| A6 | absolute `MONET_STORAGE_DIR` | that absolute dir | yes (beats both project vars) |
| A7 | **relative** `MONET_STORAGE_DIR=rel-store` | `./rel-store/monet.db` | **no** — stdout/start print it verbatim, stderr/doctor print it resolved (RE-63, S4) |
| A8 | landing journey (see below) | mixed | by design/see RE-62 |

In **every** arm `created_project_.monet = []`: no diagnostic created a project-local store, so
"asking the question" does not change the answer. The multi-surface consistency fix shipped in
1.11.0 is therefore verified on the live path (RE-62 is *not* about surfaces disagreeing).

### A8 — agent-host → operator landing journey
- Host env (`MONET_PROJECT_DIR=<repo>`, spawned at a different cwd): served `<repo>/.monet`;
  `memory_store` → `created`; same-process search hit 1; **fresh server process** with the same env
  read it back (hit 1) → durable and reproducible.
- Operator with the host env → `<repo>/.monet`, `Concepts: 1` ✅
- Bare operator at the **repo root** → `<repo>/.monet`, `Concepts: 1` ✅ (the rung incidentally
  helps a human standing in the repo root)
- Bare operator at **`<repo>/sub`** → `$HOME/.monet`, `Concepts: 0` ❌ — and the call creates
  `$HOME/.monet/monet.db` (physical check), so the wrong-rung store becomes durable.

### A9 — the silent flip (one documented flag, then bare calls only)
| # | Invocation | Store | Concepts |
|---|-----------|-------|----------|
| 1 | `monet start` (cwd=projC) + `memory_store` | `$HOME/.monet` | 1 (hit 1) |
| 2 | `monet status` (projA) | `$HOME/.monet` | 1 |
| 3 | `monet start -d <projA>/.monet` | `<projA>/.monet` | — (creates the rung) |
| 4 | `monet status` (projA) | `<projA>/.monet` | **0** |
| 5 | `monet start` (projA) → `memory_search` | `<projA>/.monet` | **0 hits** |
| 6 | `monet status` / start (projC) → search | `$HOME/.monet` | 1 (hit 1) |

Nothing is lost — but from step 4 on, the same user in the same repo is served an empty store, the
flip is permanent (the rung is "exists", checked on every entry point), and nothing says so.
`monet doctor --dir ~/.monet --json` reports `dbPath: $HOME/.monet/monet.db` at that point, so the
README's own diagnosis command answers about the store that is *not* in use.

Upstream: **team-monet/monet#162** (filed run 125; duplicates searched: `MONET_PROJECT_DIR` 0 hits,
`store resolution subdirectory` 0 hits).

### Asks (in #162)
1. Document the rung (and call `~/.monet` the *default*, not "the" store).
2. Disclose a project-local rung choice in `status`/`doctor` text (explicit override vs project
   `.monet`).
3. Either search upward for a project store, or notice when the resolved store differs from the one
   recently used for the same project. Fix RE-63 by resolving `MONET_STORAGE_DIR` into the reported
   string on every surface.

### Run 126 — promoted to the suite (the probe becomes a guard)

Run 125 left RE-62/RE-63 as probe-only (`/tmp/r125_*`). Run 126 turned both into suite-linked
tests that assert the DESIRED contract and exit 2 (XFAIL) while the defect stands:

| Test | Issue | Class | Run-126 verdict |
|------|-------|-------|-----------------|
| test63 | scenario 12 (positive) | storage RESOLUTION — six surfaces must name ONE file | **PASS** (44 checks, 0 failed, 29.1 s) |
| test64 | RE-62 | rung disclosure + operability from below the root | **XFAIL** — REPRO 16/16, DESIRED 0/4 |
| test65 | RE-63 | relative `MONET_STORAGE_DIR` display | **XFAIL** — 4 surfaces, desired unmet |

What the guards add over the probes: (1) **test64 leg H1** pins the blind spot with no flip at all —
with `MONET_PROJECT_DIR=<proj>` and cwd `<proj>`, the bare server stores into `<proj>/.monet`
(concepts 1) while a bare `status` at `<proj>/sub` and `<proj>/sub/deep` reports `$HOME/.monet`
(**concepts 0**) and its `memory_search` returns **0 hits** for the row that is physically in the
project store — the rung needs the directory to EXIST *and* the cwd to be exactly it, and `monet
status` does not search upward. (2) **test64 leg H2** re-plays the silent flip (before flip:
`$HOME/.monet`, hit 1; `monet start -d <proj>/.monet` creates the rung; after: store = `<proj>/.monet`,
`!=` the store holding the row, hit **0**) and proves the row still EXISTS in the old store
(observation_tokens row count 1) — nothing is lost, it becomes unreachable. (3) **test65** names the
harm: a reader resolving the verbatim string against its OWN cwd gets
`~/.monet-test/rel-store/monet.db` — a different file from the served `<proj>/.monet/monet.db`.

Harness note (GR-10, added this run): the bare-call test class cannot use `-d`, so every call must run
under a sandboxed `HOME`/`MONET_*` env AND every path a surface reports is hard-asserted to be inside
the sandbox before the scenario is judged; the first test64 run omitted that wrap on its `status`
calls and opened the REAL `$HOME/.monet` (read paths only).

### Run 128 — the burst failure mode has a name (RE-66)

The 2026-08-12 test09 burst flake was recorded as "resource contention (model-load memory
pressure), not reproducible standalone". Run 128 re-measured it: that generic label was hiding
TWO distinct, named failures, both invisible before the test recorded non-`conceptId` responses
(`ok = bool(r.get("conceptId"))` used to drop the payload silently):

1. **A store under contention answers with raw text**: `{"_rawText": "store failed: database is
   locked"}` — no `conceptId`, no exception, no JSON-RPC error. A caller keying on ids sees a
   silent miss, and the burst guard then ALSO reports a false dedup failure (`unique=2`) because
   the failed store never joined the single concept.
2. **`monet start` can fail to start at all**: `phase: "store-open"`, `StoreBusyError`
   (`code: SQLITE_BUSY`) — "SQLite reported it locked while a statement in the startup's schema
   region ran. That region had been running for 8179ms [8436ms] when it failed", with the
   treatment "One MCP server and one `monet` CLI call sharing a store is the supported topology,
   so this is usually transient — retry once the other process finishes". Written to
   `monet.db.startup-failure.json` (3,252 B). Its clients then saw `RuntimeError: server closed
   stdout / timeout` + `BrokenPipeError`, and one instance stored only 10/20.

So the guard asserts a topology the product declines to support: **in-suite 2/2 FAIL** (both
suite runs today) vs **standalone 6/7 PASS** (1/3 before instrumentation, 4/4 after), and it
failed deterministically only when two test09 instances ran concurrently (burst walls 23.1 s /
19.4 s vs 10–14 s healthy). The red is contention, not a regression — but the test stays red on
purpose, because the assertion is the measurement. The dev Objective is the CONTRACT: either
state the supported topology on the CLI/doctor surface and have the guard assert the documented
shape (all-succeed, or the named `StoreBusyError` / `database is locked` — never a hang,
corruption, or an id-less response), or make startup and store retry/backoff on a shared store.
