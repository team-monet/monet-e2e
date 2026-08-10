# Monet E2E

End-to-end test suite for [Monet](https://github.com/team-monet/monet) — local-first, MCP-native memory for AI agents.

This repository continuously exercises Monet against a real server process and a real SQLite store. It is the verification layer behind Monet's durability story: what an agent stores today must be retrievable tomorrow, in isolation, under concurrency, and across schema migrations.

## What is covered

| # | Scenario | Test | Assertions |
|---|----------|------|-----------|
| 1 | Startup & MCP handshake | `test01_handshake.py` | 5 |
| 2 | Store → search → retrieve round trip | `test02_store_search.py` | 6 |
| 3 | Korean search retrieval | `test03_korean_search.py` | 3 |
| 4 | Cross-session persistence (server restart) | `test04_cross_session.py` | 4 |
| 5 | Circle isolation & reassignment | `test05_circle_isolation.py` | 9 |
| 6 | Contradiction detection & resolution | `test06_contradiction.py` | 8 |
| 7 | Schema migration (real 1.2.4 fixture → current) | `test07_schema_migration.py` | 10 |
| 8 | Repair regression (post-migration state) | `test08_repair_regression.py` | 6 |
| 9 | Concurrency (multi-process + burst writes) | `test09_concurrency.py` | 15 |
| 10 | Dedup growth (API + DB layer) | `test10_dedup_growth.py` | 11 |

**Current status: 10/10 passing, 77 assertions, 0% failure.** See [METRICS.md](METRICS.md) for the full history.

## Requirements

- Python 3.9+
- Node.js (18+; the Monet package is a Node CLI)
- The Monet npm package installed globally:
  ```sh
  npm install -g @team-monet/monet
  ```
- For scenario 7 (schema migration) you also need an old `@team-monet/monet@1.2.4` install — see "Schema-7 fixture" below.

## Running

```sh
export MONET_CLI=$(which monet)          # optional: path to Monet CLI (defaults to `monet` on PATH)
export MONET_NODE_PATH=/path/to/node/bin # optional: node bin dir to prepend to PATH
export MONET_TEST_DIR=$HOME/.monet-test  # optional: where test data lives (default: ~/.monet-test)

python3 run_all.py
```

Every test spawns its own `monet start -d <dir>` server process against the isolated test DB. The suite runner exits non-zero if any test fails.

To run a single test:

```sh
python3 test01_handshake.py
```

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MONET_CLI` | `monet` on PATH | Path to the Monet CLI (`cli.js`) |
| `MONET_NODE_PATH` | *(empty)* | Node bin dir prepended to PATH for the server process |
| `MONET_TEST_DIR` | `~/.monet-test` | Where the isolated SQLite DB and fixtures live |
| `MONET_FIXTURE_DIR` | `$MONET_TEST_DIR/fixtures/schema4` | Where the schema-4 fixture is (scenario 7) |
| `MONET_OLD_CLI` | `$MONET_TEST_DIR/prefix-old/...` | Path to the old 1.2.4 CLI (fixture generator) |

## How the harness works

- `mcp_client.py` — zero-dependency MCP stdio client. Spawns the server, does `initialize → tools/list → tools/call`, unwraps the standard MCP content block into JSON. All tests use it.
- `run_all.py` — suite runner: runs every `testNN_*.py`, prints per-test PASS/FAIL + timing, exits non-zero on any failure.
- Each test is self-contained and **re-run safe**: fresh circles and content tokens per run (GR-06), so repeated runs never pollute each other.

## Known product findings

These observations surfaced from the test suite and are relevant product input:

- **Fresh DB pins `Xenova/bge-small-en-v1.5`** (English-only). Korean store/search is refused with an explicit non-Latin error until `monet repair` migrates to `Xenova/paraphrase-multilingual-MiniLM-L12-v2`. Use the bare model ID, no `onnx:` prefix.
- **Schema auto-migration works**: opening a new server on a schema-4 DB auto-migrates 4 → 12 and backfills the pin to the legacy embedder so existing vectors stay valid. Old observations remain retrievable.
- **SQLite WAL concurrency is solid**: two server processes sharing one DB — interleaved stores, cross-visibility, zero `database is locked` / `SQLITE_BUSY` errors.
- **Dedup is aggressive** (product observation): template-similar sentences with different nouns still merge into one concept (20 semi-distinct sentences → 5 concepts). Truly distinct sentence structure is required to stay separate (20 hand-written sentences → 20 unique concepts). Worth checking the dedup threshold parameter.
- **Dedup growth pattern**: first store `action=created`; later near-identical stores `action=attached` to the same concept. `observationCount` grows 1:1; `body` accumulates all observations. At the DB layer, `observation_segments` rows == observations (1:1), `observation_tokens` accumulate per observation.
- Korean-only concepts get empty slugs even with the multilingual embedder — cosmetic; retrieval still works.
- `monet doctor` needs `--check-provider` to report `Assessment: safe`.

## Schema-7 fixture (regeneration)

Scenario 7 tests migration from a real 1.2.4-era database. The pristine fixture is generated once and copied to a scratch dir per run (so the pristine copy is never mutated):

```sh
# install the old package into a prefix dir once
npm install --prefix $MONET_TEST_DIR/prefix-old @team-monet/monet@1.2.4
# generate the fixture DB (spawns old cli.js start → store → close)
python3 make_fixture_schema4.py
```

## Guardrails

The autonomous agent that maintains this suite operates under explicit guardrails — see [GUARDRAILS.md](GUARDRAILS.md). The two that matter most for contributors:

- **GR-01**: tests must run against an isolated data dir (`-d`), never the real store.
- **GR-06**: tests must be re-run safe — no shared fixed circle names or state pollution between runs.

## Contributing

Feedback is welcome via [GitHub Issues](../../issues):

- 🐞 **Bug report** — a test failing, or behavior that looks wrong
- 🧪 **Test suggestion** — a scenario that should be covered
- 💬 **Question / feedback** — anything else

Every issue filed here is reviewed by the maintainers (and, when the suite is running, by the autonomous agent itself). See the issue templates for details.

## License

Apache-2.0 — see [LICENSE](LICENSE).
