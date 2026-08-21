# Monet Reverse-Engineering — Memory Search Pipeline (`memory_search`)

> Status: **DOCUMENTED** (2026-08-11, run 7). Source: `@team-monet/monet` v1.5.2
> (`dist/index.js`, minified esbuild bundle; core duplicated in `dist/cli.js`).
> Continues run 5 (`dedup-resolution.md` — write-side thresholds). This doc covers
> the read side: `MonetStore.search()` + the `memory_search` tool handler.

## TL;DR

`memory_search(query, circle?, limit?)` is a **two-arm, unified native+source**
retrieval:

1. Embed the query (`checkedEmbed(query, "native")`).
2. Brute-force cosine over every eligible concept's observation segments in
   scope (plus authorized source projections).
3. Per concept keep the **best matching observation** (raw cosine = `score`).
4. For ONNX embedders, a **lexical arm** re-ranks: `rank = score * (1 + 1.0 * p)`
   where `p` = idf-weighted query-token overlap fraction. **Latin-script only.**
5. Drop native concepts below `nativeScoreFloor` (`.40` for bge-m3:cls:q8,
   default `.12`), sort by `rank` desc, tie-break default-circle-first then id,
   `slice(limit ?? 5)`.
6. Map to pointer cards; the tool handler adds `observationCount`, contradiction
   count (if > 0), and truncates the JSON payload to the host tool-result limit
   (40 000 chars) with a `resultsTruncated`/`resultsOmitted` flag.

## Entry point

Tool handler (offset ~1011987 in `dist/index.js`):

```js
e.tool("memory_search", "Find memories by similarity. Returns ranked pointer cards...",
  { query: U.string(), circle: U.string().max(nt).optional(), limit: U.number().int().positive().optional() },
  async ({ query: E, circle: b, limit: y }, t) => {
    ...
    let w = await t.search(E, { circle: b !== void 0 ? d(b) : void 0,
                                limit: y, sourceAuthorizationContext: n });
    ...
    let I = w.map(R => EF(R, t.countObservationsForConcept(R.id)));
    return f(bF((R,k)=>({ circle: S, results: R,
                          ...k>0?{resultsTruncated:!0, resultsOmitted:k}:{},
                          ...I.length===0?{note:pF}:{} }), I), "memory_search", v);
  });
```

- `nt = 256` — max circle-name length in the schema.
- `EF(card, n)` → `{id, slug, kind, circle, observationCount: n, ...(contradictions>0 ? {contradictions} : {})}`.
- `pF = "Nothing matched."` — empty-result note.
- `Ar = 4e4` — `bF`/`Wm` fit the serialized response into 40 000 JSON chars;
  on overflow it keeps the largest prefix and reports `resultsTruncated: true,
  resultsOmitted: k` (a fixed note `Ws` explains the cut).
- Note: `limit`-based truncation (`.slice(0, limit)`) is **silent** — no
  truncation flag; only the size-based truncation is reported.

## Store `search()` — full flow (offset ~730520)

