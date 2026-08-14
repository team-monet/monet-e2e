# Living-Model Ranking — temporal layer + V-A (valence–arousal) weighting

> Reverse-engineering run 27 (2026-08-14). Source: readable TS
> `@team-monet/core` (`src/engine.ts`, `src/embed-budget.ts`,
> `src/lexical-overlap.ts`, `src/spans.ts`, `src/synthesis.ts`) + the unit-test
> contract (`temporal.test.ts`, `usefulness-decay.test.ts`, `arousal.test.ts`,
> `stats-ranking.test.ts`, `va-ranking-probe.test.ts`).
>
> This is the "what still matters" core: how Monet orders the compact
> **living model** (`overview().livingModel`) that surfaces the handful of
> concepts an agent should actually re-read. It is a **multiplicative blend of
> four independent signals**, each on its own decay clock.

## 1. Two clocks: evidence confirmation vs structural touch

The temporal layer (0.6.0, schema rung 2) splits what used to be one timestamp
into two, so "someone edited this recently" no longer masquerades as "this is
still confirmed true":

| Column | Meaning | Bumped by |
|--------|---------|-----------|
| `updated_at` | structural touch | synthesis, edits, merges, any write |
| `last_confirmed_at` | evidence-based confirmation | create, cross-session attach, accepted contradiction verdict |
| `last_confirmed_session_id` | which session confirmed | same events as `last_confirmed_at` |

**Confirmation events** (refresh `last_confirmed_at` + `last_confirmed_session_id`):
- create (initial confirmation)
- cross-session attach (same content re-asserted from a *different* session)
- `resolveContradiction` with `accept-new` **or** `keep-current`

**Non-confirmation events** (do NOT refresh either field):
- same-session attach — damping: re-asserting inside one session is one
  confirmation, not many
- `getConcept` / fetch — reading is not confirming (test "Fetch does not confirm")
- `dismiss` verdict — setting a conflict aside is not evidence
- structural ops — they touch `updated_at` only

**Backfill**: on migration, `last_confirmed_at = updated_at` for rows where it is
NULL and `kind != 'workstream'` (workstreams are excluded from staleness and
merge paths; their NULL is inert). `last_confirmed_session_id` is TEXT, added as
a separate idempotent `table_info`-guarded column.

The point of the split (test B.6 "ranking divergence"): a concept structurally
touched *now* but last *confirmed* 5 days ago must rank below one confirmed
now. Under the old `updated_at`-only ranking the reverse was true.

## 2. Staleness

- `staleAfterMs` — constructor opt, **default 30 days** (`30 * 24*60*60*1000`).
- The staleness clock is `COALESCE(last_confirmed_at, updated_at)` — the same
  expression everywhere it matters.
- `getStaleConcepts(circle)` — active native concepts (non-workstream,
  non-source, non-source-projection, `status='active'`) with
  `now - COALESCE(last_confirmed_at, updated_at) > staleAfterMs`.
- `listStale(circle, limit=20)` — the stale **worklist**, ordered stalest-first
  (`staleAt ASC, id ASC`), SQL-bounded, returns identity/size only
  (`observationCount` filled in). Default limit `OVERVIEW_ENUMERATION_LIMIT = 20`.

## 3. V-A weighting (valence–arousal)

Two additive accumulation columns, each with its own decay. They are **decay
factors on a boost**, never a dominant term — the comments stress arousal is "a
boost, never the dominant ranking term".

### 3a. Usefulness (valence) — fetch-driven

- `usefulness_score` INTEGER, **+1 on every `getConcept`** (fetch), and
  `usefulness_last_fetched_at` = the precise fetch timestamp.
- Decay: `usefulnessDecayed = usefulness_score × exp(-fetchAgeDays / 60)`.
- `USEFULNESS_DECAY_TAU_DAYS = 60` — usefulness fades slower than recency (once
  useful is penalised less sharply than stale).
