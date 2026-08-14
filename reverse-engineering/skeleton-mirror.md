# Skeleton mirror (materialized standing files, stale detection)

Source: `src/skeleton-mirror.ts` (readable TS, `@team-monet/core` v0.9.0) + its `__tests__`.

## What it is

The read side of `monet materialize`: the engine writes the "skeleton" (the store's governing
principles, one member = conceptId + body + breadth global/local) into standing Markdown files that a
human reads and may hand-edit. This module detects when a materialized file has gone stale relative
to the store, and tells the caller how to reconcile.

`monet materialize` writes a registry (`materialize.json`) listing each "surface" (absolute path +
scope `global` or `{circle}`) and, per materialized path, a `blockHash`, a `skeletonState` hash, and
a `when` timestamp. This module reads that registry and compares it against both the file on disk
and the current store state.

## Key behaviors

- **The skeleton block** is the span between `<!-- BEGIN monet:skeleton -->` (with optional
  attributes) and `<!-- END monet:skeleton -->`, inclusive of the END marker's final `>`. The
  materialized `blockHash` is a sha256 over exactly that span (any trailing newline excluded), so a
  hand-edit *inside* the markers changes the hash, and an edit *outside* does not.
- **`skeletonStateHash`** hashes the contract's canonical JSON with exact key order and no
  whitespace; `conceptId` ordering is raw JS code-unit order (`<`/`>`), never localeCompare/ICU. The
  manifest's `materialized` lookup uses the raw absolute string from `surfaces[].path` — no
  realpath/case-folding/Unicode normalization. `when` is provenance only and never affects
  freshness.
- **Three stale reasons** (the module's `MirrorStaleReason`):
  - `block-missing` — no block found in the file, or no `materialized` entry for the path (missing
    manifest, missing surface, or a file that never got a block);
  - `block-edited` — `sha256(block) != materialized.blockHash` (a hand-edit inside the markers);
  - `store-moved` — the block is unchanged but the store's current `skeletonState` for that surface's
    breadth no longer matches `materialized.skeletonState` (the skeleton changed since materialize).
- **Reconciliation instruction** (`MIRROR_STALE_INSTRUCTION`): report the divergence and ask the
  user which side is truth — if the store, run `monet materialize`; if a hand-edit, re-declare that
  edit through `memory_declare`, then `monet materialize`. "Never repair without the user's
  confirmation."
- **Coverage is separate from staleness.** `inspectSkeletonMirrors` returns `globalCovered` /
  `localCovered` (whether any registered surface delivers that breadth/home circle) independently of
  `mirrorStale`. An absent or invalid registry is **bootstrap, not an error** — coverage is false
  and there is nothing to flag.
- **Circle-scoped surfaces are matched after alias resolution** — the caller passes a `resolveCircle`
  function, so registrations survive circle renames. Only relevant surfaces are read, and each
  distinct registered path is read at most once (a file cache).
- **The reader side is total** — a missing registry, an unreadable file, a half-written marker, or a
  foreign file all degrade to "uncovered" / "skip" rather than throwing.

## Parameters / constants

| Parameter | Value | Role |
|-----------|-------|------|
| `MATERIALIZE_MANIFEST` | `materialize.json` | registry file name |
| BEGIN marker | `<!-- BEGIN monet:skeleton(?: attrs)? -->` | block start |
| END marker | `<!-- END monet:skeleton -->` | block end |
| `MirrorStaleReason` | `block-missing` \| `block-edited` \| `store-moved` | 3 stale causes |
| `skeletonStateHash` ordering | code-unit `<`/`>`, no whitespace, exact key order | canonical hash |
| `SurfaceScope` | `global` \| `{ circle }` | standing-surface scope |

## Issues

None new. The module is the read half of the materialize loop; the write half lives in
`skeleton-mirror.ts`'s counterpart inside `engine.ts` (the `materialize` command wiring, not yet
documented separately). The stale instruction's "ask the user, never auto-repair" is by-design and
consistent with the gates module's sovereignty stance.

## Verification

`skeleton-mirror.test.ts` pins the manifest parse (strict shape, absolute paths, both scopes), the
canonical hash ordering, the three stale reasons, coverage-vs-stale separation, alias-resolved
circle matching, and the total/never-throwing reader behavior.
