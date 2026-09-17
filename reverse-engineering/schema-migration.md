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

## RE-58 — the missing schema-version ceiling (2026-09-15, E2E-reproduced on dist 1.11.0)

Baseline (GR-08): **dist `@team-monet/monet@1.11.0`** (`1c7d1e5`), driven over public
surfaces only — `monet start` (MCP stdio), `monet doctor`, `monet repair`. Guard:
`tests/test58_re58_schema_ceiling_shipped.py` (XFAIL, exit 2 while the bug is present).

**Why it existed as a gap.** Upstream #107 ("The engine constructor has no
schema-version ceiling: a newer-than-supported store opens successfully where
repair refuses it") states its own limit: *"Inferred, not reproduced … No fixture
was built that stamps `user_version` above the ladder and opens the store, so the
actual observed failure mode — which statement throws first, what the message
says, and whether anything writes before it does — is not established here."*
This run builds exactly that fixture and answers all three questions.

**Fixture recipe (minimal, no product source needed).** Build a real store
(`monet start -d <dir>` + one `memory_store`), read `supported` from the product's
own `monet doctor` line (`Schema: 13 (supported: 13)`), then stamp above it with
stdlib sqlite3 — for the bare arm, `PRAGMA user_version=<supported+1>` on a
`monet.db` that has **zero tables** (the #156 repro shape). Two arms are needed:

- **arm A** — bare store, 0 tables, `user_version = supported+1 (14)`.
- **arm B** — real store with a seeded observation, then stamped to the same value
  (the downgrade journey: does an older build serve rows it cannot name?).

**Measured (both arms, 1.11.0).**

| probe | arm A (bare, 14) | arm B (seeded, 14) |
|---|---|---|
| `monet start` | **accepted** — no refusal, stderr `Monet started` | **accepted** — `Monet started` + storage/circle banner |
| store after open | `user_version` **14** (unchanged), tables **0 → 27**, `-wal`/`-shm` created | `user_version` **14**, pre-existing observation still retrievable by `memory_search` |
| writes | `memory_store` + `memory_search` succeed; the row survives a **second, independent session** | — |
| `monet doctor` | `Schema: 14 (supported: 13)`, `Assessment: unknown` (rc 2) | same |
| `monet repair` | **refuses**: `Store schema 14 is newer than supported schema 13; refusing repair.` (rc 1) | same |

**Answers to #107's three questions.** (1) *Which statement throws first* — **none**.
Nothing throws: the constructor, the store-open path and the write path all run
clean, because the **version ladder is skipped above the ceiling** while the
idempotent, `table_info`-guarded table-ensuring DDL runs **unconditionally** — so a
store this build cannot name gets a full 27-table layout stamped onto it. (2) *What
the message says* — there is **no message**: the failure #107 predicts is deferred
past every surface the user touches. (3) *Whether anything writes before it does* —
**yes, and that write is the engine's own bootstrap DDL**, so "the store is
untouched because the caller wrote nothing" is false; the store is rewritten by the
open itself.

**The asymmetry is behavioral, not just code-read.** `monet repair` refuses the
exact store `monet start` happily serves (same process family, same version). So a
user whose store is one schema ahead of their binary gets a working-looking server
and a refusal from the one tool that would have told them to upgrade.

**Hazard (framed conservatively).** Every subsequent write lands in a store whose
schema this binary does not know, so the write is unsupported **by construction**
(an older binary can write rows a newer schema reads differently). **No data loss
was observed in this run** — the measured defect is the *silent acceptance*, not a
demonstrated corruption. Desired contract: refuse to open, writing nothing.

**Flip semantics (release-content only — NOT "the next bump").** This guard flips
only in a release whose contents actually carry the #155 ceiling change; a version
bump by itself does not flip it. The guard's flip signal is the REFUSAL only.
The ceiling fix is PR #155, **OPEN and NOT merged** as of 2026-09-16 (direct
PR-state read: `state=OPEN`, `mergedAt=null`, HEAD `e81db7b`; `main` HEAD
`9fa38c2`, and the shipped 1.11.0 bundle contains 0 occurrences of
`readStoredSchemaVersion` / `refusing to open`), so neither `main` nor 1.11.0
carries the ceiling. Upstream #156 records that the
fixed CLI still writes the circle map before refusing, so test58 deliberately does
**not** assert a write-free store — asserting it would turn a fix into a FAIL. The
four stable invariants (`doctor` schema line, `Assessment: unknown`, `repair`
refusal text + rc, version unchanged after the journey) hold **before and after**
the fix and therefore stay hard `check()`s: if one of them breaks, the *test* is
wrong.

