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
- **removed** — obsolete-by-removal: the subsystem that hosted the bug was
  retired in a Monet release, so the issue can no longer manifest (its XFAIL
  test now SKIPs on that version). Restore only if the subsystem revives.

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
| RE-05 | Source concepts skip nativeScoreFloor (any score>0 enters) while native concepts below floor are dropped — intentional? **[removed 2026-08-22: source subsystem hard-removed in 1.7.0 → cannot manifest; guardrail test26 SKIP]** | search-pipeline.md | removed | test26 (SKIP) | S4 |
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
| RE-23 | `monet start` derives a fallback identity (`local-agent` / `<basename>-<sha8>`) when MONET_CALLER_ID/MONET_PROJECT_ID are unset, so `source_list` silently returns `[]` and `source_status`/`source_path`/`source_sync` return the non-disclosing "source is unavailable" — the identity mismatch is NOT discoverable (a caller sees a clean "no sources" state) | sources-sync.md | removed | test26 (SKIP) | S3 |
| RE-24 | updateSource lets `access` be mutated, silently de-authorizing the host that registered/syncs the source | sources-sync.md | removed | test28 (SKIP) | S2 |
| RE-25 | MCP source_sync is synchronous/blocking (awaits full clone→chunk→hash→embed→publish→verify); can exceed MCP timeouts **[removed 2026-08-22: source subsystem hard-removed in 1.7.0 → tool no longer exists; guardrail test25 SKIP]** | sources-sync.md | removed | test25 (SKIP) | S4 |
| RE-26 | Gate instrumentation has NO retention/pruning: in ≤1.6.x `gate_events` grew unbounded (2–3 orders > `resolution_events`); 1.7.0 moved recording to the store-backed `governed_moments` table, which likewise has no auto-cap/prune surface — the unbounded-growth contract is unchanged | gates.md | confirmed | test29 | S2 |
| RE-27 | Conformance "cheap half" can only emit `changed` for blocking denies; advisory fires stay `unavailable` → advisory rules un-retirable until judgment half ships. **reassessment in progress (#25) w/ test50 E2E evidence (2026-08-22):** the judgment half SHIPPED in 1.7.0/1.7.1 as MCP `conformance_ask`/`conformance_answer` — it records a per-moment `followed`/`not-followed` verdict into `governed_moments` (tallied by `momentConformance`), but exposes NO rule-retirement / advisory-dismissal surface (the only conformance tools are ask+answer; both ATTACH a verdict, never retire a rule). So advisory rules still have no retirement path from this mechanism — unless retirement moves to a later layer (per the moment ledger the verdict is about the act, not the rule) | gates.md | by-design | — | S4 |
| RE-28 | gate_events.action_context stores raw intercepted commands verbatim (paths/hostnames/flags) — most privacy-sensitive column; local-only + scrub-covered | gates.md | by-design | — | S3 |
| RE-29 | `-d` isolates the SQLite DB but NOT source storage — `sourceStorageDir` hard-defaults to `~/.monet/sources` via `homedir()` with no `-d` scoping / CLI/env override; isolated-source work silently writes to prod | sources-sync.md | removed | test25 (SKIP) | S2 |
| RE-30 | repo-md `source_sync` fails `EACCES` on macOS — `sealSnapshot` chmods the tree `0o500` then `renameSync` into place; APFS refuses the in-place rename of a non-writable dir, so the stage-beside-variant mitigation (source-materializer.ts:2225) is insufficient on macOS 15.x | sources-sync.md | removed | test25 (SKIP) | S2 |
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
| RE-42 | `monet repair --target` accepts any unrecognized string as an exact model ID — `resolveTargetAlias` special-cases only onnx/hashing/blank/`dim:` and returns everything else verbatim, and no profile-registry check exists anywhere in the preflight→`migrateEmbeddings` path. A loadable-but-unregistered `owner/repo` id silently repins the store into an unmeasured space (`mean` pooling, legacy thresholds, fallback budgets) with the verified backup as the only mitigation; a typo surfaces as a download error misread as a network problem. The `readsOnlyLatinScript` one-way guard cannot fire for unregistered targets (field is profile-derived → `undefined`). Fix needs core to expose a "known profile" accessor (registry is module-private). **[FIXED in 1.7.1 upstream #77]** — preflight now rejects an unregistered `--target` with an explicit "names no embedding space this build describes… NOT a download or network condition" message + the accepted-space list, rc=1, pin preserved, no download attempted (regression guard test51, verified XPASS 2026-08-22) | repair-cli.md | fixed | test51 | S1 |
| RE-43 | `monet repair` self-deadlocks on every English-only target: `recheckNonEnglish` opens a second better-sqlite3 connection via `inspectStoredEmbedderState` while `applyRepair`'s port holds exclusive ownership (`createVerifiedBackup` retains it; `releaseExclusiveOwnership` is catch-only) → `SQLITE_BUSY` after the 5s busy_timeout. Deterministic, single-process. Only workaround `--accept-non-latin-loss` disables the very guard the recheck enforces. Fails closed (no rewrite, backup retained). **[FIXED in 1.7.1 upstream #14 (NOT in 1.7.0)]** — `recheckNonEnglish` now reads only the non-Latin COUNT through `inspectNonLatinContent(port)` (the already-owning port) instead of `dependencies.inspect` (a second better-sqlite3 handle that waited out the 5s busy timeout against its own process's EXCLUSIVE lock). E2E: test33 flips XFAIL→XPASS on installed 1.7.1 (2/2, `repair --target Xenova/bge-small-en-v1.5 --apply --yes` rc=0 + repin), still XFAIL on 1.7.0. L2 dequeue | repair-cli.md | fixed | test33 | S2 |
| RE-44 | `monet materialize` renders an unsynthesized (dirty) skeleton concept's concatenated body as governing text — `skeletonMemberRows` filters on status/verdict but has NO `dirty`/`needsSynthesis` guard, so an amended principle ships both old+new paragraphs and `mirrorStale` reports green (block hash matches the store). Silent wrong governing text on the always-on surface, recoverable via synthesize+rematerialize | materialize-cli.md | confirmed | test34 | S2 |
| RE-45 | `busy_timeout=5000` is starved by multi-minute concurrent write bursts (single WAL writer slot vs ~12 long-lived `monet start` processes); `memory_fetch` is a HIDDEN WRITER — `getConcept` runs an unprotected usefulness-bump UPDATE + may inline-synthesize a dirty concept, so a competing writer's burst makes even "reads" report `database is locked` (upstream #19) | storage.md | confirmed | test36 | S2 |
| RE-46 | Nothing bounds a statement: better-sqlite3 11.10.0 exposes no `interrupt`/progress handler, so one query can hold the write lock indefinitely (`busy_timeout` bounds *waiting*, not *holding*); `inspectStoredEmbeddingRows`/`readLiveEmbeddingRows` materializes every row's full embedding JSON via `.all()` before the fold (upstream #20) | storage.md | source | — | S2 |
| RE-47 | `correction-attach` exemption (resolution.ts:261-277) attaches a `kind="correction"` observation in the ambiguous band (`tauAmbiguous ≤ obsScore < tauAttach`) to the evidence-nominated concept on the "intent disambiguates" premise, then engine.ts:4810-4817 opens a value-conflict contradiction → the concept is `disputed`. But intent disambiguates WHAT a correction asserts, not WHICH concept a weak (sub-tauAttach, e.g. 0.60) evidence match points at — an unrelated correction is absorbed and marks an innocent concept contested (blast radius > a wrong observation). Reproduced: nearMatchScore 0.604 → `action: "ambiguous"` + `contradiction` open + attach. **[FIXED in 1.7.1 upstream #52/#76]** — the ambiguous-band correction now FORKS to its own concept (`conceptId` = new id, nearMatch reported but not absorbed), matched concept's observationCount unchanged, no contradiction/dispute (regression guard test53, verified XPASS 2026-08-22; test38 remains XFAIL for the sibling RE-48) | dedup-resolution.md | fixed | test53 | S2 |
| RE-48 | `memory_store` ack omits the attach target's title/slug/body — the MCP envelope (mcp-server.ts:969-990) returns only `conceptId`/`nearMatchId` (UUIDs) + `nearMatchScore`, dropping the `concept.slug`/`concept.title` the engine already computes (`r.concept` = toConcept(row), engine.ts:4875-4888/19120-19135) — so a mis-merge is invisible from the response alone (requires a separate `memory_fetch`). Compounds RE-47 | mcp-server.md | confirmed | test38 | S3 |
| RE-49 | `stage_lookup` clips `body`/`reason` and discards `clip()`'s `.clipped` flag — no `bodyTruncated`/`reasonTruncated` emitted, and the tool description's "omission recovery fields" covers omitted RULES only, so a clipped rule body has no disclosed recovery path (unlike `memory_fetch`, which emits `bodyTruncated` + instructs "recover from observations"); `conceptId` IS returned so the recovery path exists but is undisclosed | mcp-server.md | confirmed | test41 | S3 |
| RE-50 | Startup failure cannot say why it died: `await server.connect(transport)` (mcp-server.ts:3491) is the first moment anything can be said in MCP terms — `ensureEmbedderPin()` (3466, model load) and both entry points' store-open+model-load (`chooseStoreEmbedder`, mcp-cli.ts:38-51) all run before the protocol channel exists, so every cause reads as "Connection closed" (-32000); fixing it is a design decision (degraded mode vs out-of-band diagnosis), not a reorder — fail-closed is intended. **[FIXED in 1.7.1 upstream #12/#13/#79 via out-of-band diagnosis]** — a fatal store-open/model-load startup now writes `<db>.startup-failure.json` (v1: timestamp/pid/phase/error name+message+code+stack) and `monet doctor` reads + surfaces it ("startup: last recorded startup failure — … SQLITE_NOTADB …" with the sidecar path); fail-closed is preserved (start still dies); the DIAGNOSIS is now out-of-band (regression guard test52, verified XPASS 2026-08-22). L2 design-decision dequeue signaled | mcp-server.md | fixed | test52 | S2 |
| RE-51 | `memory_checkpoint` writes (workstream `saveWorkstream` / find `captureFind`) into an ARCHIVED circle with NO disclosure: both paths resolve the circle and write without consulting `isArchivedCircle` (the storeInternal disclosure from PR #78 / RE-17 is the only archived guard), and the receipt names the landing circle but carries no `guidance`/`archived` clause saying the row now sits OUTSIDE store-wide recall. The write is correct (archive hides recall, not writes) — the missing disclosure is the bug (upstream #81, sev:major). Confirmed 2026-08-23 on 1.7.1: archive circle → `memory_checkpoint`{workstream} → receipt `{circle, workstream:{id,title,opened,closed}}` with NO archived signal; DB workstream concept lands in the archived circle name. Desired contract (test54 XFAIL): refuse, or disclose the archived landing | checkpoint-circle.md | confirmed | test54 | S2 |
| RE-52 | `monet install` CRASHES (unhandled JS TypeError) instead of refusing cleanly on a malformed `hooks.PostToolUse`/`PostToolUseFailure` section: `validateSettingsShape` checks ONLY `hooks.PreToolUse` and returns `{ok:true}` early when it is absent, so the PostToolUse* values (now managed by the installer) skip shape-validation and reach `upsertHandlerForEvent`, whose `group.hooks.filter(...)` throws (upstream #70, sev:minor). Confirmed 2026-08-23 on 1.7.1 — a settings seed whose PostToolUse hooks is a non-array yields rc=1 `i.filter is not a function`; an empty-array hooks yields rc=1 `(t ?? []) is not iterable`. Desired contract (test55 XFAIL): refuse cleanly like the wrong-shape/malformed PreToolUse arms (test37 F/G), not an unhandled TypeError | cli.md | confirmed | test55 | S3 |
| RE-53 | A store that crosses the ambiguity gate (#86 third outcome, below `tauMargin`: nothing written, caller resolves with `attachTo`/`forceNew`) is counted by NO resolution event — the ask throws from inside the write transaction before `recordResolutionEvent` (deliberate, so nothing-written is structural, but the throw already rolled back so no row can be written there), and the retry records `direct-attach`/`force-new`, which `DECIDED_RESOLUTION_MODES` excludes (bulk/consolidation attachTo dilution rationale). Each exclusion is defensible alone; together they drop the whole exchange, so every rate dividing by `decidedTotal` (fork rate, duplicate-emission rate) is measured only over the stores the gate let through SILENTLY — a selection bias toward exactly the population the gate exists to shrink, growing as the gate does more work. Fix needs a schema change (ask: `resolution_events.observation_id` NOT NULL, throw already rolled back) and/or a caller-supplied retry signal (an attachTo answering its own question vs a caller who already knew the destination) — both wider than #87 (upstream #88, found by Codex review on #87, sev:minor). No MCP/CLI surface → structural | dedup-resolution.md | source | — | S3 |
| RE-54 | The 12 `packages/core/scripts/measure-*.ts` calibration scripts reimplement the decisions they justify instead of calling them — 0/12 call `scoreNativeConceptsByObservation`, 1/12 call `resolveIncoming`; each rebuilds scoring from better-sqlite3/embedding/lexical-overlap primitives. A reimplementation silently drifts toward making the constant look derived (nothing fails when harness and engine disagree). Codex review of #87 found 11 divergences across 4 rounds (skips the centroid confirmation the margin gate sits inside; maximises over PROBE segments where the store embeds content once; prices landings production refuses; drops `correction` and `rule`/`principle`/`preference` probes the gate governs; removes normative rows from EVIDENCE; counts retired concepts; loses pre-backfill observations; IDF over the full corpus incl. withheld-probe tokens; ranks rules as ordinary correction destinations; doesn't exclude `kind='workstream'`; probe-unit defect at measure-attach-thresholds.ts:87 → shipped `tauAttach` inherits it). STARTER_SUITE seeds 98 obs/98 segs (probe.vecs[0]==probe.whole) so the probe-unit divergence cannot appear — a gate that cannot exhibit the effect it certifies. Fix = a shared driver calling the engine's scorer+decision (`scoreNativeConceptsByObservation` & `resolveIncoming` are both module-safe), re-derive tauMargin/tauAttach/edgeSimMin/NATIVE_SCORE_FLOOR/LEXICAL_BOOST/reliableSegmentTokens per profile, recording whether each value moved (upstream #89, **ratified by John 2026-08-23**, sev:major). No MCP/CLI surface → structural | search-pipeline.md | source | — | S2 |

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
- **Upstream #81/#70 triage → RE-51 + RE-52 (2026-08-23, run 65 E2E):** the
  08-21 upstream issue batch (#66/#68/#70/#72/#75/#81/#82/#83) triaged against the
  INSTALLED 1.7.1 binary. Two behaviorally-verifiable confirmed as REs with XFAIL
  tests: **#81 → RE-51** (`memory_checkpoint` writes into an archived circle with
  NO disclosure, sev:major/S2, test54 — the checkpoint/save sibling of RE-17) and
  **#70 → RE-52** (`monet install` crashes with an unhandled TypeError on malformed
  `hooks.PostToolUse*` because `validateSettingsShape` only validates PreToolUse
  and early-returns `{ok:true}` when it is absent, sev:minor/S3, test55). The other
  six (#66/#68/#72/#75/#82/#83) are structural/gate-ledger issues with no clean
  MCP/CLI XFAIL surface → routed L2 (see `diary/2026-08-23.md`).
- **RE-worker run 66 (2026-08-23):** created the two module docs the ISSUES rows
  point at — `checkpoint-circle.md` (RE-51, wired from mcp-server.ts:1816-1853)
  and `cli.md` (RE-52, install-cli.ts:1019-1043 `validateSettingsShape`) — and
  promoted RE-51/RE-52 into the L2-code-fix-queue (active queue 12→14). This
  completes the RE-side bookkeeping for the 08-21 batch.
- **Upstream #88/#89 triage → RE-53 + RE-54 (2026-08-24, run 68):** both found by
  Codex review on the #87 tauMargin PR, both structural (no MCP/CLI surface →
  `source` status, L2-queue NOT XFAIL). **#88 → RE-53 (S3):** a store crossing the
  ambiguity gate (below `tauMargin`) is counted by no resolution event — the ask
  throws before `recordResolutionEvent` (transaction rolled back; `observation_id`
  NOT NULL) and the retry's `direct-attach`/`force-new` are excluded from
  `DECIDED_RESOLUTION_MODES`, so every rate ÷ `decidedTotal` (fork/duplicate-
  emission) is biased toward the population the gate shrinks. **#89 → RE-54 (S2,
  John-ratified 08-23):** the 12 `measure-*.ts` calibration scripts reimplement
  `scoreNativeConceptsByObservation`/`resolveIncoming` (0/12 + 1/12 call them)
  instead of driving them, so every constant they justify (`tauAttach`/`tauMargin`/
  `edgeSimMin`/`NATIVE_SCORE_FLOOR`/`LEXICAL_BOOST`/`reliableSegmentTokens`) drifts
  toward looking derived (11 Codex found divergences across 4 rounds, all inert by
  luck; STARTER_SUITE can't exhibit the probe-unit defect). Registered as `source`
  rows, module paragraphs added (`dedup-resolution.md` RE-53, `search-pipeline.md`
  RE-54), and both routed to the L2 structural section (queue 1→3 rows in that
  section). Test changes: none (structural). Closes monet-e2e#27.
- **E2E verification loop (2026-08-18, run 44):** RE-45 converted to XFAIL test36
  and CONFIRMED. **RE-45** (memory_fetch hidden writer, test36): a second
  connection (Python sqlite3, stdlib) holds `BEGIN IMMEDIATE` + one insert on the
  store's WAL file; `memory_fetch` on a live concept blocks on its unprotected
  usefulness-bump UPDATE for the stacked busy_timeout (~11.8 s in WAL: open-time
  `timeout` default + explicit `busy_timeout=5000` pragma) and then the whole
  fetch returns `fetch failed: database is locked` (a pure read fails on a
  telemetry write). Deterministic — 5 setup checks pass, fetch observed
  `elapsed≈12.6 s`. Desired contract asserted: the fetch must return the concept
  (bump best-effort). `open` → `confirmed`, `e2e_test` set (`—` → test36).
  GitHub issue #12 commented + closed. RE-45 joins the L2 code-fix queue.
- **Upstream #52 triage → RE-47 + RE-48 (2026-08-18, run 46):** verified upstream
  `team-monet/monet` #52 ("memory_store auto-merge attaches an observation to an
  unrelated concept at low similarity") against the readable source and converted
  to XFAIL test38. Two distinct findings, both E2E-observable and CONFIRMED:

  1. **RE-47 (S2) — the `correction-attach` misfile.** `resolveIncoming`
     (resolution.ts:261-277) exempts `kind="correction"` from the ambiguous-band
     fork: when `tauAmbiguous ≤ obsScore < tauAttach`, it returns mode
     `correction-attach` and attaches the observation to the evidence-nominated
     concept (the comment "intent disambiguates" justifies the exception). Then
     `storeInternal` (engine.ts:4810-4817) opens a value-conflict contradiction
     for any `kind="correction" && landedOnExisting`, flipping the concept to
     `disputed`. The premise is false for a weak match: intent disambiguates WHAT
     the correction asserts, not WHICH concept a 0.55–0.70 evidence cosine points
     at. Empirically reproduced (deterministic, bge-m3): a caching-related
     correction scored `nearMatchScore 0.604` (< tauAttach 0.70) → `action:
     "ambiguous"` + `contradiction {status:"open"}` + attach. A wrong correction
     has a larger blast radius than a wrong observation (marks healthy memory
     contested). Upstream #52's 0.556 is the same band. Fix is a product decision
     (fork instead of attach, or raise the correction floor — upstream "suggested
     directions" #2/#3), so the assertion test38 pins is the OBSERVABILITY contract
     (RE-48), which is unambiguously correct.

  2. **RE-48 (S3) — the ack hides the target.** The `memory_store` MCP envelope
     (mcp-server.ts:969-990) threads `circle`/`action`/`conceptId`/`nearMatchId`/
     `nearMatchScore`/`contradiction`/`resolutionMode` but DROPS the
     `concept.slug`/`concept.title` the engine already returns (`r.concept` =
     toConcept(row), engine.ts:4875-4888 → `toConcept` 19120-19135). A caller
     cannot tell from the response that a merge landed somewhere unrelated — the
     fix is trivial (thread slug/title into the envelope when the action landed on
     an existing concept; upstream "suggested direction" #1).

  test38 (XFAIL, deterministic): stores a base concept, then a near-identical
  correction (strong attach, `action: "attached"`) and the ambiguous-band
  correction (~0.60), asserting the DESIRED contract that an attach/ambiguous ack
  discloses a human-readable target (`title`/`slug`). Both attaches currently omit
  it → XFAIL; the ambiguous attach also records the RE-47 evidence
  (nearMatchScore + contradiction). GitHub issue #13 commented + closed.
- **Unreleased-source diff review (2026-08-19, run 47):** source clone
  `~/monet/monet` was 7 commits behind `origin/main`; two substantive code
  commits landed that were NOT in any released npm version (still 1.6.3):
  `81976e5` (#51) and `683d261` (#58), plus the conformance attribution rewrite
  (monet#37) folded into #51. **Upstream #49/#50** (hook clips rule directive to
  80-char) and **upstream #37** (conformance over-credits hook-path denies +
  double annotation) are FIXED in source; **upstream #28** (read dimension) is
  now SHIPPED with a new MCP surface (`memory_overview.gateStats.unreadStages`/
  `unreadStagesOmitted`). These three were previously halt-listed as
  "core-internal, no MCP/CLI surface" (run 42). **No RE issue status flipped** —
  the fixes are unreleased; re-verify at the next `@team-monet/monet` release
  (candidate 1.7.0). RE-26/27/28/48 are untouched by these commits. Detail in
  `diary/2026-08-19.md`.
- **Upstream #59 + #13 triage → RE-49 + RE-50 (2026-08-19, run 48):** both
  DIRECTION run #7 RE priorities verified against current `main` and registered.
  **#59 → RE-49 (S3, open):** `stage_lookup` clips `body`/`reason` and discards
  `clip()`'s `.clipped` flag — no `bodyTruncated`/`reasonTruncated` emitted, and
  the "omission recovery fields" description covers omitted RULES only; the
  `conceptId`→`memory_fetch` recovery path exists but is undisclosed. E2E-verifiable
  (MCP surface) → flagged as XFAIL test39 for the E2E worker. **#13 → RE-50 (S2,
  source):** `server.connect()` (mcp-server.ts:3491) is the first MCP-utterable
  moment; `ensureEmbedderPin()` + entry-point store-open/model-load all run before
  it, so every startup failure reads as "Connection closed" — a design decision
  (degraded mode vs out-of-band diagnosis), routes to the L2 design-decision queue.
  Line drift from the upstream citations noted (factory 3358-3414 → 3454-3510).
- **E2E verification loop (2026-08-19, run 50):** RE-49 converted to XFAIL
  **test41** and CONFIRMED. Both DIRECTION run #7 RE priorities were already
  triaged by run 48 (RE-49/RE-50); the one still-pending item was RE-49's
  XFAIL — neither RE run 48 nor the two E2E runs 48/49 had written it (run 48
  deferred XFAIL-writing to the E2E worker, run 49 re-queued it). test41 is
  deterministic: declares a stage + an advisory rule whose body is 8100 chars
  (> STAGE_LOOKUP_BODY_CAP=6000) → `stage_lookup` → the wire clip fires
  (`...[truncated ...]` marker present, bodyLen 6021) but the delivered rule
  carries keys `{body, conceptId, origin, reason, reasonMissing, scope,
  severity, text}` with NO `bodyTruncated`/`reasonTruncated` field → exit 2
  (XFAIL). `open` → `confirmed`, `e2e_test` `pending-XFAIL` → `test41`. Source
  cross-check vs `main` and the installed 1.6.3 binary both reproduce
  identically (mcp-server.ts:146-150 `clip()`, 1597-1625 handler uses only
  `.text` and discards `.clipped`). Detail in `diary/2026-08-19.md`.
- **Source subsystem hard-removal reclassification (2026-08-22, run 63):** run 60
  verified the open-source 1.7.0 release irreversibly removed the source
  subsystem — the CLI `source` command, the four `source_*` MCP tools
  (`source_list`/`source_status`/`source_path`/`source_sync`), and the dashboard
  `/api/sources` route are all gone (MCP 23→21, −4 source_* / +2
  `conformance_ask·answer`), and the schema bump 12→13 retired the source-backed
  tables. Per the `removed` status (obsolete-by-removal; XFAIL now SKIPs), this
  run reclassified the two remaining non-`removed` source-subsystem issues:
  **RE-05** (`open` → `removed`, guardrail test26 SKIP) and **RE-25** (`by-design`
  → `removed`, guardrail test25 SKIP). The three source E2E tests
  (test25/26/28) stay as regression guardrails (supervisor deliberately kept them
  SKIP, NOT XFAIL). This completes the post-1.7.0 source cleanup: RE-05/23/24/25/
  29/30 are now all `removed`, and no source-subsystem issue remains active in the
  registry. **RE-27** (conformance judgment half) is separately resolved
  (by-design, reassessed in run 62 with test50 E2E evidence) — it is a gates.md
  issue, not a source-subsystem one, so it is untouched here. Detail in
  `diary/2026-08-22.md`.
- **1.7.1 fixed-RE re-verification (2026-08-22, run 64):** completed the 1.7.1 re-verify
  (DIRECTION #1). Three of the four 1.7.1-fixed issues from the release were
  independently verified against the INSTALLED 1.7.1 binary and converted to
  committed XPASS regression guards (RE-43/test33 already flipped in run 62):
  - **RE-42** (`source` → `fixed`, **test51** XPASS) — `monet repair --target
    Xenova/fake-unregistered-model --apply --yes` now rejects in preflight rc=1
    with "names no embedding space this build describes … NOT a download or
    network condition" + the accepted-space list; pin preserved, no download.
  - **RE-50** (`source` → `fixed`, **test52** XPASS) — a corrupt store's startup
    fails closed (rc≠0) but writes `<db>.startup-failure.json` (v1: timestamp/pid/
    phase/error name+message+code+stack) and `monet doctor` reads + surfaces it
    ("startup: last recorded startup failure — … SQLITE_NOTADB"), so the cause is
    now out-of-band readable. L2 design-decision dequeue signaled.
  - **RE-47** (`confirmed` → `fixed`, **test53** XPASS) — the ambiguous-band
    correction now FORKS to its own concept (`conceptId` = new id), matched
    concept's observationCount unchanged, no contradiction/dispute. test38
    stays XFAIL because the sibling **RE-48** (ack omits target title/slug) is
    NOT addressed by 1.7.1 — RE-48 remains `confirmed`, and DIRECTION's
    "RE-48 separate confirm" is now a negative (still present).
  All 3 new guard tests green on installed 1.7.1. Detail in
  `diary/2026-08-22.md`.
