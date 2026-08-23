# Monet Reverse-Engineering — Dedup Resolution Pipeline & Similarity Thresholds

> Status: **LOCATED & DOCUMENTED** (2026-08-10, run 5). Source: `@team-monet/monet` v1.5.2
> (`dist/index.js`, minified esbuild bundle; identical core duplicated inside `dist/cli.js`).
> This answers the priority-1 question from the 2026-08-10 E2E runs: where the aggressive
> dedup threshold is defined.

## TL;DR

Dedup ("attach vs create") is decided by **two per-model similarity thresholds**,
`tauAttach` and `tauAmbiguous`, applied to cosine similarity (dot product of
L2-normalized embeddings) between the new observation and candidate concepts.

- `tauAttach` = similarity at/above which an observation **attaches** to an
  existing concept (dedup/merge).
- `tauAmbiguous` = lower band where the store **refuses to attach** and instead
  flags an ambiguous fork / near-match (a safety band).

Both are **hardcoded per embedder model** in the source config map `pU`
(`XH` inside the cli.js bundle). There is **no CLI flag and no env var** to
override them in the shipped binary — only a programmatic constructor option.

## Where the thresholds live (exact locations)

### 1. Per-model config map `pU` (`dist/index.js`)

```js
var Sd = { tauAttach: .72, tauAmbiguous: .5 };           // default thresholds
var uU = "Xenova/bge-m3:cls:q8";                          // default (fresh-store pin)
var pU = {
  "Xenova/paraphrase-multilingual-MiniLM-L12-v2": { thresholds: { tauAttach: .7, tauAmbiguous: .5 } },
  "Xenova/all-MiniLM-L6-v2":               { thresholds: Sd, readsOnlyLatinScript: !0 },
  "Xenova/bge-small-en-v1.5":              { thresholds: { tauAttach: .78, tauAmbiguous: .5, edgeSimMin: .7 }, readsOnlyLatinScript: !0, reliableSegmentTokens: 380, nativeScoreFloor: .35 },
  "Xenova/bge-m3":                         { dim: 1024, pooling: "mean", thresholds: Sd },
  "Xenova/bge-m3:cls:q8":                  { checkpoint: "Xenova/bge-m3", dim: 1024, pooling: "cls", dtype: "q8",
                                             reliableSegmentTokens: 768, thresholds: { tauAttach: .7, tauAmbiguous: .5, edgeSimMin: .6 },
                                             nativeScoreFloor: .4 },
};
```

The ONNX provider class `km` reads `pU[this.model]` and sets
`this.recommendedThresholds = t?.thresholds ?? Sd`. If the caller overrides
`pooling`/`dtype` away from the known config (custom variant), thresholds fall
back to `Sd` (`.72/.5`).

The hashing provider class `ra` hardcodes
`recommendedThresholds = { tauAttach: .55, tauAmbiguous: .4 }`.

### 2. `MonetStore.applyEmbedderDerivedThresholds(embedder)` (constructor + pin change)

```js
this.tauAttach    = explicitThresholdOpts.tauAttach    ?? e.recommendedThresholds?.tauAttach    ?? .55;
this.tauAmbiguous = explicitThresholdOpts.tauAmbiguous ?? e.recommendedThresholds?.tauAmbiguous ?? .4;
let strong = (e.recommendedThresholds?.tauAttach ?? 0) >= .7;
this.edgeSimMin  = explicitThresholdOpts.edgeSimMin   ?? e.recommendedThresholds?.edgeSimMin   ?? (strong ? .45 : .4);
```

`explicitThresholdOpts` is captured in the constructor:
`{ tauAttach: t.tauAttach, tauAmbiguous: t.tauAmbiguous, edgeSimMin: t.edgeSimMin }`.

**Override surface (verified):** the CLI `start` path constructs the store via
`pO(storageDir, { scopeContext, defaultCircle, gateSidecarPath })` — no threshold
options. `grep process.env` shows no `MONET_TAU*`/threshold env var. → In the
shipped product the thresholds are effectively **hardcoded per model**; tuning
requires code change or embedding the package as a library.

### 3. The decision function `V1` (store resolution)