```js
async search(e, t = {}) {
  this.assertPinSatisfied();
  await this.assertWithinEmbedderWindow(e, "query");
  let r = t.limit ?? 5;                          // default limit = 5
  this.assertEmbedderReadsScript(e, "query");    // Latin-only models reject non-Latin queries
  let i = await this.checkedEmbed(e, "native");
  return this.db.transaction(() => {
    this.assertReadSpaceSatisfied(i.length);
    let n = t.circle !== void 0 ? this.resolveCircle(t.circle) : void 0;
    let o = candidateRows(n, t.includeArchived); // SQL below
    let s = o.concat(this.authorizedSourceProjections(t.sourceAuthorizationContext, n, t.includeArchived).map(p => p.row));
    let a = this.openContradictionCountsGlobal(n);       // open-contradiction count per concept
    let c = this.defaultCircle;
    let d = this.scoreSourceConcepts(s, i);              // B1: max chunk/concept cosine for source concepts
    let l = this.scoreNativeConcepts(o.map(p => p.id), i, e); // oT: per-concept best observation cosine + lexical rank
    let u = Z1(this.embedder.nativeScoreFloor);          // floor clamp (W1=.12 fallback)
    return s.map(p => {
      if (p.kind === "source")
        return { row: p, score: d.get(p.id), rank: d.get(p.id), matchedObservationId: void 0 };
      let h = l.get(p.id);
      return h === void 0 || h.score < u ? null : { row: p, score: h.score, rank: h.rank, matchedObservationId: h.observationId };
    })
    .filter(p => p !== null)
    .sort((p, h) => {
      let m = h.rank - p.rank;
      if (Math.abs(m) > 1e-9) return m;
      if (n === void 0) {                        // store-wide: default circle wins ties
        let f = p.row.circle === c ? 0 : 1, g = h.row.circle === c ? 0 : 1;
        if (f !== g) return f - g;
      }
      return p.row.id < h.row.id ? -1 : 1;
    })
    .slice(0, r)
    .map(({row: p, score: h, matchedObservationId: m}) => iF(p, h, a.get(p.id) ?? 0, m));
  })();
}
```

### Candidate-row SQL (circle scoping + archived-circle hiding)

```sql
-- circle given (after resolveCircle alias redirect):
SELECT * FROM concepts
WHERE circle = ? AND kind NOT IN ('workstream','source')
  AND source_identity IS NULL AND active_observation_id IS NULL AND status != 'retired'

-- no circle, includeArchived=true:
SELECT * FROM concepts
WHERE kind NOT IN ('workstream','source') AND source_identity IS NULL
  AND active_observation_id IS NULL AND status != 'retired'

-- no circle, default (archived circles hidden):
SELECT c.* FROM concepts c
  LEFT JOIN circle_aliases ca ON ca.from_name = c.circle AND ca.status = 'archived'
 WHERE c.kind NOT IN ('workstream','source') AND c.source_identity IS NULL
   AND c.active_observation_id IS NULL AND c.status != 'retired'
   AND ca.from_name IS NULL
```

- `resolveCircle(name)`: `SELECT to_name FROM circle_aliases WHERE from_name = ? AND status = 'active'` — single-level alias redirect; unknown/alias-less names pass through unchanged.
- A `circle_aliases` row with `status='archived'` marks an entire circle archived → hidden from store-wide search unless `includeArchived`.
- Search covers **all** eligible concepts in scope — full scan, no ANN index.

### Native scorer `oT` (scoreNativeConcepts, offset 578189)

```js
SELECT o.concept_id, o.id AS observation_id, s.embedding AS embedding
  FROM observation_segments s JOIN observations o ON o.id = s.observation_id
 WHERE o.superseded_by IS NULL AND o.superseded_at IS NULL AND o.kind != 'source'
   AND o.concept_id IN (SELECT value FROM json_each(?))
UNION ALL
SELECT o.concept_id, o.id AS observation_id, o.embedding AS embedding
  FROM observations o
 WHERE o.superseded_by IS NULL AND o.superseded_at IS NULL AND o.kind != 'source'
   AND o.concept_id IN (SELECT value FROM json_each(?))
   AND NOT EXISTS (SELECT 1 FROM observation_segments s2 WHERE s2.observation_id = o.id)
```

Per row: `c = tt(embedding)` (JSON→Float32Array), skip if all-zero (`KS`),
`d = yn(queryVec, c)` — **plain dot product**; since embeddings are
L2-normalized (normalize `tg` used throughout; see run 5), dot = cosine.
Skip `d <= 0`. Per concept keep max `d`; tie → smallest `observation_id`.
Result: `Map<conceptId, {score, rank: score, observationId}>`.

**Semantics:** the concept's score is the cosine of its **single best
observation/segment** — NOT the concept centroid (centroids are used only on
the write side). A concept with one great match ranks by that match.

