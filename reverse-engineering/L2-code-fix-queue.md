# Monet L2 Code-Fix Queue (for John's prioritization)

> Consolidated, severity-ordered list of the **confirmed** behavioral bugs,
> each with its E2E XFAIL test that reproduces it. This is the promotion list:
> nothing here is speculative — every row is `confirmed` (E2E-reproduced, not
> just source-read). Promotion to a fix is John's call; this file is the input.

Status vocabulary matches `ISSUES.md`. Severity: S1 data loss / S2 scalability/
operability / S3 missing-signal / S4 cosmetic.

## S2 (scalability / operability / security — will bite in production)

| Issue | Test | Bug |
|-------|------|-----|
| RE-30 | test25 | `source_sync` fails `EACCES` on macOS — `sealSnapshot` chmods the tree `0o500` then `renameSync` into place; APFS refuses the in-place rename of a non-writable dir. **Blocks RE-05.** |
| RE-29 | test25 | `sourceStorageDir` hard-defaults to `~/.monet/sources` and is NOT scoped by `-d` — isolated-source work silently writes to prod. |
| RE-24 | test28 | `source update --allow-caller <other>` REPLACES the caller list and silently de-authorizes the acting caller (rc=0, no warning); next `source_list` returns `[]`. |
| RE-26 | test29 | `gate_events` has no retention/pruning — one row per `stage_lookup` call; will become the largest table (2–3 orders > `resolution_events`). |

## S3 (missing signal / UX / maintenance risk)

| Issue | Test | Bug |
|-------|------|-----|
| RE-23 | test26 | `monet start` derives a fallback identity when `MONET_CALLER_ID`/`MONET_PROJECT_ID` are unset, so `source_list` silently returns `[]` — the identity mismatch is not discoverable. |
| RE-17 | test24 | `memory_store` into an archived circle succeeds silently (no guard); the `isArchivedCircle` door exists but store never consults it. |
| RE-07 | test22 | `limit` truncation is silent — no flag tells the caller more matches existed. |
| RE-04 | test30 | Lexical rank arm is Latin-script-only — Korean/Japanese queries (and stored content) get zero lexical contribution. |
| RE-33 | test31 | `slow-queries.jsonl` is write-only — no doctor/CLI/MCP surface reads it. |

## S4 (cosmetic / by-design note)

| Issue | Test | Bug |
|-------|------|-----|
| RE-21 | test27 | `/api/graph` `graphDensity` counts `possible_duplicate_of` edges, inflating structural density. |
| RE-32 | test32 | `livingModelCard` discards the ranking score + per-signal breakdown — ordering is opaque. |

## Dependencies / unblock ordering

- **RE-30 → RE-05**: RE-05 (source concepts skip `nativeScoreFloor`) is the last
  `open` behavioral issue and cannot be E2E-verified until `source_sync` works on
  macOS (RE-30). Fix RE-30 first; RE-05 then becomes verifiable.
- **RE-29 + RE-30 share test25**: both live in the sources/sync path; a single
  sources-sync hardening pass can address both.

## Already fixed (removed from the queue)

- RE-19 (S2, mergeCircle hard-deletes workstreams) — **fixed in 1.6.1**, verified
  XPASS via test23.

## Notes

- All 11 rows above are `confirmed` (E2E XFAIL), 0 speculative. Structural
  issues (`source` status, e.g. RE-01/03/09/13/31/35/36) are deliberately
  excluded here — they route to code-fix separately but are not E2E-observable.
- Re-verify the whole XFAIL set on each `@team-monet/monet` version bump; an
  XFAIL→XPASS flip means the bug shipped fixed and this table shrinks.