- The fetch timestamp is the *actual* fetch, not a confirmation proxy
  (test A.3 mutation-checks that reverting to `last_confirmed_at` changes the
  value by >5%). Fallback chain: `usefulness_last_fetched_at ??
  last_confirmed_at ?? updated_at`.

### 3b. Arousal — conflict/confirmation-driven, decay-resistant

- `arousal_score` INTEGER — **cumulative, never decrements**; only the
  *effective* (decayed) value is ever re-read. `arousal_last_updated_at` stamps
  the last spike.
- Event deltas (test A.1):
  - `flagContradiction` → **+3** (a contradiction is high-salience)
  - `resolveContradiction` `accept-new` → **+1**
  - `resolveContradiction` `keep-current` → **+1**
  - `resolveContradiction` `dismiss` → **+0** (not a real conflict, no sustained
    attention)
  - cross-session attach → **+1**
  - same-session attach → **+0**
- Decay: `arousalDecayed = arousal_score × exp(-arousalAgeDays / 120)`,
  `AROUSAL_DECAY_TAU_DAYS = 120` (half the rate of usefulness — more persistent).
- **Floor**: `effectiveArousal = max(arousal_score × 0.1, arousalDecayed)`,
  `AROUSAL_FLOOR_FRAC = 0.1` — a concept retains ≥10% of its cumulative arousal
  no matter how long it idles. The floor dominates past the crossover
  `tau × ln(1/FLOOR_FRAC) = 120 × ln(10) ≈ 276 days` (test A.2 / 2.4).

## 4. livingModelScore — the blend (ADR §4.2)

```
livingModelScore =
    confidence
  × (1 + usefulnessDecayed)        # usefulness boost
  × recency                        # exp(-ageDays / 14)
  × (1 + AROUSAL_WEIGHT_LIVING × effectiveArousal)   # arousal boost, weight 0.5
```

- `recency = exp(-ageDays / 14)` where `ageDays` is from
  `COALESCE(last_confirmed_at, updated_at)` — a **14-day half-life** (hardcoded
  inline, see issue RE-31).
- `AROUSAL_WEIGHT_LIVING = 0.5`.
- Three **independent** decay clocks in one score: recency (14 d, confirmation
  clock), usefulness (60 d, fetch clock), arousal (120 d, spike clock). That is
  by design — each signal ages on its own timeline.

## 5. The living model surface (`overview().livingModel`)

- Pool: active native concepts (kind not in `workstream`/`source`,
  `source_identity IS NULL`, `active_observation_id IS NULL`, `status='active'`)
  **plus** authorized source projections.
- Filter: within the staleness window (`now - COALESCE(last_confirmed_at,
  updated_at) <= staleAfterMs`).
- Sort: `score DESC`, tiebreak `id ASC` (stable, deterministic).
- Slice: `conceptLimit`, **default 5**.
- **Card shape** (`livingModelCard`): `{ id, title, kind, confidence
  (2 decimals), supportCount }` — deliberately **no score, no body**. The score
  that decided the ordering is discarded at the surface (see RE-32 note).

## 6. Merge / detach / sync carry

- `mergeConceptInto` (reassign/merge): usefulness **additive** (src + tgt),
  `usefulness_last_fetched_at` = MAX, arousal = **MAX**, `arousal_last_updated_at`
  = MAX, `last_confirmed_at` = MAX (carries the surviving session id). Nothing
  is lost (test A.4 mutation-checks the carry).
- Partial `detach` into an existing destination intentionally carries **no**
  temporal fields — moved observations are old evidence, not new confirmation.
  A full split recomputes the source's `last_confirmed_at` as
  `min(pre-split value, max(created_at of remaining observations))` so a source
  cannot evade stale-review on stale evidence.
- Sync/graft: the V-A columns travel through `concept_activity_components`
  (`usefulness_count`/`usefulness_last_at`, `arousal_count`/`arousal_last_at`),
  reconstructed per writer; graft applies usefulness additive, arousal MAX.

## 7. Companion seams (same read pass)

