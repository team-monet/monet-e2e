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

No storage-layer issue of its own. The module is heavily reviewed (four Codex rounds on the
trace-frame invariant, PR #216 holder-filter + constructor-cleanup, #215 open-timeout budget)
and its sharp edges are documented in-line rather than open.

## Verification

- `store-busy.test.ts` pins `readInflightStatements` contract (parse/sort, empty on missing dir,
  skip foreign files, empty-result semantics) and the `StoreBusyError` holder naming.
- `embedder-pin.test.ts` + `migrate-embeddings.test.ts` cover the read-only pin/vector-presence
  peeks and the repair-backup path (quick_check gate, no-clobber, sidecar cleanup).
