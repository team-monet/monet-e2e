# Store embedder selection (pin enforcement + no-silent-downgrade startup)

Source: `src/store-embedder.ts` (readable TS, `@team-monet/core` v0.9.0) +
`src/__tests__/embedder-pin.test.ts`, `src/__tests__/embedder-safety-contract.test.ts`.

## What it is

The startup decision that maps a store's durable state to the embedder served to it, run BEFORE
`MonetCore` construction. Its whole job is to make "wrong embedder" LOUD: a store pinned to one
model served through another compares two vector spaces and returns noise, not degraded results,
and nothing in the response says so. So it refuses instead of falling back.

## Key behaviors

- **Pins are authoritative and REQUIRED to load.** `chooseStoreEmbedder(dbPath)` reads the
  persisted pin first; if present and loadable, that embedder is instantiated via
  `instantiateEmbedderForPin` (exact model string, or the exact hashing tokenizer version).
  If the pin cannot load → `PinnedStoreEmbedderUnavailableError` (refuse to serve) UNLESS the
  store is empty (`readStoredVectorPresence === false`), in which case it defers to the engine's
  empty-store re-pin recovery rather than rendering a recoverable store unserveable.
- **Three states, not two.** Unpinned: (1) `readStoredVectorPresence === true` → legacy path —
  the store already holds vectors and `ensureEmbedderPin` will infer the model from their
  DIMENSION after construction, so it reaches the engine via `createLocalEmbedder()`; (2) `false`
  or `null` → fresh path — `requireSemanticOrExplicitLexical()`. The `null` case is the subtle
  one: an earlier `!== false` test folded "could not read the store" into the legacy branch, so
  an unreadable unpinned store took `createLocalEmbedder()` (which may silently return the lexical
  fallback) and got pinned to it PERMANENTLY — the exact silent degradation this file exists to
  prevent. Only a confirmed `true` licenses the legacy path; unknown is treated like fresh.
- **Never an implicit downgrade.** `requireSemanticOrExplicitLexical()` calls
  `createLocalEmbedderWithProvenance()` and throws `FreshStoreEmbedderUnavailableError` if the
  selection was `implicit-hashing-fallback`. `MONET_EMBEDDER=hashing` stays honoured (an operator
  who asks for lexical recall gets it); what is refused is the SILENT path where the model fails
  to load, a `console.error` goes to a stderr no MCP host displays, and the store serves lexical
  while its vectors are semantic. The fresh-store error message names both remedies (fix the model
  cache, or `MONET_EMBEDDER=onnx` to see the underlying error / `MONET_EMBEDDER=hashing` to
  explicitly opt in).

## Parameters / constants

| Parameter | Value | Role |
|-----------|-------|------|
| pin source | `sync_meta.embedder_model_id` (singleton row) | durable embedder identity |
| vector presence | `observations` any row OR `concepts` non-null `embedding` | `true`/`false`/`null` |
| `MONET_EMBEDDER` | `onnx` (default) \| `hashing` (explicit lexical opt-in) | embedder selection env |
| empty-store recovery | `readStoredVectorPresence === false` | pin-load failure defers to engine re-pin |

## Issues

None new. The three-state logic and the "unknown is fresh" handling are themselves the fixes for
the silent-downgrade bug (documented in-line: FIX Z empty-store heal, Codex P1 PR #173 legacy
path, and the `readStoredVectorPresence` `null` correction). Its sharp edges are already closed.

## Verification

- `embedder-pin.test.ts` + `embedder-safety-contract.test.ts` pin: pinned store served through the
  wrong provider refuses (not falls back); empty pinned store defers to recovery; fresh store
  refuses implicit lexical fallback; `MONET_EMBEDDER=hashing` honoured; legacy vector-bearing
  store reaches the engine.
