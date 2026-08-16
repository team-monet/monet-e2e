# Embedding provider (model-adapter seam + hashing embedder + vector helpers)

Source: `src/embedding.ts` (readable TS, `@team-monet/core` v0.9.0) +
`src/__tests__/embedding.test.ts`, `src/__tests__/eval-baseline.test.ts`.

## What it is

The model-adapter seam: the engine never depends on *how* text becomes a vector. `EmbeddingProvider`
declares the contract (dimension, calibrated thresholds, model id, and the four per-space flags),
`validateEmbeddingProviderOutput` enforces the vector contract at runtime, and
`HashingEmbeddingProvider` is the no-dependency lexical default. The rest of the file is the
vector math the engine shares everywhere (cosine, running-mean blend, JSON serialization).

## Key behaviors

- **Per-space calibration travels with the embedder.** `recommendedThresholds` (tauAttach /
  tauAmbiguous / optional edgeSimMin) is a property of the PROVIDER, not a global, because cosine
  distributions differ by model. `tauAmbiguous` is documented as *near-inert by construction* —
  identical `.50` across profiles because nothing lands under it (a nomination argmax over
  hundreds of concepts concentrates just below tauAttach; measured: the lowest observed fork was
  .6953, so raising it only trades a possible-duplicate edge for an orphan concept).
- **Four per-space flags, all omitted = permissive.** `inputWindow()` (a METHOD, async, because
  the window is a property of the SELECTED model), `countTokens()` (under THIS tokenizer — the
  only count that predicts truncation), `needsLexicalArm` (semantic spaces need the IDF overlap
  arm; the lexical embedder already scores trigrams so the arm double-counts), and
  `reliableSegmentTokens` / `nativeScoreFloor` (measured in that space). A provider that says
  nothing gets no gate — refusing on a guess would be the same invented-limit failure the window
  guard refuses to make.
- **`readsOnlyLatinScript` is a commit, enforced before content accumulates.** An English-only
  model maps unseen-script text to arbitrary directions with no error — the same silent
  "fetchable but unreachable" hole as the window guard, worse because the store is PINNED and
  content written under one model cannot be rescued once the pin moves. Omitted = unknown =
  permissive; only a positively-declared restriction gets enforced.
- **Runtime output validation.** `validateEmbeddingProviderOutput` rejects non-`Float32Array`,
  wrong width (`EmbedderOutputDimensionError`), and any non-finite component
  (`EmbedderOutputNonFiniteError`) before a vector is persisted or scored — so a bad provider
  result never becomes a silently-wrong similarity.
- **Hashing embedder — tokenizer-versioned.** `embed()` hashes `word` features (weight 1.0) and
  char-trigram features (weight 0.5) into a signed `dim` vector via FNV-1a, L2-normalized. The
  tokenizer is VERSIONED: `HASHING_TOKENIZER_VERSION = 2` is the fresh-default, but
  `HASHING_TOKENIZERS` keeps every version this build can still instantiate (v1 ASCII-only,
  v2 Unicode `\p{L}\p{N}`) so a store pinned to an old tokenizer is resurrected byte-identically
  at open rather than silently drifting. An embed-affecting change ADDS a new entry behind a new
  version; an existing entry is NEVER edited in place. `modelId = hashing:dim=<dim>:tok=<ver>`
  is the ONLY signal the graft check has to tell two hashing spaces apart.
- **Vector helpers.** `cosine` is a dot product (vectors are L2-normalized); `blend` is the
  running-mean of a concept vector with a new supporting observation; `blendWeighted` is the
  support-weighted merge of two centroids; `embToJson`/`jsonToEmb` round-trip a vector through
  the TEXT `embedding` column; `isZeroVector` marks the pre-embedding PLACEHOLDER (retrieval
  excludes it rather than scoring it as 0); `normalize` divides by `mag || 1` so an all-zero
  vector stays all-zero (still a placeholder, not a direction).

## Parameters / constants

| Parameter | Value | Role |
|-----------|-------|------|
| `HASHING_TOKENIZER_VERSION` | 2 | fresh-default tokenizer |
| hashing `dim` default | 256 | vector width |
| hashing `modelId` | `hashing:dim=<dim>:tok=<ver>` | vector-space identity for graft rejection |
| hashing `tauAttach` / `tauAmbiguous` | `.55` / `.40` | lexical cosine bands (looser than semantic) |
| feature weights | word 1.0, char-trigram 0.5 | hashing features |
| sign hashing | `(h & 1) === 0 ? +1 : -1` | collision-bias reduction |
| `hash32` | FNV-1a (offset 0x811c9dc5, prime 0x01000193) | feature → bucket |
| `cosine` length | `Math.min(a.length, b.length)` | dot over common prefix |
| `normalize` zero-guard | `Math.sqrt(mag) \|\| 1` | all-zero stays all-zero |
| tokenizer v1 | `[a-z0-9\s]` strip (ASCII-only) | resurrected for old pinned stores |
| tokenizer v2 | `[^\p{L}\p{N}\s]` strip (Unicode `u`) | keeps Korean/CJK/Cyrillic |

## Issues

- **RE-41 (S4, source)** — `cosine(a, b)` computes the dot product over
  `Math.min(a.length, b.length)` and returns a value in `[-1, 1]` for *any* two vector lengths.
  For normalized vectors of mismatched dimension this yields a plausible-looking but MEANINGLESS
  score — the exact "compare two embedding spaces" failure that `PinnedStoreEmbedderUnavailableError`
  (store-embedder.ts) and the graft `EmbedderMismatchError` exist to fail LOUD on, silently
  re-opened one level down. Today no call site reaches `cosine` with mismatched dimensions
  (the provider `dim` contract + `validateEmbeddingProviderOutput` + the pin/graft guards all
  precede it), so it is latent and S4 — but a future caller that bypasses the guards gets noise
  wearing a real score, with no error. See ISSUES.md.

## Verification

- `embedding.test.ts` pins the hashing embedder (dimension, modelId shape, tokenizer versioning,
  unknown-version throws, sign-hashing, trigram features) and the vector helpers
  (cosine-as-dot, blend running-mean, blendWeighted support weighting, embToJson/jsonToEmb
  round-trip, isZeroVector, normalize).
- `eval-baseline.test.ts` pins the lexical-embedder retrieval baseline the `needsLexicalArm`
  semantics reference (why the lexical arm is off for hashing).
