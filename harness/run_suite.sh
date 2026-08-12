#!/usr/bin/env bash
# Monet E2E suite runner — cron/CI convenience wrapper.
#
# mcp_client.py resolves the Monet CLI from MONET_CLI or `monet` on PATH. In a
# bare cron environment neither is set (no interactive PATH), so the suite would
# fail with "No such file or directory: 'monet'". This wrapper exports local
# defaults for every variable; each can still be overridden by the caller.
#
# Usage:  harness/run_suite.sh            # full suite
#         MONET_TEST_DIR=/tmp/x harness/run_suite.sh   # custom isolated dir
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="${MONET_NODE_PATH:-/opt/homebrew/opt/node@22/bin}:$PATH"
export MONET_CLI="${MONET_CLI:-/Users/codalee/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js}"
export MONET_NODE_PATH="${MONET_NODE_PATH:-/opt/homebrew/opt/node@22/bin}"
export MONET_TEST_DIR="${MONET_TEST_DIR:-$HOME/.monet-test}"

exec python3 harness/run_all.py "$@"
