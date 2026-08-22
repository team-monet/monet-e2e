# CLI surface (install / settings validation) — cli.md

> Reverse-engineered from readable TS source — `packages/cli/src/install-cli.ts`.
> AGPL-3.0-only. Owns **RE-52** (malformed PostToolUse crash). The dashboards/
> doctor/repair/materialize CLI modules are documented separately
> (`dashboard.md`, `diagnostics.md`, `repair-cli.md`, `materialize-cli.md`).

## Boundary / responsibility

`monet install` wires Claude Code hooks (the gate enforcement surface): it
parses `~/.claude/settings.json`, validates its shape, and upserts Monet's gate
hook handlers. Malformed settings are meant to **refuse cleanly** and stop,
never touch the file — matching the contract for the PreToolUse arms.

### validateSettingsShape (install-cli.ts:1019-1043)

The shape guard for a parsed settings object:

- Not a JSON object / array / null → refuse (`"not a JSON object"`).
- `hooks` missing → `{ok:true}` (nothing to validate).
- `hooks` not an object → refuse (`"`hooks` is present but not an object"`).
- **`hooks.PreToolUse` missing → `{ok:true}` RETURN EARLY** — this is the bug
  locus: the shape check validates ONLY `PreToolUse`, then returns early when
  it is absent, so any OTHER hook field (PostToolUse, PostToolUseFailure,
  PostToolBatch) is NEVER shape-validated here.
- `hooks.PreToolUse` not an array → refuse.
- Per-group `.hooks` not an array → refuse (`"is present but not an array"`).

The refusal arms feed a shared refuse-and-stop path (install-cli.ts:1307-1313):
"valid JSON but not a settings file this command can safely reason about" —
route through the identical refuse-and-stop rather than let a raw TypeError
surface three calls deeper in `upsertMonetGateHook`.

## RE-52 — install CRASHES on malformed PostToolUse instead of refusing cleanly (confirmed 1.7.1)

**Bug** (upstream #70, sev:minor): `monet install` throws an unhandled JS
**TypeError** instead of refusing cleanly when `hooks.PostToolUse*` is
malformed. Because `validateSettingsShape` early-returns `{ok:true}` when
`PreToolUse` is absent (install-cli.ts:1029), the now-managed
PostToolUse/PostToolUseFailure values skip shape-validation and reach
`upsertHandlerForEvent`, whose `group.hooks.filter(...)` throws.

- Reproduction (run 65 E2E on installed 1.7.1), seeding a settings file with
  ONLY `hooks.PostToolUse` malformed (PreToolUse absent → early `{ok:true}`):
  - `[{"matcher":"x","hooks":"not-an-array"}]` → rc=1 `i.filter is not a function`
    (TypeError).
  - `{"matcher":".+","hooks":[]}` → rc=1 `(t ?? []) is not iterable`.
  Both are an unhandled crash, NOT the clean refusal the PreToolUse
  wrong-shape/malformed arms (test37 F/G) deliver.
- **Desired contract (test55 XFAIL):** refuse cleanly like the wrong-shape /
  malformed PreToolUse arms, not an unhandled TypeError. Locus: extend
  `validateSettingsShape` to shape-validate PostToolUse* (or have the
  shape-check reject any present-but-malformed hook field instead of
  early-returning on PreToolUse absence).

**Status:** `confirmed`, e2e_test `test55`, severity S3.

## References / cross-module

- `coverage-triage.md` / METRICS — install-cli already ~75% upstream-covered
  (gate-cli.test.ts, install-cli.test.ts); this bug is the one clean behavioral
  gap the shape-check leaves open.
- `mcp-server.md` — the gate/hook runtime that install wires.