### Flip-time checklist — pre-registered from the PR's own shape (2026-09-17, run 116)

Upstream #155 moved after the 2026-09-16 record: a third commit landed on the
branch (`770cd98`, 2026-09-16T21:52:31Z, "fix(core): keep the schema-version
preflight side-effect-free on WAL stores"), still **OPEN / `mergedAt=null`**,
base `main`, CI 4/4 green. Read at run time (G-5), not carried forward. It matters
to this guard because it changes the read strategy of `readStoredSchemaVersion` —
the function whose absence is this RE's shipped-side signature — so the flip
procedure is pre-registered here instead of being improvised at flip time.

What the new HEAD does (read from the PR diff; **unreleased — not measured**):
the preflight now branches on the store's sidecar shape.

| sidecar shape | preflight read | consequence at flip |
|---|---|---|
| no `-wal`/`-shm`/`-journal` | SQLite file header, offset 60 (no SQLite connection) | conclusive; the new commit's "side-effect-free" path |
| `-wal` + `-shm`, no `-journal` | readonly connection, zero timeout (as before) | conclusive |
| any other shape (orphan `-wal`, `-journal` present, malformed) | returns `null` → *live port decides* | refusal depends on the constructor's live re-check |

The engine-side refusal itself is **untouched** by `770cd98` (its 4 changed lines
are a comment; the diff solely rewrites the comment to cite #156). **Flip signal
is unchanged: the REFUSAL only.**

**Fixture shapes measured this run (installed 1.11.0, isolated temp stores):**

| arm | files at journey start | branch after the fix |
|---|---|---|
| A — bare store, `user_version` stamped, stdlib `sqlite3` clean close | `monet.db` only (`journal_mode=delete`) | HEADER |
| B — real store built by an MCP session, harness `close()` | `monet.db` + `moments.jsonl` (`journal_mode=wal`, WAL checkpointed, sidecars removed) | HEADER |
| stray: `-wal` without `-shm` | `monet.db` + `monet.db-wal` | NULL → live port |
| stray: `-journal` present | `monet.db` + `monet.db-journal` | NULL → live port |

So both of test58's arms present a *conclusive* preflight in the fixed build —
the guard does not silently depend on the live re-check.

Steps to run when a release carries the ceiling change:
1. Re-run test58 unmodified and require **XPASS (exit 3)**; a still-XFAIL means the
   release did not carry the change (a bump alone is not a flip).
2. Additionally confirm the refusal still fires on the **stray-sidecar shapes**
   (test58's two arms do not cover them) — that path is now decided by the live
   re-check, so it is the one place the ceiling could regress unnoticed.
3. Report residue as a **measurement, not an assertion**: the cleanly-closed arms
   should leave no new `-wal`/`-shm`, but #156 (now cited in `engine.ts`'s own
   comment on this HEAD) keeps the CLI's pre-engine circle-map open alive, so a
   write from that path may still appear. Asserting absence would turn the fix
   into a FAIL — keep the write-free check out of the guard.

### Flip-time assertion constraints — measured upstream evidence on HEAD `770cd98` (2026-09-17, run 117)

Run 116 pre-registered the checklist from the HEAD's *diff*. This run adds the
*measured* upstream evidence: the John-waived round-4 substitute review was spent
on exactly this HEAD (`770cd98`, still `state=OPEN` / `mergedAt=null`, 4/4 checks
green, `mergeStateStatus=CLEAN`) and its verdict is **`findings` (2×P2 + 2×P3)**,
so **the merge gate is withheld and #155 will not merge without a further human
ruling** — the flip precondition (a release that actually carries the ceiling)
is therefore no closer than it was, and RE-58 stays XFAIL. Facts read this run
(G-5: direct PR read + the branch's review artifact, not carried forward); the
review's own measurements are **upstream-reported, unreleased, and not
re-measured here** — they constrain what the flip check may assert:

1. **The NULL-preflight branch is the least-verified path in the fix.** On
   `770cd98` no committed test can make `readStoredSchemaVersion` return `null`
   (`grep -cE "mock|spyOn|-journal|asymmetric"` over
   `schema-version-ceiling.test.ts` → 0); all 11 tests decide via the header
   (sidecar-free fixtures), the `-wal`/`-shm` peek, or a caller-supplied port.
   **Directly re-verified this run** by fetching that file at ref `770cd98`
   (read-only, unreleased branch — not the GR-08 baseline): 343 lines, `  it(`
   → **11**, `mock|spyOn` → **0**, `-journal|asymmetric` → **0**, refusal
   assertions `toBe(refusal())` / `/newer than supported/` at 203/212/227/257/283/
   306/337. ⇒ step 2 of the checklist (stray-sidecar shapes, which test58's two
   arms do **not** cover) is not optional polish — it is the only coverage that
   path has.
2. **On the NULL shape the ceiling is decided only AFTER the write port opens**
   (`engine.ts:2971` before `2974`), so the refusal inherits the port's busy wait
   against a locking peer (reviewer-measured: `journal_mode = WAL` blocked
   **8147 ms** behind an 8 s exclusive holder) and can surface as
   `(locked): database is locked` instead of the ceiling refusal. ⇒ **probe the
   stray shapes lock-free and single-writer**, and treat a `database is locked`
   result as *inconclusive* — neither a flip failure nor a flip success.
3. **The fix is shape-dependent, not universal:** on `-journal` and asymmetric
   shapes the store is **converted and modified before the refusal** (verified
   independently by the dev lane: header bytes 18/19 flip `1,1`→`2,2`,
   `-journal` removed, `-wal`/`-shm` created on a `user_version=14` store, and
   only then is `14` read). Side-effect-free holds for the sidecar-free shape and
   the `-wal`+`-shm` peek shape only. ⇒ at flip time, assert the **refusal**, never
   write-freeness, on any shape (run 116's constraint, now with measured cause).
4. **Residue has no issue of its own.** The shape-specific pre-refusal conversion
   (3) and the ordering/deferral (2) are stated only in #155's PR body
   known-gaps section; #107 covers the ceiling's absence and #156 the CLI
   circle-map path. Flagged for the dev lane — **E2E does not file** (halt list:
   no upstream triage, and it is the same defect family).

5. **The refusal message is compatible with test58's flip assertion (directly
   verified this run, ref `770cd98`).** `engine.ts:2967-2968` / `2980-2981` build
   the message as `Store schema ${v} is newer than supported schema
   ${MONET_SCHEMA_VERSION}; refusing to open. Upgrade Monet first.` — it contains
   the literal **`newer than supported`** that test58 checks
   (`refusal_names_both_versions`), so the guard will not produce a *false
   failure* at flip time on message mismatch. (Pre-registered because the branch
   tests mix two expectation styles — `toBe(refusal())` for the
   `captureOpenError` fixtures and `/newer than supported/` for the header/peek
   ones — so a future reword of either site would have to be caught here.)

Shipped-side baseline re-measured this run on dist 1.11.0 (sha256 `0c579e23…`,
unchanged): `readStoredSchemaVersion` 0 / `refusing to open` 0 / `newer than this
build` 0 / `readSchemaVersionFromSqliteHeader` 0, `newer than supported schema` 2
(`monet repair` only) → the fix is still absent from the served build; RE-58's
reproduction stands.

### Flip guard discharged against run 117's constraints + the stray shapes measured on the SHIPPED build (2026-09-18, run 118)

Run 117 left three obligations on the flip guard (constraints 1–3 above: cover the
stray-sidecar shapes, probe lock-free and treat `database is locked` as
inconclusive, never assert write-freeness). This run discharged all three in
test58 and, as a side effect of building the fixtures, produced the **first
shipped-side measurement of those two shapes** — the shapes the fixed build routes
through its `null` preflight.

**test58 is now a four-arm guard** (was two): `A_bare_header` (sidecar-free, uv=14,
zero tables), `B_real_header` (real seeded store, stamped 14), plus the two shapes
run 116/117 said test58 did not cover:

| arm | pre shape | how the fixture is built |
|-----|-----------|--------------------------|
| `S1_orphan_wal` | `monet.db` + `monet.db-wal`, **no `-shm`** | 1-table WAL store (marker, uv=14) copied out of a STILL-OPEN WAL connection → real frames, no shm |
| `S2_hot_journal` | `monet.db` + `monet.db-journal` (a **hot** journal) | 1-table DELETE-journal store (marker, uv=14) copied while `BEGIN IMMEDIATE` + INSERT is open |

**Result on shipped 1.11.0 (`verdict=xfail`, exit 2): all four arms accepted and
served.** No arm refused, nothing threw — the two preflight shapes run 117 singled
out as the fix's least-verified path are, on the shipped build, simply *more* of the
same silence. Per-arm post-journey DB state (measured this run; `state()` opens a
copy, and the printed pre-shapes are the arm's own, captured before the journey):
**"Served" is a measured user path, not a handshake**: every arm then took an
independent-session `memory_store` → `memory_search` round trip and returned the row
it had just written (`repro_stray_shape_served_S1_orphan_wal` /
`_S2_hot_journal`, hits=1 each; header arms via
`repro_write_and_search_on_newer_store` and
`repro_older_build_serves_pre_existing_rows`). So on the stray shapes too, the
shipped build will **accept writes into a store it cannot version-check and serve
them back to the agent**.

| arm | tables | `user_version` | sidecars after |
|-----|--------|----------------|----------------|
| `A_bare_header` | 0 → 27 | 14 → 14 | `monet.db` → WAL trio |
| `B_real_header` | 27 → 27 | 14 → 14 (stamped from 13) | `moments.jsonl`, `monet.db` → WAL trio |
| `S1_orphan_wal` | 1 → 28 | 14 → 14 | `db`+`-wal` → WAL trio (gains `-shm`) |
| `S2_hot_journal` | 1 → 28 | 14 → 14 | `db`+`-journal` → **WAL trio: the hot journal is converted** |

Two things this adds to the flip checklist that no earlier run measured:

1. **Below the ceiling, every shape writes.** The above-ceiling store is not merely
   opened: the older build's bootstrap runs 27 `CREATE TABLE`s, converts
   `journal_mode` to WAL (including converting a HOT `-journal`, i.e. replaying/
   discarding a foreign journal mid-flight), and then serves reads and writes
   (store→search round-tripped on all four arms this run). This
   is the shipped-side counterpart of constraint 3: write-freeness was never a
   property of the unfixed build on ANY shape, so a flip-time assertion of it would
   contrast two different shape sets rather than two builds.
2. **`user_version` is never re-claimed.** All four arms end at 14 — the build
   bootstraps a schema it cannot name and leaves the stamp claiming 14. The
   "keeps claiming a schema this build cannot name" observation (run 114) holds on
   the stray shapes too, so post-journey `user_version` is a stable flip-side
   invariant, not an artifact of one shape.

Guard mechanics added this run (`harness/run_all.py` + test58): the accept/refuse
decision is factored into one testable `verdict()` (xpass / xfail / inconclusive)
with a self-check arm that pins the classification on synthetic state tuples, and
**exit code 4 = INCONCLUSIVE** is plumbed through `run_all.py` — it fails neither
the suite nor the flip (a `lock`/other `failure` startup result is neither), and the
run summary prints `INCONCLUSIVE` separately so a contended probe cannot be read as
a fix. `journey(store)` runs the public surface (handshake → tools/list → store →
search) sequentially, so the probe stays single-writer per constraint 2.

Upstream state re-read directly this run (G-5): #155 still `state=OPEN`,
`mergedAt=null`, head `770cd98` (unchanged since run 116), `mergeStateStatus=CLEAN`,
updated 2026-09-16T22:09Z; `main` = `9fa38c2`; npm `latest` = 1.11.0 = installed. The
ceiling is in neither `main` nor the served build, so RE-58 remains XFAIL — a bump is
still the only flip signal, and it has not happened.

## Next steps
1. Circle routing / aliases lifecycle (create/archive/`*` breadth) — includes
   `resolveCircle`, `circle_aliases` statuses, `migrateLegacyStarCircle` tail.
2. Contradiction processing (flag triggers, mediation states) — RE module.
3. Re-check RE-09 against next @team-monet/monet bump (schema 13+?).
