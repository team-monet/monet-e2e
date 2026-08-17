# Monet Reverse-Engineering — Issue Registry

> Consolidated list of every issue found across the reverse-engineering effort.
> Detail lives in the per-module doc named under **Source**; this table is the
> one-line index.

## Status

- **open** — a real gap, product question, or maintenance risk found at the
  source level but not yet verified either way.
- **source** — verified by source reading only. A structural / code-quality
  issue that E2E cannot test (no observable behavior); routes to the code-fix
  (L2) queue, not the E2E verifier.
- **confirmed** — verified against the E2E test-suite (behavioral), not just
  source-level. The test named in `e2e_test` reproduces it.
- **fixed** — was a real bug (open/confirmed), now verified resolved in a
  specific Monet version (E2E XPASS + source-diff cross-check).
- **by-design** — documented behavior, a known trade-off, or future work.

## Severity (preliminary — source-level estimate; E2E-measured impact upgrades it)

- **S1** — data loss / corruption / silent wrong result.
- **S2** — scalability / operability (will bite in production) / security.
- **S3** — missing signal / UX / maintenance risk.
- **S4** — cosmetic / by-design note.

`e2e_test` names the test that proves the issue (an `XFAIL` test documents a
still-open bug and flips to `XPASS` when fixed); `—` = not yet E2E-verified.

