# Source chunker — Markdown → deterministic chunks (parse/segment/hash/ref)

Readable-TS source: `packages/core/src/source-chunker.ts` (828 lines). This is the
parse/segment/hash half of the sources machinery (the scan/ledger/materialize halves are
`source-scanner.ts`/`source-ledger.ts`/`source-materializer.ts`, documented at the
sources-sync.md level). It turns one LF-normalized Markdown file into a deterministic
list of `SourceChunk`s plus a title, with three budget ceilings and a fail-closed
frontmatter parser.

## Pipeline (`chunkSourceText`)

`normalize → parseFrontmatter → sectionsFromMarkdown → mergeUndersizedSections →
computeSourceRefOccurrences → per-section segmentSection → emit chunks`.

Inputs (`ChunkSourceTextInput`): `relativePath, text` (strictly decoded + LF-normalized),
`fileContentHash` (raw bytes hash for scanner/ledger correlation), `ingestConfigHash`,
`maxChunkBytes`, `deadlineExceeded?`, `maxChunks?`. Result carries `frontmatterTitle`
independently of chunk count — a frontmatter-only or empty file resolves a title even
with zero chunks.

## Constants

- `SOURCE_CHUNKER_VERSION = "v5"` — the content-model version gate. Bumps force a full
  re-scan/re-materialization of every existing source (defeats both the source-level
  noop short-circuit and `materializeStagedBindings`' per-chunk unchanged-content skip).
  v5 = chunk embedding input now carries file title + heading path
  (`contextualizeSourceChunk`); v4 = array-frontmatter tolerance (any key); v3 = minimum-chunk-merge bump.
- `CONTENT_HASH_PREFIX = "monet-src-content/v1:sha256:"`.
- `CHUNK_FINGERPRINT_DOMAIN = "monet-src-ingest/v1"`.
- `OPERATION_ID_DOMAIN = "monet-src-op/v2"`.
- `DEFAULT_SOURCE_MAX_CHUNKS = 100_000`.
- `MIN_SOURCE_SECTION_BYTES = 200`.

## Hashing (`hashSourceDomain`)

Domain string + NUL + per-field unsigned 64-bit big-endian UTF-8 byte-length prefix +
bytes → `sha256`, rendered `<domain>:sha256:<hex>`. The length prefix makes concatenations
unaliasable. Used for:

- `computeSourceContentHash(bytes)` — content hash of the **normalized body** (not the
  raw file bytes; the raw bytes hash is the separate `fileContentHash` input).
- `computeSourceIngestFingerprint({contentHash, headingPath, metadata, ingestConfigHash})`
  — chains contentHash + JSON(headingPath) + canonical metadata + `SOURCE_CHUNKER_VERSION`
  + ingestConfigHash.
- `computeSourceOperationId(sourceId, bindingId, fingerprint, snapshotId, generation)` —
  stable retry/idempotency key; `generation` must be a positive safe integer.

## Frontmatter parser (`parseFrontmatter`) — fail-closed flat model

Only flat `key: value` entries are accepted. Refusals (`invalid-frontmatter` diagnostic,
whole file treated as bodyless/unchunked, `frontmatterTitle` null):

- opening `---` with no closing `---`/`...`,
- nested/multiline (a line starting with whitespace),
- a line without a `:` (or empty key / duplicate key),
- block-scalar values (`|`, `>`, `{`),
- `tags` that are not a flat scalar list,
- a flow-sequence value `[a, b, c]` that is genuinely nested (mismatched bracket, stray
  `[`/`]`/`{`, or an unquoted item that is itself a flow-mapping entry `name: Priya`).

**Array-valued frontmatter is accepted for any key (v4):** a flat scalar list is joined
back into one comma-separated string (frontmatter stays `Record<string,string>` — no
second value shape). `tags` keeps its own dedicated bracket handling. The
`rawValueWasQuoted` distinction is load-bearing: a quoted value (`title: "[Draft]"`) is
never a list candidate, because quoting is exactly how YAML marks a bracket-shaped scalar
literal. `frontmatter`/`tags` are canonicalized (UTF-8 sort, dedup) before hashing.

## Sectioning (`sectionsFromMarkdown`)

- **ATX headings only** (`#`..`######`), 0–3 leading spaces. Horizontal rules are NOT
  boundaries. Setext headings are not recognized.
- **Fences are atomic**: a CommonMark backtick/tilde fence swallows everything to its
  close; a heading inside a fence is data. `openingFence` rejects a backtick in a
  backtick fence's info string (CommonMark).
- Each section carries a `headingPath` (hierarchy stack) + `occurrence` (1-based count of
  that exact heading path in the file).

## Minimum-chunk merge (`mergeUndersizedSections`)

A section whose trimmed body < `MIN_SOURCE_SECTION_BYTES` (200) is never emitted alone:

- **Forward merge**: the undersized section flows into the NEXT section, which keeps its
  own identity (the smaller one's identity is dropped). A run of consecutive undersized
  sections cascades forward until the accumulation clears the minimum.
- **Backward merge (EOF only)**: a trailing undersized run with no next section flows
  into the PREVIOUS section, which keeps its identity.
- **The cap wins over the minimum**: a merge that would bust `maxChunkBytes` is skipped
  and the undersized section is emitted standalone (still small, never oversized).
- A file's only section is never merged away (headingless root section included); the
  floor is **inclusive** (a section at exactly 200 bytes does not merge).

## Segmentation (`segmentSection`)

Within a section, content is split at line boundaries into units:

- `segmentUnits` groups lines into paragraphs (blank-line separated) and fenced blocks
  (each fence = one atomic unit).
- A unit > `maxChunkBytes`: if fenced → **fail closed** (`chunk-budget-exceeded`, the
  whole section is skipped — a fence is never split); if prose → `splitNonFenceUnit`
  (line-boundary split, then `splitUtf8`).
- `splitUtf8` walks **code points**, packing to `maxBytes`; a single code point whose
  size exceeds `maxBytes` → `[]` (fails closed, the section is skipped).
- `maxSegments` (remaining chunk budget) enforced throughout; exceeding it throws
  `SourceChunkBudgetError` → `chunk-budget-exceeded` diagnostic.

## Identity fields

- `documentSequence` — 1-based emission order across the WHOLE file, assigned **at
  emission time (post-merge)**, so a file's body reconstruction sorts by true document
  position, never lexicographic heading order ("## Apple" can precede "## Zebra" in a file).
- `segmentIndex` — 1-based within the section.
- `occurrence` — 1-based count of the exact heading path in the file.
- `sourceHeadingAnchor(headingPath)` — `_root` for empty; else NFC + lowercase, strip
  non-letter/number/`/ _-`, whitespace→`-`, collapse `-`; `_untitled` if empty.
- `sourceRef` — `<encoded relative path>#<encoded anchor>~<occurrence>` (the connector
  may prefix its source authority).
- `computeSourceRefOccurrences` assigns occurrence numbers by **natural identity** (sorted
  UTF-8), never caller/input order.

## Classifier seam (`classifySourceFileContent`)

A pure, shared function of bytes (Codex 3606534097, John's ruling "A"): strict UTF-8
decode + LF/BOM normalize + frontmatter validity. The scanner calls it as an early gate;
the materializer calls it pre-seal for the small set of previously-published paths whose
fresh content would now fail. Deliberately excludes `chunk-budget-exceeded` — that
depends on cumulative usage across the walk, so it is not a pure function of one file's
bytes.

## Findings

- **RE-36 (source, S4)** — `splitUtf8` iterates **code points**, not grapheme clusters,
  so an over-budget segmentation can split a combining-character sequence across a chunk
  boundary: decomposed Hangul (자모), or a ZWJ emoji (👨‍👩‍👧‍👦), can end one chunk on a
  dangling combining mark and start the next on its base. Harmless for precomposed
  CJK/Korean (single code points) and content-addressed correctly either way, but a
  grapheme-safe split is the more correct segmentation for linguistic content.
- **Hardcoded chunk tunables** (`DEFAULT_SOURCE_MAX_CHUNKS = 100_000`,
  `MIN_SOURCE_SECTION_BYTES = 200`) are module constants, not per-source options — the
  same "hardcoded tunable, no constructor/CLI override" pattern already recorded as
  RE-01 (dedup thresholds) and RE-31 (living-model V-A). Not a new RE; noted for the
  pattern.
- The frontmatter parser is a hand-rolled YAML **subset** that fails closed on any
  non-flat construct. Consequence: a source file with legitimately nested frontmatter
  (`attendees:\n  - name: X`, block scalars, flow mappings) is skipped, not chunked. This
  is the documented fail-closed contract, not a bug — but it is a real ingestion ceiling
  for Obsidian-style vaults (the source comment itself cites Obsidian arrays as the
  motivation for v4).
