# Reverse-Engineering Metrics

> Progress of the Monet source reverse-engineering effort (agent-ops cron).
> "Progress" = documented modules / identified parameters / found issues, by data.
> Related: root `METRICS.md` tracks E2E test-suite metrics.

## Core metrics

| Date | Modules documented | Thresholds/params identified | Issues found | Notes |
|------|-------------------|------------------------------|--------------|-------|
| 2026-08-10 | 1 — store resolution pipeline (dedup) | 6 (tauAttach, tauAmbiguous, edgeSimMin, nativeScoreFloor, wi=6, lexical boost H1=1.0) | 3 (RE-01..RE-03) | Priority-1 answered: dedup threshold located in per-model config map `pU` + `applyEmbedderDerivedThresholds`; decision fn `V1`. See `dedup-resolution.md` |
| 2026-08-11 | 2 — search pipeline (`memory_search`) | 10 (+4: default limit=5, lexical tokenizer regex (Latin-only), Ar=40000 response cap, nt=256 circle-name max) | 7 (+4: RE-04..RE-07) | Full read-side flow: store.search → oT (best-obs cosine) → q1 lexical rank boost → floor filter → default-circle tiebreak; source concepts bypass floor; Korean queries get NO lexical boost (regex Latin-only). See `search-pipeline.md` |
| 2026-08-11 | 3 — schema migration & versioning | 21 (+11: user_version ladder 0→12, supportedSchemaVersion=12, sync/graft protocol=15, first-block sentinel zT, migrated obs id scheme, content prefix, graph-backfill gate <1, first-block window [9,12), assessment `e===12`, exclusive-lock probe ±1, closure-trigger 7→8 bump) | 12 (+5: RE-08..RE-12) | No migration table — `PRAGMA user_version` scalar ladder 0→12 with idempotent `table_info`-guarded DDL; First Block pin conversion at 12 carries sentinel author; doctor/repair hardcode supported=12 (3+ places); version 10 skipped; graph backfill conflates 0→1. See `schema-migration.md` |

## Module inventory

| Module | File(s) | Status | Doc |
|--------|---------|--------|-----|
| Store resolution / dedup pipeline (`resolutionCandidates`, `rankByCentroid`, `nominateByObservation`, `oT`, `q1`, `V1`, `sT`) | dist/index.js (+ cli.js bundle) | **DOCUMENTED** | `dedup-resolution.md` |
| Embedder config map (`pU`/`XH`) & threshold application | dist/index.js, dist/cli.js | **DOCUMENTED** | `dedup-resolution.md` |
| Search pipeline (`memory_search`, `search()`, `oT`/`scoreNativeConcepts`, `q1` lexical arm, `B1`/`scoreSourceConcepts`, `nativeScoreFloor`, `resolveCircle`, `EF`/`bF`) | dist/index.js | **DOCUMENTED** | `search-pipeline.md` |
| Schema migration 4→12 | dist/index.js, dist/cli.js | **DOCUMENTED** | `schema-migration.md` |
| Circle routing / aliases / `*` breadth | dist/index.js | NOT STARTED | — |
| Contradiction processing | dist/index.js | NOT STARTED | — |
| Dashboard | dist/dashboard/* | NOT STARTED | — |

## Identified parameters (running list)

| Parameter | Value (per model) | Where | Role |
|-----------|-------------------|-------|------|
| `tauAttach` | bge-m3:cls:q8 **.70**; bge-small-en .78; all-MiniLM .72; multilingual .70; hashing .55; fallback .55 | `pU` map + `applyEmbedderDerivedThresholds` | similarity ≥ → attach/dedup |
| `tauAmbiguous` | bge-m3:cls:q8 **.50**; bge-small-en .50; all-MiniLM .50; multilingual .50; hashing .40; fallback .40 | same | ambiguous-fork band lower bound; possible_duplicate_of edge min |
| `edgeSimMin` | bge-m3:cls:q8 **.60**; bge-small-en .70; else .45/.40 | same | `related` edge lower bound |
| `nativeScoreFloor` | bge-m3 .40; bge-small-en .35; default .12 (`W1`) | `Z1`/`pU` | search result filter floor |
| `wi` | 6 | const | top-k candidate window |
| lexical boost `H1` | 1.0 | const `H1` in `j1` | rank boost `score*(1+H1*p)` |
| `W1`/`Z1` default floor | .12 | const | clamp for nativeScoreFloor |
| `reliableSegmentTokens` | bge-m3 768; bge-small-en 380 | `pU` | embedder window segmentation |
| default `limit` | 5 | `search()` | `t.limit ?? 5` (silent truncation) |
| lexical tokenizer | `/[a-z0-9][a-z0-9_-]{2,}/gu` | `Im` in `q1` | Latin-only; Korean query → empty token set → no boost |
| `Ar` | 40 000 | `bF`/`Wm` | response JSON size cap → resultsTruncated/resultsOmitted |
| `nt` | 256 | tool schema | max circle-name length |
| user_version ladder | 0→12 (10 skipped) | `Ff..UT` consts | schema milestone scalar (sole versioning) |
| `supportedSchemaVersion` | 12 | cli.js inspector ×2 (hardcoded) | doctor display + repair preflight cap |
| sync/graft protocol version | 15 (`Gf`) | `graftRows` | export payload version cap (≠ schema) |
| first-block sentinel `zT` | `"schema-12-first-block-migration"` | const | author_agent_id of migrated pins |
| migrated obs id `HT` | `fb-migration:` + sha256(id\0sha256(summary))[:32] | migrateFirstBlockPins | deterministic re-runnable id |
| migrated obs content `FT` | `First Block pin (surface retired 2026-08-02): ` | const | content prefix |
| graph backfill gate | user_version < 1 | runGraphBackfillIfPending | 0→1 milestone (feature-conflated) |
| first-block migration window | [9, 12) → 12 | migrateFirstBlockPins | when conversion runs |
| doctor assessment schema check | `e === 12` | `dW` cli.js | verdict gate (hardcoded) |
| exclusive-lock probe | user_version ±1 | acquireExclusiveOwnership | repair ownership dance |

## Stagnation detection

- 3 consecutive runs with 0 new modules/params → switch module (search → migration → circles → contradictions → dashboard).
- Found issues should be re-checked after each @team-monet/monet version bump (source diff).