| ID | One-line summary | Source | Status | e2e_test | severity |
|----|------------------|--------|--------|----------|----------|
| RE-01 | Dedup thresholds (tauAttach/tauAmbiguous) invisible to users — no CLI flag/env var/README; can't tune without patching source | dedup-resolution.md | source | — | S3 |
| RE-02 | Attach requires obsScore≥tauAttach AND centroidScore≥tauAmbiguous → a drifted centroid repels valid attaches into fork-signal | dedup-resolution.md | by-design | — | S4 |
| RE-03 | Resolution core fully duplicated between dist/index.js and dist/cli.js bundles (V1/sT vs xH/IN); patches must touch both | dedup-resolution.md | source | — | S3 |
| RE-04 | Lexical rank arm is Latin-script-only (`/[a-z0-9][a-z0-9_-]{2,}/`) → Korean/Japanese queries get zero lexical contribution | search-pipeline.md | confirmed | test30 | S3 |
| RE-05 | Source concepts skip nativeScoreFloor (any score>0 enters) while native concepts below floor are dropped — intentional? | search-pipeline.md | open | — | S4 |
| RE-06 | Search is O(eligible segments) brute-force scan, no ANN index; cost grows linearly with store size | search-pipeline.md | by-design | — | S4 |
| RE-07 | `limit` truncation is silent — no flag tells the caller more matches existed | search-pipeline.md | confirmed | test22 | S3 |
| RE-08 | Migration steps run outside one transaction (version is a milestone, not a ledger); half-migrated state reports old version | schema-migration.md | by-design | — | S4 |
| RE-09 | supportedSchemaVersion=12 hardcoded in 3+ places; next schema bump must touch all in lockstep or doctor silently degrades | schema-migration.md | source | — | S3 |
| RE-10 | Schema version 10 skipped (9→11 jump); external tooling assuming consecutive numbers must know the hole | schema-migration.md | source | — | S4 |
| RE-11 | user_version conflates schema and feature backfills (0→1 graph backfill gated on graphEnabled) | schema-migration.md | source | — | S3 |
| RE-12 | Migration sentinel `author_agent_id="schema-12-first-block-migration"` leaks into product attribution APIs | schema-migration.md | by-design | — | S4 |
| RE-13 | Contradiction statuses are raw string literals across 6+ functions, no shared enum | contradiction-processing.md | source | — | S3 |
| RE-14 | Store-side auto-flag fires only when correction ATTACHES; a correction that creates (below tauAttach/forceNew) opens no contradiction | contradiction-processing.md | by-design | — | S3 |
| RE-15 | memory_fetch status/openContradictions depend on derived column; latent coupling if a closer ever skips recompute | contradiction-processing.md | by-design | — | S4 |
| RE-16 | Explicit-circle recall bypasses archive hide (active alias → archived name still resolves) | circle-routing.md | by-design | — | S4 |
| RE-17 | storeInternal has no archived-circle guard: memory_store into an archived circle succeeds silently | circle-routing.md | confirmed | test24 | S3 |
| RE-18 | renameCircle doesn't refuse when `from` is an active alias to a third circle; upsert silently re-targets it | circle-routing.md | by-design | — | S4 |
| RE-19 | mergeCircle HARD-DELETES workstream concepts (no tombstone/confirmation), counts as noop | circle-routing.md | fixed | test23 | S2 |
| RE-20 | Every dashboard API request copies the whole store (~0.4–0.5s on 75MB); scales linearly, no cache/ETag | dashboard.md | by-design | — | S3 |
| RE-21 | graphDensity includes possible_duplicate_of edges, slightly inflating "structural density" | dashboard.md | confirmed | test27 | S4 |
| RE-22 | Dashboard is local-only, read-only, Host-allowlisted — positive security posture, no remote-monitoring path | dashboard.md | by-design | — | S4 |
| RE-23 | `monet start` derives a fallback identity (`local-agent` / `<basename>-<sha8>`) when MONET_CALLER_ID/MONET_PROJECT_ID are unset, so `source_list` silently returns `[]` and `source_status`/`source_path`/`source_sync` return the non-disclosing "source is unavailable" — the identity mismatch is NOT discoverable (a caller sees a clean "no sources" state) | sources-sync.md | confirmed | test26 | S3 |
| RE-24 | updateSource lets `access` be mutated, silently de-authorizing the host that registered/syncs the source | sources-sync.md | confirmed | test28 | S2 |
| RE-25 | MCP source_sync is synchronous/blocking (awaits full clone→chunk→hash→embed→publish→verify); can exceed MCP timeouts | sources-sync.md | by-design | — | S4 |
| RE-26 | gate_events has NO retention/pruning; grows with agent activity (2–3 orders > resolution_events), will become largest table | gates.md | confirmed | test29 | S2 |
| RE-27 | Conformance "cheap half" can only emit `changed` for blocking denies; advisory fires stay `unavailable` → advisory rules un-retirable until judgment half ships | gates.md | by-design | — | S4 |
| RE-28 | gate_events.action_context stores raw intercepted commands verbatim (paths/hostnames/flags) — most privacy-sensitive column; local-only + scrub-covered | gates.md | by-design | — | S3 |
| RE-29 | `-d` isolates the SQLite DB but NOT source storage — `sourceStorageDir` hard-defaults to `~/.monet/sources` via `homedir()` with no `-d` scoping / CLI/env override; isolated-source work silently writes to prod | sources-sync.md | confirmed | test25 | S2 |
| RE-30 | repo-md `source_sync` fails `EACCES` on macOS — `sealSnapshot` chmods the tree `0o500` then `renameSync` into place; APFS refuses the in-place rename of a non-writable dir, so the stage-beside-variant mitigation (source-materializer.ts:2225) is insufficient on macOS 15.x | sources-sync.md | confirmed | test25 | S2 |
| RE-31 | V-A living-model tunables hardcoded module constants, not constructor opts (usefulness tau=60d, arousal tau=120d, arousal floor 0.1, arousal weight 0.5, recency half-life 14d inline) — can't tune without patching source; recency 14 is a bare magic number vs the named usefulness/arousal taus | living-model-ranking.md | source | — | S3 |
| RE-32 | `livingModelCard` discards the ranking score + per-signal breakdown (returns id/title/kind/confidence/supportCount) — the ordering is opaque: a caller sees that a concept ranks high but not why (recency vs usefulness vs arousal) | living-model-ranking.md | confirmed | test32 | S4 |
| RE-33 | `slow-queries.jsonl` (statement-trace slow log) is write-only: `readInflightStatements` gives the in-flight marker a consumer (lock-contention path in storage.ts) but nothing reads/surfaces the slow log — the retrieval-degradation diagnosis it exists to provide has no doctor/CLI/MCP path | statement-trace.md | confirmed | test31 | S3 |
| RE-34 | Lifecycle-edge cross-circle invariant is checked at creation but NOT maintained: a later `reassignCircle`/`moveConcept` moves one endpoint into another circle and leaves the edge standing with a `circle` value that no longer names both endpoints (append-only; `circle` is provenance, not live locality) | lifecycle-edges.md | by-design | — | S4 |
| RE-35 | `lifecycleEdgeIntegrity()` (dangling-edge sweep) is a public `MonetCore` method with NO operator surface — not exposed as an MCP tool or CLI command (unlike `inspectStoredEmbedderState`, which backs `doctor`/`repair`); report-only, library-only reachability, and moot today (no producer of lifecycle edges yet) | diagnostics.md | source | — | S4 |
| RE-36 | `splitUtf8` in the source chunker segments by UTF-8 code point, not grapheme cluster, so an over-budget chunk split can land between a base char and its combining marks (decomposed Hangul 자모, ZWJ emoji), leaving a dangling combining mark at a chunk boundary | source-chunker.md | source | — | S4 |
| RE-37 | `renderOverview` (the terminal curation workbench renderer) is exported as public API but has NO operator surface — no CLI command (`start/status/config/dashboard/source/doctor/repair/resegment/gate/install/materialize`) and no MCP tool call it; `memory_overview` returns JSON and `monet status` returns statistics. The gates.test.ts comment asserts it "is what the CLI prints", so it is intended-but-unshipped (or formerly wired). Mirrors RE-35 but higher severity (primary human view) | render-overview.md | source | — | S3 |
| RE-38 | `extractEntities` logic is duplicated between `extract-entities.ts` and its byte-for-byte `extract-entities.mjs` mirror (added so plain-node `scrub-db.mjs` can re-run the same extraction without a TS-import dependency). Same "two files must change in lockstep" risk as RE-03, but lower severity because drift is caught by a mirror-identity test | extract-entities.md | source | — | S4 |
| RE-39 | The "result truncated" note text is dead and duplicated: `RESULT_TRUNCATE_NOTE` (module scope) and a byte-identical local `okNote` (memory_fetch) are each referenced ONLY via `.length` as sizeBudget headroom — neither string is ever emitted. When `ok()` actually exceeds the ceiling it emits a DIFFERENT wording ("…the original payload was omitted."). Two dead copies of a note + a wording divergence (the reserved note suggests narrowing/lowering `limit`/`memory_fetch`; the emitted note only says "payload omitted") | mcp-server.md | source | — | S4 |
| RE-40 | `RegisterMonetCoreToolsOpts.checkpointNudge` is a deprecated no-op ("Checkpoint response nags are no longer emitted") still present in the public options interface — dead API surface | mcp-server.md | source | — | S4 |
| RE-41 | `cosine(a, b)` computes the dot product over `Math.min(a.length, b.length)` and returns a value in `[-1,1]` for ANY two vector lengths — a mismatched-dimension comparison yields a plausible-looking but meaningless score instead of erroring, silently re-opening (one level down) the cross-space compare that `PinnedStoreEmbedderUnavailableError` and the graft `EmbedderMismatchError` exist to fail LOUD on. Latent: no call site reaches it with mismatched dims (provider `dim` contract + `validateEmbeddingProviderOutput` + pin/graft guards all precede it) | embedding.md | source | — | S4 |
| RE-42 | `monet repair --target` accepts any unrecognized string as an exact model ID — `resolveTargetAlias` special-cases only onnx/hashing/blank/`dim:` and returns everything else verbatim, and no profile-registry check exists anywhere in the preflight→`migrateEmbeddings` path. A loadable-but-unregistered `owner/repo` id silently repins the store into an unmeasured space (`mean` pooling, legacy thresholds, fallback budgets) with the verified backup as the only mitigation; a typo surfaces as a download error misread as a network problem. The `readsOnlyLatinScript` one-way guard cannot fire for unregistered targets (field is profile-derived → `undefined`). Fix needs core to expose a "known profile" accessor (registry is module-private) | repair-cli.md | source | — | S1 |
| RE-43 | `monet repair` self-deadlocks on every English-only target: `recheckNonEnglish` opens a second better-sqlite3 connection via `inspectStoredEmbedderState` while `applyRepair`'s port holds exclusive ownership (`createVerifiedBackup` retains it; `releaseExclusiveOwnership` is catch-only) → `SQLITE_BUSY` after the 5s busy_timeout. Deterministic, single-process. Only workaround `--accept-non-latin-loss` disables the very guard the recheck enforces. Fails closed (no rewrite, backup retained) | repair-cli.md | confirmed | test33 | S2 |
| RE-44 | `monet materialize` renders an unsynthesized (dirty) skeleton concept's concatenated body as governing text — `skeletonMemberRows` filters on status/verdict but has NO `dirty`/`needsSynthesis` guard, so an amended principle ships both old+new paragraphs and `mirrorStale` reports green (block hash matches the store). Silent wrong governing text on the always-on surface, recoverable via synthesize+rematerialize | materialize-cli.md | confirmed | test34 | S2 |
| RE-45 | `busy_timeout=5000` is starved by multi-minute concurrent write bursts (single WAL writer slot vs ~12 long-lived `monet start` processes); `memory_fetch` is a HIDDEN WRITER — `getConcept` runs an unprotected usefulness-bump UPDATE + may inline-synthesize a dirty concept, so a competing writer's burst makes even "reads" report `database is locked` (upstream #19) | storage.md | open | — | S2 |
| RE-46 | Nothing bounds a statement: better-sqlite3 11.10.0 exposes no `interrupt`/progress handler, so one query can hold the write lock indefinitely (`busy_timeout` bounds *waiting*, not *holding*); `inspectStoredEmbeddingRows`/`readLiveEmbeddingRows` materializes every row's full embedding JSON via `.all()` before the fold (upstream #20) | storage.md | source | — | S2 |

