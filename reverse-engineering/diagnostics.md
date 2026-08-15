# Diagnostics — embedder-state inspection + lifecycle-edge integrity

Readable-TS source: `packages/core/src/diagnostics.ts` (693 lines),
`packages/core/src/embedding-state.ts` (198 lines, the live-vector inventory it
depends on), `packages/core/src/schema-version.ts` (2 lines). This is the engine
behind `monet doctor` / `monet repair` preflight (wired in `packages/cli/src/repair-cli.ts`),
the first readable-TS documentation of a subsystem previously reverse-engineered
only from the minified `dist` (see `schema-migration.md`, which documented the
doctor/repair *schema ladder*; this documents the *embedder-state assessment*).

## Two responsibilities

1. **`inspectStoredEmbedderState(dbPath)`** — read-only embedder-state diagnosis
   without constructing `MonetCore` (the `monet doctor`/`repair` preflight).
2. **`inspectLifecycleEdgeIntegrity(db)`** — report-only sweep for dangling
   lifecycle edges / ratifications (endpoint concept no longer resolves).

They share one philosophy: **diagnose from a raw better-sqlite3 handle, before any
`MonetCore` exists, and never mutate the source bytes.**

## `inspectStoredEmbedderState` — the doctor/repair preflight

Returns `StoredEmbedderStateInspection`:
`dbPath, exists, schemaVersion, supportedSchemaVersion, integrity, pin, populations,
migration, nonLatin, assessment`.

### Safety assessment (`assess`) — the verdict ladder

`StoredEmbedderSafetyAssessment = "missing" | "safe" | "unsafe" | "unknown"`.

- **missing** — DB file does not exist (clean no-op, no sidecar created).
- **unsafe** — provable bad state: `integrity.status === "failed"`, OR an active
  embedder migration, OR any population has `malformed.count > 0`, OR more than one
  vector width across the four populations, OR a hashing pin whose declared width
  mismatches the stored width.
- **unknown** — cannot be proven one way or the other: integrity not `ok`, migration
  unknown, a population's schema does not prove liveness, `schemaVersion !== 12`,
  pin unknown, OR (`storedVectorCount > 0` AND (`pin.modelId === null` OR the pin is a
  non-hashing identity)). **An arbitrary ONNX/model/path pin always lands here** —
  its width cannot be proven without loading the provider, so `doctor` must not call
  that combination compatible from shape alone. This is exactly why plain
  `monet doctor` prints `Assessment: unknown` on a healthy store and `--check-provider`
  loads the pinned provider to reach `safe`.
- **safe** — everything provably consistent: integrity ok, no migration, all four
  populations known and uniform, zero malformed, schema 12, pin known, and (when
  vectors exist) either no pin or a hashing pin with a matching width.

### Integrity check

