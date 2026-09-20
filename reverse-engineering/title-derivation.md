# Title derivation (`firstLine()`) — card titles, slugs, and arbitration evidence

> RE-60 · upstream [`team-monet/monet#117`](https://github.com/team-monet/monet/issues/117)
> Owner of the served card shapes also referenced here: `mcp-server.md`,
> `render-overview.md`, `living-model-ranking.md`, `search-pipeline.md`.
> Evidence basis: **dist 1.11.0** (GR-08) driven over the live MCP stdio path in an
> isolated temp store (`~/.monet-test/tests/test61_re60_title_truncation.py`),
> plus a read of `main` @ `d920bc2` for the source anchors below.

## The helper

`packages/core/src/engine.ts:18889-18894` (identical in `main` @ `d920bc2`):

```ts
function firstLine(content: string): string {
  // A period BETWEEN digits is not a sentence end — version numbers like "0.5.0" or
  // "v0.6.0" stay intact instead of truncating the title at their first dot.
  const line = content.trim().split(/\n|(?<!\d)\.|\.(?!\d)/)[0].trim();
  return line.length > 80 ? line.slice(0, 77) + "…" : line || content.trim().slice(0, 80);
}
```

The written intent is version numbers. The implementation is far wider: **any period
with a non-digit on at least one side is a split point**, so a filename, a domain, an
initial or an abbreviation ends the title. Only `0.6.0`-style tokens (digit on BOTH
sides) survive.

## Where it lands

| Site | Field |
|------|-------|
| `engine.ts:18250` (`create()`), `:18408` (rewrite) | `concepts.title` |
| `engine.ts:18259` | `concepts.slug = slugify(title)` — the slug inherits the cut |
| `engine.ts:1793` (`toSkeletonEntry`) | declared principle/preference `content` |
| `engine.ts:5772` | contradiction `detail = \`correction: ${firstLine(content)}\`` — **the line an agent arbitrates from** |
| `engine.ts:7055`, `:8138` | `nextTitle` on attach/append when the row is not a workstream |
| `engine.ts:8876` | source concept title |
| `engine.ts:12964` | impeachment evidence text (`"${firstLine(incumbent.body)}"`) |

Consequence: the cut is not only cosmetic card text — it reaches the arbitration
record and the skeleton projections. `workstream` rows are explicitly exempt
(they keep their own title).

## Card shapes the cut shows up in (measured)

| Surface | Shape | What the reading agent sees |
|---------|-------|-----------------------------|
| `memory_list` | `{id, slug, title, kind, circle, observationCount}` | truncated `title` |
| `memory_search` | `{id, slug, kind, circle, observationCount}` — **no `title` at all** | the truncated **slug is the entire triage text** (`mcp-server.md:46`) |
| `memory_overview` LIVING MODEL | `kind · title · supportCount` | truncated `title` |
| `memory_store` correction ack | `contradiction.detail` | `correction: <truncated line>` |

## Measured on dist 1.11.0 (test61, 2 consecutive runs, isolated temp store)

| Arm | Stored body (token elided) | title observed | title desired |
|-----|---------------------------|----------------|---------------|
| file extension | `Updated app/card-image.ts downloadCardImage canvas exporter for …` | `Updated app/card-image` | keeps `app/card-image.ts` |
| config file | `Bump vite.config.ts target to es2022 for the … dashboard build` | `Bump vite` | keeps `vite.config.ts` |
| component | `Layout Height Collapse: Svelte mounts App.svelte at the root, …` | `Layout Height Collapse: Svelte mounts App` | keeps `App.svelte` |
| domain | `Deploy the docs to example.ai and mirror … on acme.dev` | `Deploy the docs to example` | keeps `example.ai` |
| email lead | `jane.doe@example.com reported the … crash` | `jane` | (record only — privacy tension) |
| abbrev lead | `Use e.g. a lexicon entry instead of patching text, …` | `Use e` | (record only — NOT covered by #117's proposal) |
| version control | `monet-core 0.6.0 ships the temporal layer for …` | intact | intact ✅ |
| plain control | `Korean search works after the bge-m3 repair for … memories` | intact | intact ✅ |
| sentence end | `Refactored the resolver. The old … path is gone.` | `Refactored the resolver` | still ends there ✅ |
| newline | `First line about …\nSecond line …` | `First line about …` | still ends there ✅ |

Slug inheritance measured in the same run: the `vite.config.ts` concept's search-card
slug is `bump-vite`, and `app/card-image.ts` yields `updated-app-card-image` — the file
name is unrecoverable from the search surface.

Correction detail measured in the same run (base concept + one attaching correction):

```
action=attached  contradiction.detail = "correction: Correction: bump vite"
```

so the agent deciding `accept-new` / `keep-current` is told the correction changes
"vite" — not that it changes `vite.config.ts`.

## Status / flip semantics

- **Upstream:** #117 is `state=OPEN` (filed 2026-08-29 by JohnOnLee, 0 comments); no fix
  PR exists; **no duplicate was filed** (the E2E contract files only when nothing tracks it).
- **Not fixed in `main` either:** the regex in `main` @ `d920bc2` is byte-identical to the
  shipped bundle, so test61 keeps XFAILing until a release carries a changed `firstLine`.
- **Guard:** `tests/test61_re60_title_truncation.py` — XFAIL, exit 2, **18 held checks +
  7 desired-but-unmet** across the two surfaces. The held checks are the *regression* half:
  if a fix widens the split (e.g. drops the sentence-end semantics or the first-line rule)
  those arms go red instead of flipping the test green.
- **Suggested direction in #117** (`split(/\n|\.(?=\s|$)/)`) fixes the filename/domain arms
  and the `0.6.0` control, but NOT the abbreviation arm (`e.g.` = period + space) — which is
  why that arm is evidence-only here: asserting it would keep the guard XFAIL after the fix.

## Tension worth stating, not asserting

The narrower rule that fixes filenames (`period followed by whitespace or EOL`) also stops
truncating an email or a sentence that ends mid-line, i.e. it widens the amount of stored
text projected into a title. #117 itself flags the privacy edge (an email-led body currently
degrades to `jane`); that is a product decision, not a test assertion.