## Maintenance notes

- **E2E verification loop (2026-08-14):** behavioral `open` issues are converted
  into XFAIL tests (`run_all.py` exit 2 = known-bug documented, expected; exit 3
  = XPASS, bug appears fixed). The test name is recorded in `e2e_test`; when a
  test flips XFAIL→XPASS the issue status moves to closed and severity is
  re-assessed against the measured impact.
- Structural issues (`source` status) cannot be E2E-verified — they route to the
  code-fix (L2) queue, whose changes are then regression-gated by the E2E suite.
- Re-check `open`/`confirmed` issues against each `@team-monet/monet` version
  bump (source diff).
- New issues get the next free `RE-NN`, a row here, and detail in the owning
  module doc.
- The `sources-sync.md` module doc records RE-23..25; `gates.md` records RE-26..28.
- **E2E verification loop (2026-08-15, run 31):** three behavioral `open` issues converted
  to XFAIL tests and CONFIRMED — RE-26 (gate_events retention, test29), RE-04 (Latin-only
  lexical arm drops Korean, test30), RE-33 (slow-queries.jsonl write-only, test31).
  RE-29 e2e_test column fixed (`—` → `test25`).
- **Reclassifications (2026-08-15, run 31):** RE-01 / RE-09 / RE-11 / RE-31 reclassified
  `open` → `source` (structural, no observable behavior — route to the L2 code-fix queue,
  not the E2E verifier). RE-14 reclassified `confirmed` → `by-design`: test18 confirmed the
  DISJOINT correction case (creates its own concept, opens no contradiction) is
  correct-by-design; the below-threshold fork nuance (no possible_duplicate_of on an
  ambiguous fork) is the same by-design fork semantics as RE-02, not a verified bug.