```js
function V1({ nomination, centroidTop, kind, thresholds }) {
  let { tauAttach, tauAmbiguous } = thresholds;
  if (nomination === null) return sT(e, 0);
  let { conceptId, obsScore, centroidScore } = nomination;
  return obsScore >= tauAttach
    ? (centroidScore >= tauAmbiguous
        ? { action: "attached",   mode: "attach",          attachToConceptId: conceptId, score: obsScore }
        : { action: "ambiguous",  mode: "fork-signal",     duplicateEdge: { conceptId, weight: obsScore },
            nearMatchId: conceptId, nearMatchScore: obsScore, score: obsScore })
    : obsScore >= tauAmbiguous
      ? (kind === "correction"
          ? { action: "ambiguous", mode: "correction-attach", attachToConceptId: conceptId,
              nearMatchId: conceptId, nearMatchScore: obsScore, score: obsScore }
          : { action: "ambiguous", mode: "ambiguous-fork",  duplicateEdge: { conceptId, weight: obsScore },
              nearMatchId: conceptId, nearMatchScore: obsScore, score: obsScore })
      : sT(e, obsScore);
}
function sT(e, score) {   // fallback when no nomination / score below ambiguous band
  let { centroidTop, thresholds } = e;
  return centroidTop && centroidTop.centroidScore >= thresholds.tauAttach
    ? { action: "ambiguous", mode: "blur-duplicate", duplicateEdge: { conceptId: centroidTop.conceptId, weight: centroidTop.centroidScore },
        nearMatchId: centroidTop.conceptId, nearMatchScore: centroidTop.centroidScore, score }
    : { action: "created", mode: "new", score };
}
```

Decision table (V1):

| obsScore vs tauAttach | centroidScore vs tauAmbiguous | action / mode | outcome |
|---|---|---|---|
| ≥ tauAttach | ≥ tauAmbiguous | `attached` / `attach` | **dedup merge** into concept |
| ≥ tauAttach | < tauAmbiguous | `ambiguous` / `fork-signal` | NOT attached; duplicate edge + nearMatch |
| [tauAmbiguous, tauAttach) | (kind=correction) | `ambiguous` / `correction-attach` | attaches (correction challenge) |
| [tauAmbiguous, tauAttach) | (kind≠correction) | `ambiguous` / `ambiguous-fork` | NOT attached; duplicate edge + nearMatch |
| < tauAmbiguous | centroidTop ≥ tauAttach | `ambiguous` / `blur-duplicate` | NOT attached; duplicate edge to centroid top |
| < tauAmbiguous | centroidTop < tauAttach | `created` / `new` | **new concept** |

## Scoring pipeline (how obsScore / centroidScore are computed)

Store path (`storeInternal`):
1. embed content → `checkedEmbed` → vector `a`
2. `resolutionCandidates(circle)` — SQL:
   `SELECT * FROM concepts WHERE circle=? AND kind NOT IN ('workstream','source') AND source_identity IS NULL AND active_observation_id IS NULL AND status != 'retired'`
3. `D = rankByCentroid(candidates, a, wi)` — cosine to **concept centroid** embeddings
   (`yn(a, tt(concept.embedding))`, dot product; vectors are L2-normalized by `tg`);
   filter score > 0, sort desc, take `wi` (**wi = 6**)
4. `O = nominateByObservation(candidates, a, content)` — per-concept **observation-level**
   best score via `oT` (SQL over `observation_segments` UNION `observations` without
   segments; max cosine per concept); for embedders with `needsLexicalArm` (all ONNX),
   `q1` boosts the candidate **rank** by lexical token overlap:
   `rank = score * (1 + 1.0 * p)` where `p = F1(n, tokens, idf)` with
   `idf = max(0, log(n/(1+df)))` (`z1`), and `W1 = .12` is the default floor constant
   (`Z1` clamps `nativeScoreFloor`).
   → **nuance:** the lexical arm changes which concept is *nominated* (rank), but V1
     thresholds compare the **raw cosine** `obsScore`, not the boosted rank.
5. `V1({nomination: O, centroidTop: D[0], kind, thresholds})` → action.

Related-graph thresholds (same source constants):
- `edgeSimMin` gates `related` edges: edge added when `edgeSimMin <= score < tauAttach`
  (score ≥ tauAttach would be a duplicate, not "related").
- `batchDedup` adds `possible_duplicate_of` edges when score **≥ tauAmbiguous**.
- `memory_reassign_circle` merges into a target concept when `score >= tauAttach`
  (otherwise moves); flags `possible_duplicate_of` when `score >= tauAmbiguous`.
- Search-side floor: `nativeScoreFloor` (`Z1`, default `.12`; bge-m3: `.4`) filters
  native concept search results below the floor (`score < floor → dropped`).

## Explains the 2026-08-10 E2E observations

- **20 template sentences, only noun differs → merged 1-per-writer:** the isolated
  server pins the fresh-store default `Xenova/bge-m3:cls:q8` (tauAttach = **0.70**).
  bge-m3 cosine between sentences differing by a single noun is ≫ 0.70 → attach.
- **20 hand-written distinct sentences → 20 concepts:** pairwise similarity < 0.70 → created.
- **`needsSynthesis` by the 2nd attach:** unrelated to thresholds — synthesis flag is
  eager (see diary run 4, Finding 5).

## Issues found

- **RE-01 (documentation/operability gap):** dedup thresholds are invisible to users —
  no CLI flag, no env var, not in README. "Similar things merge" is by design
  (tauAttach 0.70 for the current pin) but cannot be tuned without patching source.
  Product review candidate: document per-model thresholds and/or expose override
  (env or `monet config`).