- **`embed-budget.ts` — retrieval-quality budget**: `RELIABLE_EMBED_TOKENS = 280`
  (the size below which retrieval measures reliable on the store; unrelated
  pairs shorter than this score 0% at/above `tauAttach`). It is advisory at the
  write boundary but **enforced in the segmenter** (`segmentTokenBudget` caps
  every indexed span at `min(RELIABLE_EMBED_TOKENS, provider window)`).
  `reliableSegmentTokensOf(declared)` honours a declaration only when it is a
  finite number `>= 1`; else falls back to 280 — ONE read/validation shared by
  the segmenter and the window guard (they previously drifted; PR #171).
- **`lexical-overlap.ts` — lexical arm (pure half)**: CONFIRMS RE-04 at readable
  source. `TOKEN = /[a-z0-9][a-z0-9_-]{2,}/gu` is Latin-only; `lexicalTokens`
  lowercases and matches that regex, so Korean/Japanese queries produce an empty
  token set → zero lexical contribution. `tokenIdf = max(0, log(conceptCount /
  (1 + df)))` (clamped at zero — a ubiquitous token is neutral, never negative;
  PR #156). `lexicalOverlap` is applied **per observation and maxed**, not over a
  concept's token union, and is **normalized by the probe**, not the union.
  `LEXICAL_BOOST = 1.0`; `blendLexical(cos, overlap) = cos × (1 + 1.0 × overlap)`
  — multiplicative, so cosine stays the floor and vocabulary cannot talk a
  rejected concept into winning. (The `H1 = 1.0` already in `search-pipeline.md`
  is this same constant.)
- **`spans.ts` — transcript spans**: provenance edges point at a location inside
  a conversation via `span://<host>/<session-id>#<anchor>`. `host` is
  lowercased/unescaped (grammar `^[a-z0-9][a-z0-9.-]*$`); `session-id` and
  `anchor` are percent-encoded so the three delimiters are unambiguous. The
  parse/format pair is **bijective** (stored in a column, compared by string
  equality). Only `claude-code` anchors are interpreted (JSONL line range
  `L<start>-L<end>`, 1-based inclusive, no leading zeros); every other host's
  anchor stays opaque so a new host is storable before its grammar is understood.
- **`synthesis.ts` — synthesizer seam (ADR §4.6)**: the HOST AGENT plugs in
  here. Synthesis produces **only the `body`** — there is deliberately no prose
  `summary` (#232: a summary reads like an answer and stops agents from
  fetching). The default `DeterministicSynthesizer` is a no-LLM stand-in
  (dedupes/joins observations) so the flow (store marks dirty → touch
  synthesizes) can be demonstrated without a generation model.

## Issues found this run

| ID | Summary | Severity |
|----|---------|----------|
| RE-31 | V-A living-model tunables hardcoded | S3 |
| RE-32 | livingModel card discards the ranking score (opaque ordering) | S4 |

- **RE-31** — `USEFULNESS_DECAY_TAU_DAYS` (60), `AROUSAL_DECAY_TAU_DAYS` (120),
  `AROUSAL_FLOOR_FRAC` (0.1), `AROUSAL_WEIGHT_LIVING` (0.5) and the recency
  half-life (14, inline) are module-level constants, not constructor opts. The
  source comment on the arousal block says "These are tuning defaults pending
  sign-off; expose as constructor opts if the pattern holds." Same class as
  RE-01 (dedup thresholds invisible to users): cannot be tuned without patching
  source. The recency 14 is additionally a bare magic number, unlike the named
  usefulness/arousal taus — it would be missed by anyone grepping for decay
  constants.
- **RE-32** — `livingModelCard` returns `{id, title, kind, confidence,
  supportCount}` with no `score` and no signal breakdown. The ranking is
  computed then discarded, so a caller sees *that* a concept ranks high but not
  *why* (recency vs usefulness vs arousal). Consistent with the "structural
  card, no body" philosophy, but the score is a rank signal, not content — a
  mild observability gap.
