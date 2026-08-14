# Embed budget & window guard (bounded retrieval unit, write/query refusal)

Source: `src/embed-budget.ts`, `src/observation-segmenter.ts`, `src/script-gate.ts`, the window
guard + `ContentExceedsEmbedderWindowError` in `src/engine.ts`, plus
`src/__tests__/{write-budget,query-budget,segment-budget-travel}.test.ts`.

## What it is

The one subsystem that stops the store from silently storing/ranking text the embedder cannot
reliably read. It has three cooperating pieces that form a single rule with a hard boundary and an
enforced ranking granularity:

1. **`RELIABLE_EMBED_TOKENS = 280`** (`embed-budget.ts`) — the retrieval-quality budget, in the
   embedder's own tokens. Below 280, unrelated pairs score 0.0% at/above `tauAttach`; three times
   longer, 93.3% cross it. It is **advisory at the write boundary** (refusing there would turn away
   a large share of legitimate single-claim writes) and **enforced in the segmenter** (which caps
   every indexed span at `min(280, provider window)`).
2. **The segmenter** (`observation-segmenter.ts`) — the *bounded retrieval unit*: splits a long
   observation into segments no larger than the budget so ranking happens at a granularity the model
   reads reliably, regardless of how long the author's observation was.
3. **The window guard** (`engine.ts`) — the *hard* boundary: refuse a write/query whose token count
   exceeds the selected model's input window (the point past which the failure is irreversible data
   loss, not degraded ranking).

