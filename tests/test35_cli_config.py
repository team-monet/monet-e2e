#!/usr/bin/env python3
"""Scenario (CLI surface): `monet config` — MCP config generation (test35).

The MCP stdio surface (`monet start`) is the only path the earlier scenarios
exercise; the CLI subcommands (`config`/`gate`/`install`/...) are never invoked,
so config-cli.ts / install-cli.ts / gate-cli.ts sit at 0-7% source line
coverage. This is the first CLI-subcommand scenario: it drives `monet config`
through the same process boundary and pins the emitted config shape per agent
type. (See the `monet-e2e-testing` skill, "Code line coverage" section.)

`monet config` is side-effect-free — it resolves paths and emits JSON/YAML; the
only disk write is the explicit `-o` target. Safe against GR-01.

Arms:
A. default (claude-code): {mcpServers:{monet:{command,args,env}}} with
   MONET_STORAGE_DIR pinned to the override and NO MONET_PROJECT_DIR
   (claude-code supplies CLAUDE_PROJECT_DIR at spawn, so it is deliberately
   not pinned — config-cli.ts).
B. cursor: {mcp_servers:{Monet:{...}}} with MONET_PROJECT_DIR pinned.
C. hermes: {mcp_servers:{monet:{...}}}.
D. openclaw: raw server object {command,args,env} (no mcpServers/mcp_servers).
E. --yaml: YAML text with `mcpServers:` + `command: monet`.
F. -o <file>: writes the file, prints "Configuration written to".
G. identity overrides: MONET_CALLER_ID / MONET_PROJECT_ID pinned into env.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import run_cli

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


STORE = "/tmp/monet-e2e-config-store"


def load_json(out):
    try:
        return json.loads(out)
    except Exception:
        return None


def main():
    base_env = {"MONET_STORAGE_DIR": STORE}

    # A. default (claude-code)
    rc, out, err = run_cli(["config"], env_extra=base_env)
    cfg = load_json(out)
    check("config_default_rc0_json", rc == 0 and cfg is not None, f"rc={rc}")
    if cfg:
        server = cfg.get("mcpServers", {}).get("monet", {})
        check("config_claude_command", server.get("command") == "monet", str(server.get("command")))
        check("config_claude_args", server.get("args") == ["start"], str(server.get("args")))
        env = server.get("env", {})
        check("config_claude_storage_dir", env.get("MONET_STORAGE_DIR") == STORE,
              str(env.get("MONET_STORAGE_DIR")))
        check("config_claude_no_project_dir", "MONET_PROJECT_DIR" not in env, str(sorted(env.keys())))

    # B. cursor
    rc, out, err = run_cli(["config", "--agent", "cursor"], env_extra=base_env)
    cfg = load_json(out) or {}
    cur = cfg.get("mcp_servers", {}).get("Monet", {})
    check("config_cursor_shape", rc == 0 and bool(cur), f"rc={rc}")
    check("config_cursor_project_dir_pinned", bool(cur.get("env", {}).get("MONET_PROJECT_DIR")),
          str(cur.get("env", {}).get("MONET_PROJECT_DIR")))

    # C. hermes
    rc, out, err = run_cli(["config", "--agent", "hermes"], env_extra=base_env)
    cfg = load_json(out) or {}
    check("config_hermes_shape", rc == 0 and "monet" in cfg.get("mcp_servers", {}), f"rc={rc}")

    # D. openclaw (raw server object, no wrapper)
    rc, out, err = run_cli(["config", "--agent", "openclaw"], env_extra=base_env)
    cfg = load_json(out) or {}
    check("config_openclaw_raw",
          rc == 0 and cfg.get("command") == "monet" and "mcpServers" not in cfg and "mcp_servers" not in cfg,
          f"rc={rc} keys={sorted(cfg.keys()) if cfg else 'parse-fail'}")

    # E. yaml
    rc, out, err = run_cli(["config", "--yaml"], env_extra=base_env)
    check("config_yaml", rc == 0 and "mcpServers:" in out and "command: monet" in out, f"rc={rc}")

    # F. -o <file>
    with tempfile.TemporaryDirectory() as td:
        outfile = os.path.join(td, "monet.json")
        rc, out, err = run_cli(["config", "-o", outfile], env_extra=base_env)
        wrote = os.path.exists(outfile)
        check("config_output_file_written", rc == 0 and wrote, f"rc={rc} wrote={wrote}")
        check("config_output_printed", "Configuration written to" in out, out.strip())

    # G. identity overrides pinned
    idenv = {"MONET_STORAGE_DIR": STORE, "MONET_CALLER_ID": "e2e-caller", "MONET_PROJECT_ID": "e2e-project"}
    rc, out, err = run_cli(["config"], env_extra=idenv)
    cfg = load_json(out) or {}
    env = cfg.get("mcpServers", {}).get("monet", {}).get("env", {})
    check("config_identity_caller_pinned", env.get("MONET_CALLER_ID") == "e2e-caller",
          str(env.get("MONET_CALLER_ID")))
    check("config_identity_project_pinned", env.get("MONET_PROJECT_ID") == "e2e-project",
          str(env.get("MONET_PROJECT_ID")))

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