- **RE-02 (design nuance, not a bug):** attach requires BOTH obsScore ≥ tauAttach AND
  centroidScore ≥ tauAmbiguous. A concept whose centroid has drifted from its own
  observations (many heterogeneous attaches) can repel valid attaches into
  `fork-signal` — dedup depends on centroid freshness, not just observation similarity.
- **RE-03 (maintainability note):** the core logic is fully duplicated between
  `dist/index.js` and the `dist/cli.js` bundle (`xH`/`IN`/`oi` vs `V1`/`sT`/`gN`).
  Any source patch must touch both; keep them in sync when diffing versions.
- **RE-53 (structural, upstream #88, 2026-08-24): ambiguity-gate stores are counted
  by no resolution event.** #86 added a third attach outcome — below `tauMargin`
  the store writes nothing and returns candidates for the caller to resolve with
  `attachTo`/`forceNew`. Neither half of that exchange reaches `decidedTotal`: (a)
  the ask itself throws from inside the write transaction before
  `recordResolutionEvent`, deliberately, because that is what makes nothing-written
  structural rather than a rule the next edit must remember — but the throw already
  rolls the transaction back, so no row can exist there; (b) the retry records
  `direct-attach`/`force-new`, and `DECIDED_RESOLUTION_MODES` excludes both, for an
  older-and-still-valid reason (bulk import/consolidation sessions are mostly
  explicit `attachTo`, and counting those would dilute the fork rate toward zero
  with writes that were never allowed to fork). Each exclusion is defensible alone;
  together they drop the whole exchange, so every rate that divides by
  `decidedTotal` — fork rate, duplicate-emission rate — is measured only over the
  stores the gate let through silently: a selection bias toward exactly the
  population the gate exists to shrink, growing as the gate does more work.
  `resolution.ts`'s `DECIDED_RESOLUTION_MODES` note records the gap in place
  (`decidedTotal` means decisions-the-substrate-made-alone, not stores), so the
  number is not read as complete meanwhile. Fix is wider than #87 (schema change
  for the ask's observation-less row + caller-supplied retry signal), so routed L2.
  Found by Codex review on #87. No MCP/CLI surface → `source` status.

## Cross-check against readable TS (2026-08-16, run 34)

Validated against `packages/core/src/resolution.ts` + `embedding-onnx.ts` +
`engine.ts` (commit 83e9d7d, core 0.9.0). **No drift — decision logic, the model
profile table, the default, and the threshold-derivation function all match.**

- `resolveIncoming` (resolution.ts:230) ≡ minified `V1`; `createOrPair`
  (resolution.ts:324) ≡ `sT`. Same five-mode band mapping and same
  `ResolutionMode` vocabulary (the doc's table is exact, including the
  `species-fork`/`stage-fork` engine-only overrides).
- `MODEL_PROFILES` (embedding-onnx.ts:227–548) ≡ minified `pU`, value-for-value:
  multilingual-MiniLM `.70/.5`; all-MiniLM-L6-v2 legacy `.72/.5` + Latin-only;
  bge-small-en-v1.5 `.78/.5` + edgeSimMin `.70` + `reliableSegmentTokens 380` +
  `nativeScoreFloor .35`; bge-m3 (mean) dim 1024 legacy `.72/.5`; bge-m3:cls:q8
  `.70/.5` + edgeSimMin `.60` + `reliableSegmentTokens 768` + `nativeScoreFloor .40`.
- `DEFAULT_MODEL = "Xenova/bge-m3:cls:q8"` (embedding-onnx.ts:225) ≡ minified `uU`.
- `applyEmbedderDerivedThresholds` (engine.ts:10311–10323) is **exact**: `.55`/
  `.4` fallbacks and `semantic ? 0.45 : 0.4` for `edgeSimMin`.
- Naming refinement only: minified `Sd = {.72,.5}` is now
  `LEGACY_UNMEASURED_THRESHOLDS` (embedding-onnx.ts:198) with an explicit
  "known guess, not evidence — kept so an unmeasured model still runs" label.
  Value unchanged; the label is the point.
- **RE-01 confirmed** (no CLI/env override): thresholds still only reachable via
  the constructor `tauAttach`/`tauAmbiguous`/`edgeSimMin` opts
  (engine.ts:2611, `explicitThresholdOpts`); no env/CLI path added.

## Next candidates

1. Full search pipeline (memory_search): score fusion order, limit/truncation,
   `nativeScoreFloor` + lexical arm interaction, circle scoping SQL.
2. Schema migration 4→12: migration table + sentinel logic (partial: repair docs exist).
3. Circle routing / `resolveCircleName`, aliases, global-breadth marker `*`.
4. Contradiction processing: flagContradiction triggers, mediation states.