- **E2E verification loop (2026-08-15, run 32):** RE-32 (`livingModelCard` drops the
  ranking score) converted to XFAIL test32 and CONFIRMED — the card emits
  `{id,title,kind,confidence,supportCount}` with no numeric rank signal, so the
  `livingModelScore`-ordered living model is opaque (a concept fetched 4x ranked
  LAST with no way to see why). RE-10 reclassified `open` → `source` (schema-version
  ladder hole is a documentation/tooling note, no observable wrong behavior).
- **Version bump re-check (2026-08-15, run 32):** `@team-monet/monet` 1.6.1 → 1.6.3
  available on npm. Installed 1.6.3 to an isolated prefix and ran the FULL suite: 23
  MCP tools identical, root `--help` identical, all 31 tests produce IDENTICAL results
  (21 pass / 9 xfail / 1 xpass / 0 fail). No tracked bug (RE-04/07/17/21/23/24/26/30/33)
  was fixed and no regression was introduced — 1.6.3 is a safe upgrade candidate that
  does not resolve any open XFAIL. Prod install stays at 1.6.1 (upgrade is John's call).
- **Readable-TS documentation pass (2026-08-15, run 33):** documented two previously
  undocumented engine subsystems from readable TS — `diagnostics.md` (the `monet doctor`/
  `repair` embedder-state preflight: safety assessment ladder, snapshot isolation #188,
  pin/population/migration/non-Latin inspection, and the report-only lifecycle-edge
  integrity sweep) and `source-chunker.md` (Markdown → deterministic chunks: frontmatter
  parser, sectioning, minimum-chunk merge, segmentation, hashing, sourceRef). New issues
  RE-35 (lifecycleEdgeIntegrity has no operator surface) and RE-36 (splitUtf8 splits by
  code point not grapheme). Cross-check note: `MONET_SCHEMA_VERSION=12` is a single named
  const in the readable source — RE-09 is a dist-bundle concern, not a source one.
- **Sources E2E isolation (2026-08-14):** `sourceStorageDir` = `resolve(homedir(),
  ".monet", "sources")` and is NOT wired to `-d` (RE-29). To test sources without
  touching prod `~/.monet/sources`, redirect `HOME` to a temp dir for BOTH the
  CLI `source add` and the MCP server subprocess (test25 does this; the
  `source_storage_isolated_via_home` check proves the redirect worked).
- **Minified-doc drift cross-check (2026-08-16, run 34):** cross-checked
  `search-pipeline.md`, `dedup-resolution.md`, `schema-migration.md` against the
  readable TS (`retrieval.ts`, `resolution.ts`, `lexical-overlap.ts`,
  `embedding-onnx.ts`, `schema-version.ts`, `engine.ts`). Result:
  **search + dedup are accurate (no drift)** — every constant, the SQL, the
  `MODEL_PROFILES`≡`pU` table, `DEFAULT_MODEL`≡`uU`, and
  `applyEmbedderDerivedThresholds` are value-for-value identical; the readable
  source only adds rationale. **schema-migration has real drift**: the ladder was
  refactored from minified single-letter constants + "unguarded DDL / no-op bump"
  into NAMED version-gated migrations (`GRAPH=1 … FIRST_BLOCK_RETIREMENT=12`); the
  doc's "no-op bump" labels for 2→3/3→4/5→6/6→7 are wrong (2→3 = AROUSAL is real
  version-gated DDL; 3→4/5→6/6→7 are named sentinels), and "DDL unguarded on every
  open" is outdated for temporal/arousal. Doc corrected in-place. RE-09 and RE-10
  confirmed unchanged (`source` status); version 10 still skipped (9→11).