### Lexical arm `q1` (offset 579474, ONNX embedders only)

- Query tokens: `Im(query)` = `new Set(query.toLowerCase().match(/[a-z0-9][a-z0-9_-]{2,}/gu) ?? [])`.
  - **Latin-script only**: token must start `[a-z0-9]` and be ≥3 chars. Korean
    queries → empty set → `if (n.size === 0) return` → **no lexical boost**.
    Verified: `주식 스톡 트래커` → `[]`, `stock tracker portfolio` → 3 tokens.
  - (`nT` hashing-provider tokenizers offer a unicode mode `2` with
    `[\p{L}\p{N}\s]`, but the ONNX search path uses `Im` only.)
- SQL: observations' tokens in query token set, joined per concept.
- Per token: `idf = z1(N, df) = max(0, log(N / (1 + df)))` where N = concept
  count, df = #concepts containing the token.
- Per observation: `p = F1(queryTokens, obsTokens, idf)` =
  `Σ idf(t) over matched query tokens / Σ idf(t) over all query tokens` —
  an idf-weighted query-coverage fraction in [0,1].
- Per concept: max `p` over its observations → **rank = `j1(score, p)` =
  `score * (1 + H1 * p)`**, `H1 = 1`. Raw `score` unchanged.
- Consequence: ordering uses the boosted rank, filtering uses raw `score`.
  A low-cosine but high token-overlap concept can outrank a higher-cosine one.

### Source scorer `B1` (offset 580347)

For authorized source projections only: max cosine over **active** `source_chunks`
embeddings, then also cosine vs the concept's own embedding; take the max.
Source rows are returned **unfiltered by floor** (no `nativeScoreFloor` check)
and their rank = raw score (no lexical boost).

### Result card `iF` (offset 988964)

```js
{ id, slug, kind, supportCount: e.support_count, contradictions: r,   // open count
  confidence: e.confidence, score: t, fetchHint: nF(e.kind), circle: e.circle,
  ...(i !== void 0 ? { matchedObservationId: i } : {}) }
```

