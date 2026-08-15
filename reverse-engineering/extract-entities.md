# Monet Reverse-Engineering — Entity Extraction (`extractEntities`, `about`-edge anchors)

> Status: **DOCUMENTED** (2026-08-16, run 34). Source: `packages/core/src/extract-entities.ts`
> (readable TS, commit 83e9d7d, core 0.9.0) + `engine.ts` entity/`about` derivation. The
> last two undocumented readable-TS modules outside the halt list.

## TL;DR

`extractEntities(text) → ExtractedEntity[]` is a **cheap, deterministic,
dependency-free** entity extractor for short technical memory text (#245). Entities are
the anchors for `about` edges: two concepts that mention the same RARE entity are linked.
No NLP library — stable surface-form keys, not POS tags; the repo forbids new deps and
non-determinism.

- **Key form** `${kind}:${surface}` — e.g. `path:apps/api`, `lib:jose`, `id:AuthService`,
  `err:ECONNREFUSED`, `noun:migration`. `noun` and `lib` surfaces are lowercased; `path`/
  `id`/`err` surfaces are case-preserved.
- **Weight** (anchor strength): structural = 3, lib = 2, noun = 1. Feeds
  `rarity × kindBoost` edge weighting in the engine.
- **Two passes**: structural (high precision, case-sensitive, spans removed so they
  aren't re-counted as nouns), then nouns (lowercase residual, drop stopwords + short +
  numeric tokens, apply morphology).

## Pass 1 — structural (order matters)

| Pattern | Kind | Weight | Notes |
|---|---|---|---|
| `PATH_FILE` `\b[\w./-]*\w…\.(ts\|tsx\|js\|jsx\|mjs\|cjs\|json\|sql\|md\|sh\|ya?ml\|py\|go\|rs\|toml\|css)\b` | path | 3 | file paths |
| `PATH_SLASH` `\b\w[\w-]*(?:/[\w.-]+)+\b` | path | 3 | slash paths |
| `ERRCODE` `E[A-Z]{3,}\|…\|E\d{2,}` | err | 3 | error codes |
| `CAMEL` `\b[A-Za-z][a-z0-9]*[A-Z]\w*\b` | id | 3 | camelCase AND PascalCase (internal capital required) |
| `SNAKE` `\b[a-z0-9]+_[a-z0-9_]+\b` | id | 3 | snake_case |
| `DOTTED` `\b[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w+)+\b` | id | 3 | dotted identifiers |

Paths run before dotted so `foo.ts` is a path, not a dotted id. Matched spans are
replaced with spaces (offset-stable) so the noun pass never re-counts them.

## Lexicon (pass 1.5)

`LEXICON` (a null-prototype object — so `"constructor"` etc. can't resolve inherited
properties and crash `surface.toLowerCase()`; the `#extract-constructor-crash` fix) maps
42 canonical library/tool names (`jose`, `jsonwebtoken`, `pnpm`, `npm`, `better-sqlite3`,
`postgres`, `drizzle`, `hono`, `stripe`, `redis`, `playwright`, `vitest`, `zod`, `react`,
`nextjs`, `node`, `typescript`, `onnx`, `minilm`, `next-intl`, …). Scanned against the
lowercased full text via the Latin-only `WORD = /[a-z][a-z0-9]*/g`; a hit → `lib` entity
with the canonical surface.

## Pass 2 — nouns

- **Segmentation via `Intl.Segmenter(undefined, {granularity:"word"})`** (Node 22 full
  ICU) — the #187 fix: the old `[a-z]`-only `WORD` produced ZERO entities (and therefore
  zero derived edges) for Korean/Cyrillic/Greek/Arabic/Hebrew (character class) and
  Chinese/Japanese/Thai (not whitespace-delimited). Determinism is now runtime-stable,
  not cross-runtime-stable (a future ICU revision may segment differently) — accepted
  because the alternative was "silently empty for most of the world's text"; edges are
  re-derived rather than frozen, so a shift is drift, not corruption.