- **Source subsystem provisionally retired (2026-08-16, run 37):** the author's
  own commit (team-monet/monet `eafaf3c`, John Lee, 2026-08-15, v1.6.3) declares
  the source subsystem *"provisionally retired"* and withdraws ~90 lines of the
  npm README's `monet source` docs. Commands and MCP tools are untouched and
  still work — it is a docs/product-direction signal, not a behavioral change.
  Implication: **RE-30, RE-29, RE-24 (S2), RE-23 (S3), and the RE-30-blocked
  RE-05 are all source-subsystem issues on a deprecation path** — their fix
  priority drops; fix only if sources are revived. The 3 source E2E tests
  (test25/26/28) stay as regression guardrails. Recorded in `L2-code-fix-queue.md`
  (new "Product-direction signal" section) and `sources-sync.md` (retirement
  banner). Run 36 had misread this commit as "docs-only, no behavioral change"
  and missed the prioritization implication.
- **Foundational-module documentation (2026-08-16, run 38):** documented the three
  remaining undocumented readable-TS modules that were NOT in the DIRECTION halt
  list and were queued by run 35: `storage.ts` (the `StoragePort` persistence seam,
  `BetterSqlitePort`, exclusive-ownership dance for `repair`, verified repair
  backup, `readStoredEmbedderPin`/`readStoredVectorPresence` read-only peeks),
  `embedding.ts` (the `EmbeddingProvider` model-adapter seam, the four per-space
  flags, `HashingEmbeddingProvider` with tokenizer versioning, vector helpers), and
  `store-embedder.ts` (the `chooseStoreEmbedder` three-state startup decision and
  the no-silent-downgrade refusal). One new issue: **RE-41** (`cosine()`'s
  `Math.min` length handling silently re-opens the cross-space-compare failure the
  pin/graft guards exist to fail loud on — latent S4). Modules 19→22, issues
  40→41.
