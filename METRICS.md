# Metrics — progression over time

> Updated after each run. "Progress" is judged by the numbers here, not by vibes.

## Core metrics

| Date | Tests | Coverage (%) | Failure (%) | Scenarios passing | Run summary |
|------|-------|--------------|-------------|-------------------|-------------|
| 2026-08-08 | 7 | 78 | 0 | 1,2,3,4,5,6,8 | Pilot → first real run: pure-stdio MCP client implemented, 7 scenarios built & passing (41 assertions) |
| 2026-08-09 | 9 | 100 | 0 | 1,2,3,4,5,6,7,8,9 | Run 2: scenario 7 (old 1.2.4 fixture → auto migration) & 9 (2-process WAL concurrency) added, coverage 100% (59 assertions) |
| 2026-08-10 | 10 | 100 | 0 | 1..10 all | Run 3: scenario 10 (dedup growth) added, scenario 9 deepened (4-process burst, dedup-under-load), test05 re-run bug fixed (GR-06), assertions 59 → 77 |
| 2026-08-10 (run 4, 20:00) | 11 | 100 | 0 | 1..11 all | Run 4: test11 (synthesis transition + growth curve) added — needsSynthesis appears by 2 stores, memory_synthesize clears it + records concept_revisions row, 30-obs growth curve (segments 1:1, tokens accumulate), assertions 77 → 96 |
| 2026-08-11 (run 6) | 12 | 100 | 0 | 1..12 all | Run 6: test12 (synthesize idempotency + version semantics) added — version is DERIVED (obsCount-1, flat across calls, not unique per revision row); needsSynthesis set from creation; test05 re-run bug fixed (token-scoped unrestricted query, GR-06 extension), assertions 96 → 119 |
| 2026-08-11 (run 8) | 13 | 100 | 0 | 1..13 all | Run 8: test13 (needsSynthesis flag lifecycle) added — flag RE-FLAGS on new attach after synthesize (store→synth→store→synth loop repeatable), synthesized body preserved + observations append, version tracks live obsCount (4→7), assertions 119 → 135 |
| 2026-08-11 (run 9) | 14 | 100 | 0 | 1..14 all | Run 9: test14 (contradiction × needsSynthesis + accept-new body guard) added — correction observation re-arms needsSynthesis on a synthesized concept; accept-new resolve REFUSED without `body` when 2+ prior observations (anti-guess guard, boundary-probed); resolve-with-body replaces concept body + writes a 2nd concept_revisions row; `disputed` is an overview/counts signal, not a fetch-card field; assertions 135 → 160 |
| 2026-08-12 (run 12) | 16 | 100 | 0 | 1..16 all | Run 12: test16 (contradiction DISMISS on a SYNTHESIZED concept + dismiss-with-body boundary) added — dismiss is verdict-orthogonal to synthesize state (same no-verdict close semantics as test15 on a plain concept; body/obs/revisions untouched, 1 revision row = synthesize only); dismiss WITH `body` silently IGNORES it (E2E-confirms RE run-11 finding 6: no verdict text, no extra revision, contradiction still closes); needsSynthesis stays True after dismiss (resolve is not a synthesize); assertions 176 → 213 |
| 2026-08-12 (run 13) | 18 | 100 | 0 | 1..18 all | Run 13: test17 (keep-current verdict) + test18 (RE-14 no-attach correction) added — verdict matrix now COMPLETE (accept-new/dismiss/keep-current): keep-current supersedes the CORRECTION (superseded_by NULL, successor NULL) while priors stay live, row `status='resolved'` with resolution_obs_id NULL, body-less = no revision row / with body = +1 revision (mirrors accept-new), arousal +1, last_confirmed_at refreshed; test18 E2E-confirms RE-14: a topically-disjoint correction creates its own concept and opens ZERO contradictions (auto-flag fires only on attach); harness lesson: store ack has no observationId — derive from contradictions row; added harness/run_suite.sh cron wrapper (bare cron PATH lacks monet; env-overridable); assertions 213 → 247 |
| 2026-08-13 (run 15) | 19 | 100 | 0 | 1..19 all | Run 15: test01 tool-surface stale assertion fixed (21 → 23 tools; 1.6.1 added memory_retire/memory_restore — lockstep count check + extra-set check so future bumps fail loudly); test19 (MANUAL memory_flag_contradiction opener) added — five arms: staleness flag data layer (row kind/status/obs, confidence −0.3 floor 0.1, arousal +3, derived 'disputed' + openContradictions on fetch card), kinds stack + observationId passthrough (3 open rows), wrong-circle / rule / retired refusals (zero rows; first memory_retire E2E — ack + fetch-not-found); assertions 247 → 284 |

## Metric definitions

- **Tests**: number of verification scenarios/tests present in the isolated environment
- **Coverage (%)**: share of the 9-scenario test matrix covered (scenario basis)
  - 1 startup/handshake, 2 store→search→retrieve, 3 Korean search, 4 cross-session persistence,
    5 circle isolation, 6 contradiction detection/resolution, 7 schema migration, 8 repair regression, 9 concurrency
- **Failure (%)**: share of tests failing in the most recent run

## Stagnation detection rules

- 3 consecutive weeks with 0 growth in tests/coverage → try a different angle (read more product source, attempt a new scenario)
- 2 consecutive weeks of rising failure rate → prioritize root-causing the failures