The design of record (`docs/design/bounded-retrieval-unit.md`) measured the live store before this
shipped (#155): observation pairs drawn from *different* concepts — the pairs store-time resolution
exists to refuse — cleared `tauAttach` 41.5% of the time; re-scored at segment granularity that
falls to 0.2%, and separability on clean labels rises from AUC 0.7782 to 0.9119.

## Key behaviors

- **The budget travels with the model.** `RELIABLE_EMBED_TOKENS` is only the fallback for a provider
  that declares no `reliableSegmentTokens`. The shipped 280 was derived on multilingual-MiniLM;
  re-derived on bge-small-en-v1.5 by LOO argmax it is 380 (see `MODEL_PROFILES`). A constant left in
  place across a model swap is unjustified until re-derived in the space it now governs.
- **`reliableSegmentTokensOf(declared)`** — one read, one validation: a declaration is honoured only
  when finite and ≥ 1; anything else (0, negative, NaN, Infinity, fractional 0.5) falls back to 280.
  Two consumers (segmenter + guard) previously did their own `?? 280` and drifted — an `Infinity`
  declaration produced advice to "stay under Infinity tokens" (PR #171).
- **`segmentTokenBudget`** returns `min(reliableSegmentTokens, inputWindow)`; `null` when the
  provider declares neither `inputWindow` nor `countTokens` (the lexical provider, which hashes
  everything and has no window — `null` means "do not segment", never "guess a number"). A window
  *narrower* than the budget yields the window (data loss outranks ranking quality).
- **Segmentation is pure and deterministic** (no DB, no clock, no randomness) — the same text and
  budget always produce the same segments, which is what makes the migration idempotent by protocol.
  No overlap between adjacent segments (ruled out in the design: the usual boundary-straddling
  remedy multiplies index size for an unmeasured gain).
- **Boundary hierarchy** — split on the strongest boundary that fits: paragraph
  (`/\n\s*\n+/u`), then sentence (`/(?<=[.!?。！？])\s+|\n+/u`), then a hard cut. A paragraph break is
  the author's own claim boundary; a sentence still leaves a self-contained assertion; a hard cut
  leaves neither and exists only so an unbroken over-budget run still gets indexed rather than
  silently truncated. `hardCut` binary-searches on *tokens* (never characters — the character/token
  ratio moves with script), and prefers a whitespace boundary inside the fitting prefix (`ws > fit*0.6`).
- **Greedy re-packing** — units are packed back up so a short paragraph doesn't become a thin
  fragment; a segment carries more signal close to the budget than as a fragment. The joiner
  reserves one token per join (a tokenizer may count the `\n`), so a segment is never over budget.
- **The window guard is cheap and layered.** `assertWithinEmbedderWindow` runs before any store
  read or embedder load — it costs a tokenizer lookup and nothing else (refusing only *after* paying
  for a model load would be barely better than the silent truncation it removes). It is not applied
  to `storeSource`: a source chunk is materialized from a file that cannot be asked to write
  differently, so its budget belongs to the chunker, not a refusal handed to a connector with no
  author to relay it to.
- **Idempotency-receipt-first.** `storeInternal` looks up the operationId receipt *before* the
  window guard, so a retry of an already-committed operation is a no-op success even if the retry
  body is over the window.
- **The Latin-script gate** (`script-gate.ts`) sits beside the window guard as the same class of
  failure (a write that succeeds and is then invisible to search). `assertEmbedderReadsScript`
  refuses content whose share of non-Latin *letters* exceeds `NON_LATIN_LETTER_TOLERANCE` — but only
  when the provider declares `readsOnlyLatinScript`; never guess a restriction the provider didn't
  state. `nonLatinLetterShare` is a *script* floor, not a language test: French/Vietnamese/Turkish
  score 0 and degrade on an English-only model exactly the same way.

## Error shape

`ContentExceedsEmbedderWindowError` carries `tokens`, `maxInputTokens`, `reliableTokens`, and
`subject: "content" | "query"`. The diagnosis is identical on both sides (the tail is discarded and
nothing says so) but the remedy differs:

- write → "Split it into separate observations, each a single claim"
- query → "Ask the narrower question you actually need" (a query has nothing to split)

The advisory `target` branches: `reliableTokens < maxInputTokens` → "below about N tokens retrieval
is measurably reliable"; else the model window is the binding constraint ("stay well inside it").
The advisory quotes the budget *this embedder* actually segments at, never the global fallback.

## Parameters / constants

| Parameter | Value | Role |
|-----------|-------|------|
| `RELIABLE_EMBED_TOKENS` | 280 (fallback; bge-small-en profile 380) | retrieval-reliable token budget |
| `NON_LATIN_LETTER_TOLERANCE` | 0.2 | Latin-only gate threshold (share of non-Latin letters) |
| paragraph boundary | `/\n\s*\n+/u` | finest claim boundary |
| sentence boundary | `/(?<=[.!?。！？])\s+|\n+/u` | secondary boundary |
| hardCut whitespace preference | `ws > fit * 0.6` | prefer a word boundary over a mid-word cut |
| joiner cost | +1 token per `\n` join | segment never over budget |
| `reliableSegmentTokensOf` rule | finite && ≥ 1 else 280 | one shared validation |
| `segmentTokenBudget` | `min(reliable, window)`, null when unbounded | per-provider budget |
| window-guard predicate | `tokens > inputWindow` | refuse before any embed |
| `ContentExceedsEmbedderWindowError` | subject `content`\|`query`, `tokens`/`maxInputTokens`/`reliableTokens` | surfaced refusal |

## Issues

No new issues beyond what is already recorded: RE-04 (the Latin-only *lexical* arm is a separate
matter in `retrieval.ts`); the script gate here is the *write/embed* guard and is by-design
(provider-declared, 0.2 tolerance). `storeSource` bypassing the write budget is by-design (no author
to retry). All three model-travel invariants (segment budget, card-emission floor, edgeSimMin) are
pinned by `segment-budget-travel.test.ts`.

## Verification

- `write-budget.test.ts` — refusal names `tokens`/`maxInputTokens`/`reliableTokens`; refuses without
  invoking the embedder; leaves the store untouched; accepts at the window; replays a committed
  operationId even over-window; does not refuse `storeSource`; window comes from the provider per
  instance (smaller/larger/null); lexical (no window) is unbounded; advisory never exceeds the window.
- `query-budget.test.ts` — over-window query refused, not truncated; quotes the provider's own
  budget; falls back on invalid declared budgets; refuses without invoking the embedder; query remedy
  ≠ write remedy; in-window query works; lexical query unbounded.
- `segment-budget-travel.test.ts` — segment budget delivers the profile value (shipping default ≠
  280), falls back for unprofiled models, yields to a narrower window, falls back on 6 invalid
  declarations, returns null when no window; card-emission floor travels (honours a legitimate 0,
  falls back on NaN/Infinity/negative/1/above-one, reaches `search()`); edgeSimMin travels
  (bge-m3 0.60 vs class guess 0.45/0.40, constructor opt wins).