- **Upstream issue batch cross-reference (2026-08-16, run 39):** JohnOnLee filed
  ~20 issues on `team-monet/monet` (recreated 2026-08-16 from the private
  `monet-client` tracker). Three point at CLI modules not yet in this registry and
  are now registered with source verification: **#15 → RE-42** (repair `--target`
  accepts arbitrary id, S1), **#14 → RE-43** (repair self-deadlock on English-only
  target, S2, `open`/XFAIL candidate), **#23 → RE-44** (materialize renders dirty
  skeleton body, S2, `open`/XFAIL candidate). Line numbers in #14/#15 verified
  exact against the current readable source (no drift). The remainder map to
  already-documented or DIRECTION-halt-listed modules and are cross-referenced, not
  re-analyzed: #16 (source retirement → RE-23/24/29/30, run 37), #2 (Korean search
  → RE-04/05), #8 (agents/stig.md tool-name omission — already known),
  #26-30 + #31-33 (gate instrumentation / dashboard epics — `gates`/`dashboard`
  are halt-listed), #19/#20 (storage busy_timeout starvation / no `interrupt` —
  `storage.ts` documented run 38, specific findings not yet independently
  RE-registered), #13 (mcp startup "transport connects last" — `mcp-server.ts`
  documented run 35), #17 (surfaces emitting a verdict where they hold a not-known
  — multi-module), #12/#21/#22 (startup/CI test-infra flakes).
- **E2E verification loop (2026-08-17, run 40):** RE-43 and RE-44 converted to
  XFAIL tests and CONFIRMED. **RE-43** (repair self-deadlock, test33): an
  all-English store + `repair --target Xenova/bge-small-en-v1.5 --apply --yes`
  fails `database is locked` (SQLITE_BUSY) — `recheckNonEnglish` opens a second
  connection under `applyRepair`'s exclusive lock; fails closed (backup retained,
  store stays on bge-m3:cls:q8). **RE-44** (materialize dirty skeleton, test34):
  a principle amended via near-identical re-declare attaches (`action=attached`)
  → `needsSynthesis=True`, obs=2, body = old+new concatenation, and `materialize`
  renders BOTH paragraphs verbatim with `mirrorStale` green (no dirty/needsSynthesis
  guard in `skeletonMemberRows`). Both `open` → `confirmed`, `e2e_test` set
  (`—` → test33/test34), GitHub issues #9/#10 commented + closed. Both join the
  L2 code-fix queue (with RE-26/RE-42) for John's promotion call.
- **Upstream gate/dashboard batch (2026-08-17, run 42):** 13 new upstream issues
  filed 2026-08-16/17 (#27–#33, #36, #37, #49, #50 — John's v1.7.0 "gate
  instrumentation" milestone) are all in halt-listed modules (`gates.md` RE-26/27/28,
  `dashboard.md` RE-20/21/22). No new RE issue registered (redundant with the
  author's own line-numbered upstream reports). #36 ≡ RE-27 (conformance judgment
  half, by-design). #37 (conformance over-credits hook-path denies + double
  annotation) and #49 (hook clips rule directive to 80-char `firstLine()` display
  width) are NEW behavioral findings but core-internal / hook-path — no MCP/CLI
  surface, not E2E-verifiable. #27/#28/#29/#30 = `gateStats`/per-rule/read-dimension
  gaps (core-internal). #31/#32/#33 = dashboard epics. #50 = re-measure (depends on
  #49). No E2E action this run.
