# Monet Reverse-Engineering — Schema Migration & Versioning

> Status: **DOCUMENTED** (2026-08-11, run 10). Source: `@team-monet/monet` v1.5.2
> (`dist/index.js` store core + `dist/cli.js` doctor/repair). This closes the
> PARTIAL item from METRICS ("schema migration 4→12 — table/sentinel open").

## TL;DR

Monet has **no migration table**. The single source of schema truth is
**SQLite `PRAGMA user_version`**, a scalar integer bumped through a fixed
ladder 0 → 12. All DDL is **idempotent**: every step guards on
`PRAGMA table_info(<table>)` (column existence) or `sqlite_master`
(index/table existence) before running, so a crash mid-migration is safe —
the next open re-runs only the unfinished pieces. `user_version` is more a
**milestone marker** than a per-step ledger: version bumps are batched at the
end of `migrate()`, so two stores at the same version are indistinguishable
regardless of how many steps they actually ran. The one non-idempotent
conversion (First Block pins → observations, schema 12) is wrapped in a
single `immediateTransaction` and carries a hardcoded sentinel.

## The version constants (dist/index.js, offset ~663136)

```js
Ff=1, Hf=2, jf=3, Wf=4, Zf=5, qf=6, Bf=7, kr=8, Xf=9, Vf=11, UT=12
zT = "schema-12-first-block-migration"   // sentinel author_agent_id
```

- **Version 10 is skipped** — no constant, `9 → 11` jump. Hole in the ladder.
- `Gf=15` looks like a schema constant but is **NOT** — it is the
  **sync/graft protocol version** (`payload.schemaVersion`; `graftRows`
  refuses payloads `> Gf` with "this build understands up to 15").

## The startup migration pipeline (MonetStore constructor)

Order of operations (constructor, offset ~675550):

```
init()                              // base CREATE TABLE IF NOT EXISTS (no version bump)
initSyncIdentity()
sourceRegistry.ensureSchema()       // separate subsystem (knowledge_sources etc.)
migrate()                           // main ladder 0..8
fT(db)                              // gate sidecar: gate_events.matcher column
sourceLedger.ensureSchema()         // separate subsystem (source ledger)
repairConnectorGraphContamination()
// tail bumps (pure pragma, no DDL):
user_version 8..9  -> 9             // kr -> Xf
user_version 9..10 -> 11            // Xf -> Vf (skips 10)
migrateFirstBlockPins()             // 9/10/11 -> 12 (First Block conversion)
// embedder pin state read (pinUnsatisfied = embedder_migration present || pin mismatch)
```

### `init()` — base tables, no bump
Creates `observations`, `concepts`, `observation_segments`,
`observation_tokens` (the lexical posting list, cf. search-pipeline.md),
`circle_aliases` later in migrate(), etc. — all `CREATE TABLE IF NOT EXISTS`.
Adds `sync_meta` embedder-pin columns (`embedder_model_id`,
`embedder_pin_source` CHECK IN ('created','backfilled','migrated'),
`embedder_pinned_at`), then sidecar helpers `CU(db)`, `jU(db)` (gate_meta),
`migrateLegacyStarCircle()`, `fT(db)` (gate_events.matcher).

### `migrate()` — main ladder (offset ~698158)
Each step = guard + DDL + (later) batch version bump:

| Step | DDL (guarded) |
|------|---------------|
| 0→1 | **Not here** — graph backfill (see below) |
| — | sync_meta: `applying_remote`, `closure_migrated`, `clock_mode` columns |
| — | embedder_migration: `prior_model_id`, `prior_pin_source`, `prior_pinned_at`, `prior_pin_captured`, `vectors_rewritten` |
| — | closure_migrated=0 → `last_mutation_at = MAX(last_mutation_at, now)` |
| — | observations/concepts: `source_refs`; observations: `superseded_at` |
| — | ingest_operations: `writer_domain`, `source_concept_id`, `rule_previous_severity`, `rule_previous_circle`, `rule_circle`, `rule_severity` |
| — | concepts: `aliases`, `source_identity`, `active_observation_id`, `skeleton_breadth` (CHECK 'local'/'global') |
| — | backfill: source concepts `source_identity` from `source_refs`; `active_observation_id` = latest live observation |
| — | backfill: retired concepts without tombstones → `concept_tombstones` |
| — | `CREATE TABLE IF NOT EXISTS circle_aliases` (+ idx_ca_to) |
| — | memory_edge: `legacy_count`, `sync_updated_at` |
| — | embedder no-migration + (pin matches OR no vectors) → `runGraphBackfillIfPending()` |
| — | applying_remote=1 wrap: concepts `last_confirmed_at`/`last_confirmed_session_id`; memory_edge `dismissed_at`/`dismissed_by` |
| 1→2 | `d>=Ff && d<Hf` → pragma(Hf) |
| 2→3 | `l>=Hf && l<jf` → pragma(jf) — **no-op bump** |
| 3→4 | `u>=jf && u<Wf` → pragma(Wf) — **no-op bump** |
| 4→5 | `p>=Wf && p<Zf` → `CREATE UNIQUE INDEX uq_edge ON memory_edge(src_id, dst_id, type, scope)` + pragma(Zf) |
| 5→6 | `h>=Zf && h<qf` → pragma(qf) — **no-op bump** |
| 6→7 | `m>=qf && m<Bf` → pragma(Bf) — **no-op bump** |
| 7→8 | `ensureSyncClosureSchema()` (see below) |

Note the DDL steps before 1→2 are **unguarded by version** — they run on
every open as pure idempotent guards; version 1→8 bumps are applied only
after all of them.

### `ensureSyncClosureSchema()` — sync closure columns + triggers
Adds via `table_info` guards: `sync_revision` (INTEGER NOT NULL DEFAULT 1),
`sync_writer` (TEXT) on concepts/observations/circle_aliases/contradictions/
first_block/sessions; `updated_at` on observations/circle_aliases/
contradictions/first_block/sessions; `clock_mode` on sync_meta;
`contradicted_observation_id` on contradictions; `deleted_at` on first_block.
Then installs sync-closure triggers (concepts/observations: revision++
on mutation, writer = sync_meta.device_id) and — at the end — bumps
**7→8** (`a>=Bf && a<kr && pragma(kr)`).

### `migrateFirstBlockPins()` — the schema-12 sentinel migration (offset ~706672)
Runs only when `user_version ∈ [Vf=9, UT=12)` — i.e. 9, 10, or 11. In a
single `immediateTransaction`:

1. SELECT surviving `first_block` rows joined to concepts
   (`kind NOT IN ('source','workstream')`, no `source_identity`, no
   `active_observation_id`).
2. For each: `INSERT OR IGNORE INTO observations` a `kind='statement'` row:
   - id = `HT(fb.id, fb.summary)` = `"fb-migration:" + sha256(id + "\0" + sha256(summary)).slice(0,32)` — deterministic, re-runnable
   - content = `FT(summary)` = `"First Block pin (surface retired 2026-08-02): " + summary`
   - `author_agent_id = zT` = `"schema-12-first-block-migration"` ← the sentinel
   - circle from the concept, `concept_id`, created/updated = `promoted_at`,
     `sync_revision=1`, `sync_writer = device_id`
3. If inserted (`changes>0`): `support_count + 1`, `dirty = 1` on the concept.
4. `DELETE FROM first_block` (all rows — atomic with the inserts).
5. `user_version = 12` (UT).

The First Block surface was retired 2026-08-02; schema 12 demotes surviving
pins to ordinary statement observations, marked with the sentinel author id.

### `runGraphBackfillIfPending()` (offset ~956421)
`graphEnabled && user_version < Ff(1)` → `backfillGraph()` (builds graph
edges over non-source/workstream concepts) + `user_version = 1`.
Called from migrate() for fresh stores (no pin, no vectors). **This is the
only migration step keyed to the graph feature flag** — user_version 0→1 is
really a "graph backfilled" milestone, conflating feature backfill with schema
evolution.