- **NFC normalize before the noun pass** (PR #189): an entity key IS the join column for
  `about` edges, so composed vs decomposed spellings of one word must not be two keys.
- **Split on `/[^\p{L}\p{N}\p{M}]+/u`** (PR #189): ICU keeps punctuation-bearing strings
  as one word, so `it's` and `café.ts` leaked into morphology — one split fixes both.
- **`HAS_LETTER = /\p{L}/u`** gate: `isWordLike` is true for numbers, so `2026`/`3.14`
  would otherwise become entities; the module's contract has always dropped numeric-only
  tokens (dates/counts/versions would link unrelated concepts).
- **`tooShort(token)` = length < 2** (PR #189): the floor was lowered from 3. The
  English-specific thing is the STOPWORDS word list, not a script property, so the floor
  became script-neutral and two-letter English function words moved into STOPWORDS.

## STOPWORDS

English function words + code chatter (`file`, `fix`, `use`, `set`, `get`, `add`,
`server`, `config`, …) + two-letter English + **non-Latin function words** (Japanese
`した/する/ある/この/その/など/ため…`; Korean `하는/있는/없는/이런/대해/통해/위해/때문…`;
Chinese `这个/那个/可以/因为/所以/但是…`). Single-character non-Latin particles (의/를/の)
never reach here — `tooShort` drops them.

## Morphology (`normalizeToken`)

Dispatches per script: `HANGUL_ONLY` (`/^\p{Script=Hangul}+$/u`) → `stripKoreanParticle`,
else `singularize` (English plural stripping). The dispatch makes "add the next script"
an entry rather than a rewrite — but note only English and Korean are implemented today;
Japanese/Chinese/Cyrillic nouns flow through `singularize` (English morphology), which is
mostly inert on them (documented as structural, not a rewrite).

- **`stripKoreanParticle`** — Korean 조사 are a CLOSED class, so stripping them is the
  same move `singularize` makes for English plurals. Without it 주식/주식을/주식이/주식은
  are four entities and the stock-tracker concepts never link. `KOREAN_PARTICLES` is 36
  entries; **longest-match wins**, and a strip never leaves fewer than two syllables
  (`w.length - p.length >= 2`) — 마을/가을 end in 을 without containing a particle.
  `KOREAN_PARTICLE_SET` is a separate whole-token check: a token that is ENTIRELY a
  particle (Korean spacing often isolates one) is dropped, where the length-guarded strip
  would refuse.
- **`singularize`** (conservative, never touches structural entities): ≤3 chars no-op;
  `(us|is|os|as|ss)$` no-op (status/analysis/class); `ies→y`; `(sses|shes|ches|xes|zes)$`
  strip 2 (boxes→box); else trailing `s` strip 1 (tokens→token).

## The `about`-edge consumer (engine.ts)

Extraction is only half — the engine decides whether a shared entity MATERIALIZES an
edge (`deriveConceptEntityEdges`, engine.ts ~17740):

- On store, `extractEntities(content)` → `INSERT OR IGNORE` into `concept_entities
  (concept_id, entity_key, scope)` + bump `entities.df` (per-scope concept frequency =
  rarity signal).
- Per shared entity: `strongAlone = kind !== "noun" && df <= RARE_DF_MAX` (`RARE_DF_MAX =
  5`) — one rare structural anchor alone justifies an `about` edge.
- Else the `isHubDf(df, n)` hub gate skips the edge (but KEEPS the `concept_entities` row
  + df, so `df == COUNT(rows)` stays invariant — a hub entity un-hubbing on one delete
  would flip-flop edges); otherwise edge strength = `rarityFromDf(df, n) *
  KIND_BOOST[kind]`, summed over shared entities, must reach `EDGE_MIN_STRENGTH = 2.0`.
- `entities`/`concept_entities` are exported/grafted scoped to the exported concept ids,
  moved on circle reassignment, and scrubbed in lockstep (key/surface + entity_key).

## The `.mjs` mirror (maintainability)

`src/extract-entities.mjs` is a **byte-for-byte mirror** of `extractEntities`, added so
`scripts/scrub-db.mjs` (plain `node`, not `tsx`) can re-run the SAME extraction against
scrubbed text to prune now-stale entity fragments (the "entity fragment leak": the
extractor atomizes `jane.doe@example.com` into `id:jane.doe` + `id:example.com` at store
time, before any scrub pattern sees the combined string). The mirror is kept in sync by a
mirror-identity test (`extract-entities-nonlatin.test.ts` "mirror — identical output").

## Issues found

- **RE-38 (S4, source):** `extractEntities` logic is duplicated between
  `extract-entities.ts` and its byte-for-byte `.mjs` mirror — the same "two files must
  change in lockstep" maintenance risk as RE-03 (dist bundle duplication), but LOWER
  severity because drift is caught by the mirror-identity test, and the split exists for a
  real reason (plain-node scrubbing without a TS-import dependency). A change to the
  extractor must update both; the test is the safety net, not a removal of the risk.
- (Non-issue, documented) `singularize` applied to non-Korean non-Latin nouns is the same
  "one language implemented" gap the `normalizeToken` dispatch is designed to make
  structural — the next script is an entry, not a rewrite.