`PRAGMA quick_check` → `{status:"ok", check:"ok"}` only when exactly one row `"ok"`;
otherwise `{status:"failed", check:[...]}`. `repair-cli.ts` refuses to mutate a store
whose integrity result is `failed` (see `repair-cli.test.ts` "refuses a store whose
integrity check FAILED").

### Pin inspection (`inspectPin`)

Reads `sync_meta` singleton row (`embedder_model_id`, `embedder_pin_source`,
`embedder_pinned_at`). `PIN_SOURCES = {"created","backfilled","migrated"}`. Malformed
metadata → `{status:"unknown", reason:"persisted embedder pin metadata is malformed"}`
— e.g. non-empty-string model id, `model_id` set with null source/timestamp, or a
source outside `PIN_SOURCES`.

### Populations (`inspectPopulations` → `embedding-state.ts`)

Four canonical live populations, each a `{status:"known"|"unknown"}` wrapping
`LiveEmbeddingPopulationInspection {liveRowCount, scoredVectorCount, ignoredZeroVectorCount, dimensions[], malformed{count, sampleIds[]}}`:

- `nativeObservations` — `observations WHERE kind != 'source'`.
- `nativeConcepts` — `concepts WHERE kind != 'source' AND embedding IS NOT NULL`.
- `sourceObservations` — `kind = 'source'` AND (no `source_chunks` row OR an
  `active` chunk whose concept is null-or-active).
- `sourceConcepts` — `kind = 'source' AND status = 'active' AND embedding IS NOT NULL`.

The liveness predicates are kept byte-for-byte aligned with the merged #56
native/source ownership boundary. Source populations exclude legacy all-zero
placeholder vectors (`excludeZero = true` → `ignoredZeroVectorCount`), native do not.
`parseFiniteEmbeddingJson` is the strict persisted-vector parser shared by diagnosis,
enforcement, and hostile payload validation (JSON array of finite numbers,
round-tripped through `Float32Array`).

A population is `unknown` when its required tables/columns are absent
(`POPULATION_SCHEMA` — e.g. `sourceObservations` requires the `source_chunks` table
with `observation_id/concept_id/lifecycle`), which is how a legacy/partial schema is
reported as unknown rather than inferred safe.

### Migration inspection + abandon classification

`embedder_migration` singleton. `{status:"none"}` when no row; `{status:"active"}` with
an `abandon.classification ∈ {safe, refused, unsupported, unknown}`:

- **refused** — `vectors_rewritten != 0` (rewrite started/cannot be disproved), or the
  live store holds >1 vector width.
- **unsupported** — sentinel predates durable prior-pin capture (`prior_pin_captured === 0`).
- **unknown** — a population's liveness can't be proven from this schema.
- **safe** — no rewrite recorded, widths consistent, exact prior pin captured.

### Snapshot isolation (the #188 subtlety)

Opening a closed WAL-mode DB read-only makes SQLite *create fresh `-wal`/`-shm`* beside
the real file (macOS) — or fail `SQLITE_BUSY` on the zero-to-one WAL-recovery race
(Linux/WSL2). So the open is **conditional on WAL presence**:

- **No WAL+SHM pair** → copy the main file to `monet-readonly-diagnostic-*` under
  `os.tmpdir()`, SHA-256 the bytes before/after (and reject if they or the sidecar set
  changed → `locked`), and open the **copy read-write** (`readonly: false`) so SQLite
  builds sidecars beside the throwaway copy, not the source. Temp dir removed in
  `finally`.
- **WAL+SHM pair exists** → open the **real file read-only** (`readonly: true`) to
  observe committed WAL frames and surface lock failures.

Guards before open: `-wal` XOR `-shm` (incomplete pair) → throw `"unreadable"`; a
rollback journal without WAL → throw `"locked"`. Typed failures
(`StoredEmbedderStateDiagnosticError`, `reason ∈ {locked, not-sqlite, unreadable}`)
classify by error code (`SQLITE_BUSY`/`SQLITE_LOCKED`/`SQLITE_NOTADB`), so a CLI can't
mistake an unreadable store for a missing one. `timeout: 5_000`, `fileMustExist: true`.
The test suite asserts **byte-for-byte non-mutation** of db/wal/shm and that absent
sidecars are not created.

### Non-Latin content scan (`inspectNonLatin`)

Counts what a move to a Latin-only embedder would strand, measured with the SAME
`nonLatinLetterShare > NON_LATIN_LETTER_TOLERANCE (0.2)` threshold the write gate
enforces (so it can't clear a row the write path would refuse). Reported **regardless
of the current pin** — the count exists to be read *before* a Latin-only migration,
when the pin is still multilingual.

Scans **four** populations (not one) — the exact set `migrateEmbeddings` rewrites:

1. native observations (`kind != 'source'`, no supersession filter),
2. source observations whose chunks are live (or which have none),
3. native concept **bodies** (`kind != 'source' AND body IS NOT NULL`) — bodies are
   written by `applySynthesis` *without* the write path's script gate, so a store of
   English observations can hold a non-Latin body (Codex P1, PR #173).

Streamed via `.iterate()` (not `.all()`) so a large source store isn't materialized
while producing the very warning meant to prevent a loss. Samples are **per-population**
(3 observation ids + 2 concept ids), not a shared first-come buffer — otherwise five
non-English observations would starve the concept-body sample (the invisibility this
scan was widened to fix).

## `inspectLifecycleEdgeIntegrity` — dangling-edge sweep

Report-only. Sweeps `lifecycle_edges` and `ratifications` for rows whose endpoint
concept id no longer resolves in `concepts`:

- A provenance edge (null `dst_concept_id`) can only report `missing: ["src"]` — a null
  dst is a span address, not a missing concept.
- `DanglingRatification` = a ratification whose `subject_concept_id` is gone.

Returns `{tablesPresent, edgesChecked, ratificationsChecked, dangling, danglingRatifications}`.
When the tables predate the store (`tablesPresent: false`) both lists are trivially empty.

**REPAIR SEMANTICS ARE DELIBERATELY UNDEFINED.** Whether an orphaned derivation edge
should be dropped, re-pointed at the surviving consolidation target, or preserved as
evidence is a question for impeachment/audit consumers that do not exist yet. Guessing
now would bake in an answer the consuming slice would unpick. The ordinary
unwind/rederive/detach/reassign path cannot orphan an edge (append-only, graph
maintenance never deletes); the residual path is hard concept deletion (full-consolidation
`detach` deletes the source row; hard delete removes an id permanently).

## Findings

- **RE-35 (source, S4)** — `lifecycleEdgeIntegrity()` is a public `MonetCore` method
  (exported from `index.ts`) with **no operator surface**: it is not exposed as an MCP
  tool or CLI command (unlike `inspectStoredEmbedderState`, which is `doctor`/`repair`).
  It is exercised by unit tests and referenced in the graft path ("reported by the
  dangling sweep, never repaired here"), but no `doctor`/`status`/MCP path surfaces its
  output. This is the same shape as RE-33 (slow-queries.jsonl write-only) one layer up:
  a report-only diagnostic with library-only reachability. Moot today — no producer of
  lifecycle edges exists yet (rule capture arrives with a later slice), so no live
  orphan is currently possible — but the sweep will need a surface when that slice lands.
- `MONET_SCHEMA_VERSION = 12` is now a **single named constant** (`schema-version.ts`),
  imported by both `engine.ts` and `diagnostics.ts`. The readable source does NOT hardcode
  12 in multiple places — RE-09 ("supportedSchemaVersion hardcoded in 3+ places") is a
  **dist-bundle** concern (the minified `cli.js` inspector duplicates the literal), not a
  readable-source one. Cross-check note, not a new issue.