- **Upstream #19/#20 independent verification (2026-08-18, run 43):** the two
  concrete claims from upstream `team-monet/monet` #19 and #20 were verified
  against the readable source and registered as RE-45 (#19) and RE-46 (#20).
  **Verified against current readable source (line numbers are the CURRENT
  monorepo layout; the upstream issues cite pre-monorepo line numbers that have
  drifted):**
  - `busy_timeout = 5000` — `storage.ts:253` (`this.pragma("busy_timeout = 5000")`),
    with the #215 nuance at `storage.ts:226-230`: better-sqlite3 arms
    `sqlite3_busy_timeout` from its own `timeout` option at open (default 5000),
    and the explicit pragma runs AFTER the wait it looks like it governs.
  - **`memory_fetch` is a hidden writer** — `engine.ts:5054-5056`: `getConcept`
    runs `UPDATE concepts SET usefulness_score = usefulness_score + 1,
    usefulness_last_fetched_at = ? WHERE id = ?` UNPROTECTED (no SQLITE_BUSY
    catch, no transaction, fires before the read result is assembled); and
    `engine.ts:5057-5059`: `if (synthesizedNow) row = await this.synthesizeRow(row)`
    — a dirty concept is inline-synthesized on fetch. Either write failing under
    contention fails the ENTIRE fetch. (Upstream cited `engine.ts:3330-3334`,
    now `5054-5059`.)
  - **`checkpoint()` synthesizes every dirty concept in one loop** —
    `engine.ts:5106-5107`: `SELECT * FROM concepts WHERE dirty = 1 … .all(circle)`
    then `for (const r of rows) await this.synthesizeRow(r)` — no yield/batch/cap
    between iterations, so a large dirty debt (live store: 179) is a minutes-long
    write window at every session end. (Upstream cited `engine.ts:3368-3375`.)
  - **No `interrupt`/progress handler** — verified against the installed driver
    `better-sqlite3 11.10.0` (`packages/core/node_modules`): prototype methods are
    `constructor prepare transaction pragma backup serialize function aggregate
    table loadExtension exec close defaultSafeIntegers unsafeMode` — no `interrupt`,
    no progress handler. `busy_timeout` bounds waiting for a lock, not holding one.
  - **`inspectStoredEmbeddingRows` materializes full embeddings** —
    `embedding-state.ts:128`: `readLiveEmbeddingRows` returns
    `db.prepare(LIVE_EMBEDDING_SQL[population]).all()` over `SELECT id, embedding`
    (the FULL embedding JSON column, every live row), and `inspectStoredEmbeddingRows`
    (`:131`) folds the array in JS afterward — memory grows linearly with population
    size before the reduction. (The upstream issue named the function
    `inspectStoredEmbeddingRows`; in the current source the `.all()` lives one hop
    away in `readLiveEmbeddingRows`, which the inspector calls.)
  - **Deterministic contention probe (empirical, isolated):** a second
    better-sqlite3 connection writing while another holds `BEGIN IMMEDIATE` fails
    `SQLITE_BUSY` ("database is locked") after **~11.8 s** — not 5 s — because in
    WAL mode the open-time `timeout` default and the explicit `busy_timeout=5000`
    pragma stack. This confirms the contention mechanism is deterministic and
    reproducible, and pins the safe hold-time for a future test.
  - **#19 E2E-verifiability judgment:** REPRODUCIBLE as a deterministic
    scenario-9-extension XFAIL. Recipe: isolated store with a live concept → raw
    better-sqlite3 connection holds `BEGIN IMMEDIATE` (one tiny write) for ≥12 s →
    MCP `memory_fetch` on the concept → its usefulness-bump UPDATE blocks → the
    whole fetch fails `database is locked`. Desired contract to assert: *a fetch
    (read) must not fail on a telemetry write — the bump should be best-effort and
    the concept still returned.* **Flagged as E2E follow-up test35** (NOT
    implemented this run — verification-only scope, per DIRECTION). RE-45 status
    stays `open` (E2E-verifiable, not yet reproduced as an XFAIL).
  - **#20 status:** `source` (structural) — "no interrupt" is a driver-API
    property (not MCP/CLI-observable without a deliberately bad query) and the
    `.all()` materialization is a scalability observation, not a clean behavioral
    XFAIL. Routes to the code-fix queue, not the E2E verifier.
  - storage.ts was NOT re-documented (DIRECTION "검증만"); the verification detail
    lives here. GitHub issue #11 commented + closed.