### `migrateLegacyStarCircle()` (offset ~945520)
Not version-keyed; runs on every open. If any concept / knowledge_source /
lifecycle_edge / ratification / circle_alias references the legacy star
circle `W = "*"`, moves it inside `immediateTransaction` to
`chooseLegacyStarDestination()` = `rd = "legacy-star"` (or `legacy-star-N`
while the name is taken). Only relevant for stores from the pre-circles era.

## Embedder migration — a SEPARATE sentinel subsystem

Schema version ≠ embedder migration state. The `embedder_migration` table
(singleton row: `target_model_id`, `started_at`, `prior_*`, `vectors_rewritten`)
records an in-flight embedder rewrite; `readEmbedderMigration()` reads it,
`markEmbedderMigrationVectorsRewritten()` clears the rewrite flag,
`throwIfEmbedderMigrationIncomplete()`/`assertPinSatisfied()` refuse writes
while one is active. This is what `monet doctor` reports under `Migration:`
and what gates `monet repair` (see skill: "embedder state is unknown;
refusing repair until diagnosis succeeds completely").

## doctor / repair coupling (dist/cli.js)

- **`supportedSchemaVersion: 12` is hardcoded** in the inspector — in BOTH
  branches (missing-DB: offset ~727793; real inspect: offset ~729024).
- doctor prints `Schema: <user_version> (supported: 12)`.
- Assessment `dW(e=<user_version>, d=integrity, p=pin, l=populations,
  h=migration)`: integrity failed OR migration active → `unsafe`; integrity
  not ok OR migration unknown OR any population unknown → `unknown`;
  malformed vectors OR >1 vector dimension → `unsafe`; **`e !== 12`** OR pin
  unknown → `unknown`; scored vectors>0 with null pin → `unknown`; scored
  vectors>0 with pin → dimension must match model registry (EI) else `unsafe`;
  else `safe`. This explains the skill's "plain doctor prints
  Assessment: unknown on a healthy store" — the store-side check needs the
  population/pin data the inspector only fully proves with `--check-provider`.
- Migration sentinel inspector `cW`: validates embedder_migration columns,
  no row → `none`; row → `active` with `rewriteProgress` (`vectors_rewritten
  === 0` → "not-started") and an abandon classification (multi-width →
  refused; `prior_pin_captured === 0` → unsupported; else safe).
- Repair preflight `rB` refuses when: integrity ≠ ok; **`user_version >
  supportedSchemaVersion` ("Store schema X is newer than supported schema
  12; refusing repair")**; pin or migration status unknown.
- `acquireExclusiveOwnership()` (used by repair apply) probes exclusivity by
  toggling `user_version` ±1 inside `BEGIN IMMEDIATE` under
  `locking_mode=EXCLUSIVE` — the same scalar doubles as the lock probe.

## Identified parameters (new, this run)

| Parameter | Value | Where | Role |
|-----------|-------|-------|------|
| Schema ladder | 0 → 12 (10 skipped) | `Ff..UT` consts + migrate fns | user_version milestones |
| `supportedSchemaVersion` | 12 | cli.js inspector ×2 (hardcoded) | doctor display + repair preflight |
| Sync/graft protocol version | 15 (`Gf`) | `graftRows` | export payload version cap |
| First-block sentinel `zT` | `"schema-12-first-block-migration"` | const | author_agent_id of migrated pins |
| Migrated obs id `HT` | `fb-migration:` + sha256(id\0sha256(summary))[:32] | migrateFirstBlockPins | deterministic re-runnable id |
| Migrated obs content `FT` | `First Block pin (surface retired 2026-08-02): ` | const | content prefix |
| Graph backfill gate | user_version < 1 (Ff) | runGraphBackfillIfPending | 0→1 milestone |
| First-block window | [9, 12) → 12 | migrateFirstBlockPins guard | when conversion runs |
| Assessment schema check | `e === 12` | dW in cli.js | doctor verdict |
| Exclusive-lock probe | user_version ±1 | acquireExclusiveOwnership | repair ownership dance |

## Issues found (RE-08..RE-12)

- **RE-08 — migration steps are not transactional as a unit; version is a
  milestone, not a ledger.** All `migrate()` DDL runs outside a single
  transaction (SQLite auto-commits each ALTER). It is safe only because every
  step is idempotent, but a store can be left in a half-migrated state that
  reports the OLD version number while already having some new columns —
  version alone cannot describe it. No corruption risk observed; design note.
- **RE-09 — `supportedSchemaVersion: 12` is hardcoded in 3+ places** (cli.js
  inspector ×2, cli.js `dW` `e!==12`, plus index.js `UT` and the
  `migrateFirstBlockPins` window). The next schema bump must touch all of
  them in lockstep; nothing centralizes "current schema = 12". Latent
  maintenance risk (a bump that forgets `dW` silently degrades doctor to
  `unknown` for the new schema).
- **RE-10 — schema version 10 was skipped** (9→11 jump, no constant). Any
  external tooling that assumes consecutive schema numbers (or an old store
  at 10 — impossible, but 9→11 bumps 9 AND 10 both to 11) must know the hole.
  Cosmetic, but worth documenting for future migration writers.
- **RE-11 — user_version conflates schema and feature backfills.** The 0→1
  step is the graph backfill, gated on `graphEnabled`; a store opened with
  `graphEnabled=false` never takes step 0→1 but is otherwise fully modern.
  External consumers reading user_version as "schema" get a misleading 0.
- **RE-12 — migration sentinel leaks into product data.** The
  `author_agent_id = "schema-12-first-block-migration"` on migrated
  observations is visible through fetch/store attribution APIs; anything
  that counts per-agent activity will see a "schema-12-first-block-migration"
  pseudo-agent. Intentional marker, but downstream consumers should filter it.

## Verification notes
- Claims are source-level (v1.5.2 dist bundles); no `-d` experiment needed
  (doctor/repair behavior already verified operationally — see
  `monet-upgrade-embedder-migration.md` in the server-ops skill for the
  4→12 upgrade and the embedder-repair refusals).
- `migrateLegacyStarCircle` overlaps with the circle-routing module (next on
  the queue); the `W="*"` / `rd="legacy-star"` constants are now pinned here
  for that doc.

## Cross-check against readable TS (2026-08-16, run 34)

Validated the above (v1.5.2 dist) against the current readable source
(`packages/core/src/schema-version.ts`, `engine.ts` — commit 83e9d7d, core 0.9.0).
**Drift found: the ladder has been refactored from minified single-letter
constants + "unguarded DDL / no-op bump" into NAMED, version-gated migrations.**
Facts (sentinel, payload protocol, migration id/content formats) all survive;
the STRUCTURE description does not.

### Named ladder (engine.ts:312–356)

| version | readable constant | what it gates |
|---|---|---|
| 1 | `GRAPH_SCHEMA_VERSION` | one-time graph backfill (still gated on `graphEnabled` + a new trustworthiness check) |
| 2 | `TEMPORAL_SCHEMA_VERSION` | temporal layer — **version-gated DDL + backfill** (`last_confirmed_at`/`last_confirmed_session_id`, `dismissed_at`/`dismissed_by`) with State-A/B/C/D handling |
| 3 | `AROUSAL_SCHEMA_VERSION` | V-A arousal — **version-gated DDL + backfill** (`usefulness_last_fetched_at`, `arousal_score`, `arousal_last_updated_at`) |
| 4 | `FIRST_BLOCK_SCHEMA_VERSION` | first_block table (created by `init()`; **sentinel only**) |
| 5 | `SYNC_SCHEMA_VERSION` | sync primitives (uq_edge safety check; **sentinel**) |
| 6 | `SOURCE_SCHEMA_VERSION` | source-concept prerequisites (tables from `init()`; **sentinel**) |
| 7 | `SOURCE_REGISTRY_SCHEMA_VERSION` | knowledge_sources registry (**sentinel**) |
| 8 | `SYNC_CLOSURE_SCHEMA_VERSION` | `ensureSyncClosureSchema()` — unchanged from the doc |
| 9 | `SOURCE_LEDGER_SCHEMA_VERSION` | source ledger (**sentinel**) |
| 11 | `SOURCE_FILE_CONCEPT_SCHEMA_VERSION` | file=concept reshape (index swap + columns) |
| 12 | `FIRST_BLOCK_RETIREMENT_SCHEMA_VERSION` | `migrateFirstBlockPins()` — unchanged |

### Corrections to this doc's "no-op" labels

The doc labels 2→3, 3→4, 5→6, 6→7 as "no-op bump". In the readable source
those rungs are NOT no-ops:

- **2→3 (AROUSAL)** is real version-gated DDL + backfill — the doc's "no-op"
  label is wrong.
- **3→4 (FIRST_BLOCK)** and **5→6 (SOURCE)** / **6→7 (SOURCE_REGISTRY)** are
  *sentinels*: their tables are created idempotently by `init()`/the registry
  before `migrate()`, so the rung is a milestone marker with no DDL of its own.
  "No-op" under-describes them — each names a real subsystem.

### Other corrections

- The doc's "DDL steps before 1→2 are **unguarded by version** — they run on
  every open" is OUTDATED for temporal/arousal: those two are now version-gated
  migrations with guarded `ALTER` + backfill (State A/B/C/D for temporal), not
  an every-open "applying_remote wrap".
- **RE-09 refinement (confirms run-33 note):** `MONET_SCHEMA_VERSION = 12` is a
  SINGLE named const in `schema-version.ts` (imported by engine/diagnostics).
  The individual rung numbers are now NAMED constants, but still literal
  integers in engine.ts. RE-09 ("hardcoded in 3+ places") remains a
  *dist-bundle* concern — the readable source has centralized the top-of-ladder
  number. No change to RE-09's `source` status.
- **RE-10 confirmed:** version 10 is still skipped (9 → 11). The readable
  source's own comment on `SOURCE_FILE_CONCEPT_SCHEMA_VERSION` says "next free
  sequential slot after SOURCE_LEDGER_SCHEMA_VERSION (9)" yet the value is 11 —
  consistent with a withdrawn version-10 migration (cf. the #187 note at
  `FIRST_BLOCK_RETIREMENT_SCHEMA_VERSION`). No change to RE-10's `source` status.

### Confirmed unchanged (facts survive)

- `SYNC_PAYLOAD_PROTOCOL_VERSION = 15` (engine.ts:341) = minified `Gf` — now
  with a changelog comment (11: +lifecycle_edges/ratifications; 12: +stages/
  rule_bindings; 13: +concepts.skeleton_breadth; 14: first_block retired;
  15: +ratifications.entrance/battery).
- `FIRST_BLOCK_OBSERVATION_AUTHOR = "schema-12-first-block-migration"` (line 357) = `zT`.
- `FIRST_BLOCK_OBSERVATION_PREFIX = "First Block pin (surface retired 2026-08-02): "` (line 358) = `FT`.
- `firstBlockObservationId` = `fb-migration:` + sha256(id+`\0`+sha256(summary))[:32] (lines 364–372) = `HT`.
- `migrateFirstBlockPins` runs in `immediateTransaction`, window `[9,12) → 12` (lines 3797–3846) — matches the doc.

## Next steps
1. Circle routing / aliases lifecycle (create/archive/`*` breadth) — includes
   `resolveCircle`, `circle_aliases` statuses, `migrateLegacyStarCircle` tail.
2. Contradiction processing (flag triggers, mediation states) — RE module.
3. Re-check RE-09 against next @team-monet/monet bump (schema 13+?).
