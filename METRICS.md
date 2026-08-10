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

## Metric definitions

- **Tests**: number of verification scenarios/tests present in the isolated environment
- **Coverage (%)**: share of the 9-scenario test matrix covered (scenario basis)
  - 1 startup/handshake, 2 store→search→retrieve, 3 Korean search, 4 cross-session persistence,
    5 circle isolation, 6 contradiction detection/resolution, 7 schema migration, 8 repair regression, 9 concurrency
- **Failure (%)**: share of tests failing in the most recent run

## Stagnation detection rules

- 3 consecutive weeks with 0 growth in tests/coverage → try a different angle (read more product source, attempt a new scenario)
- 2 consecutive weeks of rising failure rate → prioritize root-causing the failures