`nF(kind)` gives a kind-specific fetch hint ("fetch for the decision, the why,
and the alternatives", etc.).

## Verified constants

| Symbol | Value | Role |
|--------|-------|------|
| default `limit` | 5 | `t.limit ?? 5` |
| `W1` | .12 | fallback nativeScoreFloor |
| `Z1` | clamp | `[0,1)` valid → value, else `W1` |
| `nativeScoreFloor` (bge-m3:cls:q8) | .40 | native results below → dropped |
| `H1` | 1.0 | lexical rank boost `score*(1+H1*p)` |
| `Ar` | 40 000 | response JSON size cap (chars) |
| `nt` | 256 | max circle-name length |
| `pF` | "Nothing matched." | empty-note |
| tokenizer | `/[a-z0-9][a-z0-9_-]{2,}/gu` | lexical arm (Latin only) |

## Explains the observed behavior

- **Korean search works** (E2E test03): semantic arm only — bge-m3 multilingual
  embeddings + cosine, floor .40. The lexical arm contributes nothing for
  Hangul (token set empty). Retrieval quality for Korean is entirely embedding
  quality.
- **English exact-token recall is boosted**: `rank = score*(1+p)` can surface
  token-heavy concepts above higher-cosine ones — expected, since the floor
  filter is on raw cosine.
- **Circle-isolation tests (test05)**: scoped search filters by resolved circle;
  store-wide search excludes archived circles and prefers the default circle on
  ties — consistent with the E2E harness needing token-scoped queries.

## Issues found (new this run)

- **RE-04 (asymmetry/product note):** the lexical rank arm is Latin-script-only
  (`/[a-z0-9][a-z0-9_-]{2,}/`). Multilingual models (bge-m3, multilingual
  MiniLM) pass the Latin-script guard for storage/search but their search
  ordering gets zero lexical contribution for non-Latin queries. English
  benefits from both arms; Korean/Japanese rely purely on embeddings. **E2E-CONFIRMED (2026-08-15, test30):** Korean content stores ZERO `observation_tokens` rows (the Latin-only `lexicalTokens` drops Hangul at write time) vs 10 tokens for the English equivalent; Korean SEMANTIC retrieval still works (bge-m3), so the gap is purely lexical. XFAIL.
- **RE-05 (design nuance, REMOVED 2026-08-22):** source concepts skip `nativeScoreFloor` — a source
  projection with tiny cosine (any score > 0) still enters results while a
  native concept below floor is dropped. Obsolete-by-removal: the source
  subsystem was hard-removed in 1.7.0, so this contrast can no longer
  manifest. Guardrail test26 SKIPs on 1.7.0+.
- **RE-06 (performance note):** search is an O(eligible segments) brute-force
  scan per query — every segment embedding in scope is deserialized and dotted
  with the query (no ANN index, no pre-filter beyond SQL kind/status/circle).
  Fine for local-first scale; the scan cost grows linearly with store size.
- **RE-07 (UX nit):** `limit` truncation is silent — no flag tells the caller
  more matches existed; only JSON-size truncation is reported.

## Cross-check against readable TS (2026-08-16, run 34)

Validated against `packages/core/src/retrieval.ts` + `lexical-overlap.ts`
(commit 83e9d7d, core 0.9.0). **No drift — every constant and the SQL match the
readable source.** The readable source only adds rationale the doc didn't have.

- `TOKEN = /[a-z0-9][a-z0-9_-]{2,}/gu` (lexical-overlap.ts:39) = the doc's tokenizer.
  **RE-04 (Latin-only) confirmed at source** — no change.
- `tokenIdf = max(0, log(N/(1+df)))` (lexical-overlap.ts:60) = `z1`; the
  `max(0, …)` clamp is the Codex-P2 / PR #156 fix the doc already showed.
- `LEXICAL_BOOST = 1.0`, `blendLexical = score*(1+1.0*overlap)`
  (lexical-overlap.ts:115–119) = `H1 = 1.0`.
- `NATIVE_SCORE_FLOOR = 0.12` (retrieval.ts:70) = `W1` fallback;
  `nativeScoreFloorOf(declared)` honours a provider value in `[0,1)` else 0.12
  (retrieval.ts:84–88) = `Z1` clamp.
- Per-model floors: bge-m3:cls:q8 `nativeScoreFloor: 0.40`
  (embedding-onnx.ts:547); bge-small `0.35` (embedding-onnx.ts:344) — both match.
- Native scorer SQL (`observation_segments UNION ALL observations-without-segments`)
  is byte-equivalent to `scoreNativeConceptsByObservation` (retrieval.ts:192–230).
- Lexical overlap is "per observation, max over concept" and DF is counted over
  concepts — both confirmed (retrieval.ts:284–307; lexical-overlap.ts:63–94).
- Source scorer `max(whole-file cosine, best active-chunk cosine)` confirmed
  (retrieval.ts:354–384), including the "whole-file is an UNCONDITIONAL candidate
  in the max" review fix the doc's summary did not call out.

Not re-verified here (MCP handler layer, `dist/cli.js`): `limit` default 5,
`nt=256`, `Ar=4e4`, the `resultsTruncated`/`resultsOmitted` shape. These live in
the MCP tool handler / CLI bundle, not in `retrieval.ts`; unchanged in every
version-bump diff to date and left as-is.

## Next candidates

1. Schema migration 4→12 (migration table + sentinel) — partial.
2. Circle routing/aliases lifecycle (how `circle_aliases` rows are created,
   archived; `resolveCircle` breadth marker `*`).
3. Contradiction processing (`flagContradiction` triggers, mediation states,
   `openContradictionCountsGlobal` usage in overview).
4. Dashboard (`dist/dashboard/*`).
