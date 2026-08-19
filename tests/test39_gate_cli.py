#!/usr/bin/env python3
"""Scenario (CLI surface): `monet gate` — the offline gate mirror evaluator (test39).

The MCP stdio surface (`monet start`), `monet config` (test35) and `monet install`
(test37) are the only paths exercised so far; `monet gate` — the offline hook
binary that reads the gate mirror straight off disk with NO store, NO network —
sat at 6.9% source line coverage (gate-cli.ts, 1078 lines), the largest remaining
non-deprecated CLI gap (coverage-gaps.md). This scenario drives `monet gate`
through the same process boundary (run_cli) with hand-built mirror fixtures and
pins its five-outcome exit-code contract plus the gate journal and fail-open policy.

CONTRACT UNDER TEST (gate-cli.ts — five outcomes, five exit codes):
  USAGE_ERROR  exit 1  (no/ambiguous context, unprefixed context, bad --tool,
                        --circle '*', excess positionals)
  SILENCE      exit 0  (no stage matched)
  STAGE_HIT    exit 10 (a stage matched with no live rules bound)
  ADVISORY     exit 20 (only advisory rules matched)
  BLOCKING     exit 30 (a blocking rule matched)
  OVERFLOW     exit 40 (action context exceeds the refusal threshold; ask, never allow)
  FAIL-OPEN    exit 0  (missing/malformed mirror — stderr carries the
                        GATE_FAIL_OPEN_MARKER, distinct from genuine silence)

STABILITY ACROSS SHIPPED / MAIN: the installed binary is 1.6.3 (gate payload is
`text — reason`); the coverage bundle is built from the source clone at `main`,
which ships #49/#58 (identity-only payload: `Blocked by a Monet rule — N ...`,
stage_lookup instruction). The five EXIT CODES and the JOURNAL record
(`disposition`, `ruleIds`, `claimType`, `gateExitCode`) are IDENTICAL across both,
so this test asserts on those plus stdout-emptiness/non-emptiness — never on the
verbatim payload text (which differs by release). This keeps the suite green
against both the regular installed runs and the coverage-measurement bundle.

Journal: every invocation opens+closes a gate-journal event (appended line stream
at `getGateJournalPath()` = MONET_STORAGE_DIR/gate-journal.jsonl). Verdict records
carry disposition + claimType ('parsed' — a mirror answer, not a live store read)
+ circle + stage/rule ids + gateExitCode. Each arm runs in a FRESH store dir so
its journal is correlated unambiguously.

Isolation (GR-01 + the HOME/MONET_STORAGE_DIR redirect technique from test37):
  - MONET_STORAGE_DIR -> temp dir (isolates the gate journal DB)
  - HOME              -> temp dir
  - --circle + --mirror passed explicitly on every armed invocation so circle
    resolution short-circuits at the flag rung (no git shell-out) and the mirror
    path is always nameable.
  - The mirror fixture is written to a temp dir, never the shared test store.
  - cwd stays the parent ~/.monet-test; nothing here opens a store or loads the
    embedder, so MONET_MODEL_CACHE is not needed.

MIRROR SCHEMA (GATE_MIRROR_FORMAT=4): generation/generatedAt/format/entries[]/
stages[]/circleAliases[]/circles[] + optional sha256 checksum over the canonical
JSON serialization (JSON.stringify(rest,null,2)). The checksum is computed with
the EXACT JS recipe via a node one-liner (JSON.stringify separators differ from
Python's json.dumps defaults — verified 2026-08-19), so a valid-checksum mirror
passes readGateMirrorFile and a tampered checksum fails as `malformed`.
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import run_cli, NODE_PATH

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def node_checksum(mirror):
    """sha256 of the canonical JS JSON.stringify(rest, null, 2) serialization."""
    payload = json.dumps({k: v for k, v in mirror.items() if k != "checksum"})
    node = os.path.join(NODE_PATH, "node")
    script = ("const m=" + payload +
              ";const{checksum,...rest}=m;process.stdout.write("
              "require('crypto').createHash('sha256').update("
              "JSON.stringify(rest,null,2)).digest('hex'))")
    r = subprocess.run([node, "-e", script], capture_output=True, text=True)
    return r.stdout.strip()


def write_mirror(path, mirror):
    mirror["checksum"] = node_checksum(mirror)
    with open(path, "w") as f:
        json.dump(mirror, f, indent=2, separators=(", ", ": "))


def base_mirror():
    return {
        "format": 4,
        "generation": 3,
        "generatedAt": 1750000000000,
        "entries": [
            {"conceptId": "c-block", "stageId": "s-gitpush", "severity": "blocking",
             "circle": "*", "text": "Never force-push to main.", "scope": "domain",
             "reason": "a rewritten history cannot be recovered"},
            {"conceptId": "c-adv", "stageId": "s-tf", "severity": "advisory",
             "circle": "acme", "text": "Always run plan first.", "scope": "domain",
             "reason": "plan then apply"},
            {"conceptId": "c-agent", "stageId": "s-tf", "severity": "advisory",
             "circle": "acme", "text": "for pro model only", "scope": "agent",
             "modelTag": "pro", "reason": "pro"},
        ],
        "stages": [
            {"id": "s-gitpush", "name": "git force push",
             "triggerPatterns": json.dumps([{"tool": "bash", "tokens": ["git", "push", "--force"]}])},
            {"id": "s-tf", "name": "terraform apply",
             "triggerPatterns": json.dumps([{"tool": "bash", "tokens": ["terraform", "apply"]}])},
            {"id": "s-empty", "name": "empty stage",
             "triggerPatterns": json.dumps([{"tool": "bash", "tokens": ["frobnicate", "--hard"]}])},
        ],
        "circleAliases": [{"from": "oldacme", "to": "acme"}],
        "circles": ["acme", "oldacme"],
    }


def journal_records(path):
    """All phase==disposition record dicts (arrival lines skipped)."""
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        ev = json.loads(line)
        if ev.get("phase") == "disposition":
            out.append(ev)
    return out


def gate(args, mirror, stdin=None, env_extra=None):
    """Run one `monet gate` arm in a FRESH store; return (rc, stdout, records)."""
    td = tempfile.mkdtemp(prefix="e2e-gate-arm-")
    store = os.path.join(td, "store")
    os.makedirs(store)
    env = {"MONET_STORAGE_DIR": store, "HOME": os.path.join(td, "home")}
    if env_extra:
        env.update(env_extra)
    rc, out, err = run_cli(["gate", *args, "--mirror", mirror],
                           env_extra=env, stdin=stdin, timeout=60)
    return rc, out, err, journal_records(os.path.join(store, "gate-journal.jsonl"))


def disps(records):
    return [r.get("disposition") for r in records]


def rule_ids(records):
    return [r.get("ruleIds") for r in records if r.get("disposition") in ("deny", "advisory")]


def main():
    tdir = tempfile.mkdtemp(prefix="e2e-gate-")
    mirror = os.path.join(tdir, "gate-mirror.json")
    write_mirror(mirror, base_mirror())

    # ── A. five outcomes, five exit codes (valid mirror) ──────────────────────
    rc, out, err, rec = gate(["Bash:git push --force", "--circle", "acme"], mirror)
    check("A_blocking_rc30", rc == 30, f"rc={rc}")
    check("A_blocking_stdout_nonempty", out.strip() != "", "out empty")
    check("A_blocking_journal_deny", disps(rec) == ["deny"], str(disps(rec)))
    check("A_blocking_rule_id", rule_ids(rec) == [["c-block"]], str(rule_ids(rec)))
    check("A_blocking_gateExit", rec and rec[0].get("gateExitCode") == 30,
          str(rec[0].get("gateExitCode") if rec else None))

    rc, out, err, rec = gate(["Bash:terraform apply", "--circle", "acme"], mirror)
    check("A_advisory_rc20", rc == 20, f"rc={rc}")
    check("A_advisory_stdout_nonempty", out.strip() != "", "out empty")
    check("A_advisory_journal", disps(rec) == ["advisory"], str(disps(rec)))

    rc, out, err, rec = gate(["Bash:frobnicate --hard", "--circle", "acme"], mirror)
    check("A_no_rules_rc10", rc == 10, f"rc={rc}")
    check("A_no_rules_journal", disps(rec) == ["stage-hit-no-rules"], str(disps(rec)))
    check("A_no_rules_empty_stdout", out.strip() == "", "out non-empty")

    rc, out, err, rec = gate(["Bash:echo hi", "--circle", "acme"], mirror)
    check("A_silence_rc0", rc == 0, f"rc={rc}")
    check("A_silence_empty_stdout", out.strip() == "", out.strip()[:60])
    check("A_silence_no_failopen", "failing OPEN" not in err, err.strip()[:80])
    check("A_silence_journal", disps(rec) == ["silent"], str(disps(rec)))

    # ── B. circle alias resolution (query oldacme -> rule bound at acme) ──────
    rc, out, err, rec = gate(["Bash:terraform apply", "--circle", "oldacme"], mirror)
    check("B_alias_rc20", rc == 20, f"rc={rc}")
    check("B_alias_delivers_rule", rule_ids(rec) == [["c-adv", "c-agent"]], str(rule_ids(rec)))
    check("B_alias_stderr", "mirror alias of oldacme" in err, err.strip()[:100])

    # ── C. model-tag scope filtering (agent rule) ─────────────────────────────
    # No runtime tag (filter off) -> domain + agent rules both delivered
    rc, _, _, rec = gate(["Bash:terraform apply", "--circle", "acme"], mirror)
    check("C_notag_both_rules", rule_ids(rec) == [["c-adv", "c-agent"]], str(rule_ids(rec)))
    # Runtime tag mismatch -> agent rule dropped, only domain advisory remains
    rc, _, _, rec = gate(["Bash:terraform apply", "--circle", "acme"], mirror,
                        env_extra={"MONET_MODEL_TAG": "deepseek"})
    check("C_tagmismatch_drops_agent", rule_ids(rec) == [["c-adv"]], str(rule_ids(rec)))
    # Runtime tag match -> agent rule included
    rc, _, _, rec = gate(["Bash:terraform apply", "--circle", "acme"], mirror,
                        env_extra={"MONET_MODEL_TAG": "pro"})
    check("C_tagmatch_keeps_agent", rule_ids(rec) == [["c-adv", "c-agent"]], str(rule_ids(rec)))

    # ── D. Tool: prefix discipline ────────────────────────────────────────────
    rc, out, err, rec = gate(["git push --force", "--circle", "acme"], mirror)
    check("D_no_prefix_rc1", rc == 1, f"rc={rc}")
    check("D_no_prefix_msg", "has no 'Tool:' prefix" in err, err.strip()[:100])
    check("D_no_prefix_journal", [d for d in disps(rec) if d] == ["declined: unprefixed-context"],
          str(disps(rec)))

    rc, out, err, rec = gate(["git push --force", "--tool", "bash", "--circle", "acme"], mirror)
    check("D_tool_synth_rc30", rc == 30, f"rc={rc}")
    check("D_tool_synth_journal", disps(rec) == ["deny"], str(disps(rec)))

    rc, out, err, rec = gate(["git push --force", "--tool", "bad name", "--circle", "acme"], mirror)
    check("D_bad_tool_rc1", rc == 1, f"rc={rc}")
    check("D_bad_tool_msg", "not a valid tool name" in err, err.strip()[:100])

    rc, out, err, rec = gate(["Bash:git push --force", "--tool", "bash", "--circle", "acme"], mirror)
    check("D_tool_ignored_warning", "ignored" in err, err.strip()[:100])
    check("D_tool_ignored_still_eval", rc == 30, f"rc={rc}")

    # ── E. action-context sourcing ────────────────────────────────────────────
    rc, out, err, rec = gate([], mirror)
    check("E_no_context_rc1", rc == 1, f"rc={rc}")
    check("E_no_context_msg", "no action context given" in err, err.strip()[:90])

    rc, out, err, rec = gate(["--stdin", "--circle", "acme"], mirror, stdin="Bash:git push --force")
    check("E_stdin_rc30", rc == 30, f"rc={rc}")
    check("E_stdin_deny", disps(rec) == ["deny"], str(disps(rec)))

    rc, out, err, rec = gate(["Bash:git push --force", "--circle", "acme", "--stdin"],
                            mirror, stdin="x")
    check("E_both_sources_rc1", rc == 1, f"rc={rc}")
    check("E_both_sources_msg", "supply exactly one" in err, err.strip()[:100])

    # ── F. circle wildcard refusal ────────────────────────────────────────────
    rc, out, err, rec = gate(["Bash:git push --force", "--circle", "*"], mirror)
    check("F_wildcard_rc1", rc == 1, f"rc={rc}")
    check("F_wildcard_msg", "not a queryable circle" in err, err.strip()[:90])

    # ── G. checksum integrity (proved valid by the real verdicts above) ───────
    with open(mirror) as f:
        _m = json.load(f)
    check("G_check_present", isinstance(_m.get("checksum"), str) and len(_m["checksum"]) == 64,
          "len=%d" % len(_m.get("checksum") or ""))

    # tampered checksum -> malformed -> fail open
    bad = os.path.join(tdir, "bad-checksum.json")
    m2 = base_mirror()
    m2["checksum"] = "0" * 64  # wrong — write WITHOUT recomputing
    with open(bad, "w") as f:
        json.dump(m2, f, indent=2, separators=(", ", ": "))
    rc, out, err, rec = gate(["Bash:git push --force", "--circle", "acme"], bad)
    check("G_bad_checksum_rc0", rc == 0, f"rc={rc}")
    check("G_bad_checksum_failopen", "failing OPEN" in err and "checksum mismatch" in err, err.strip()[:120])
    check("G_bad_checksum_journal", [d for d in disps(rec) if d] == ["declined: mirror-unreadable"],
          str(disps(rec)))

    # ── H. missing / malformed mirror fail OPEN (exit 0 + marker) ─────────────
    rc, out, err, rec = gate(["Bash:git push --force", "--circle", "acme"],
                            os.path.join(tdir, "nope.json"))
    check("H_missing_rc0", rc == 0, f"rc={rc}")
    check("H_missing_failopen", "failing OPEN" in err and "no readable mirror" in err, err.strip()[:120])

    badjson = os.path.join(tdir, "bad.json")
    with open(badjson, "w") as f:
        f.write("{ nope !!")
    rc, out, err, rec = gate(["Bash:git push --force", "--circle", "acme"], badjson)
    check("H_badjson_rc0", rc == 0, f"rc={rc}")
    check("H_badjson_failopen", "failing OPEN" in err and "unusable" in err, err.strip()[:120])

    # wrong format number -> malformed -> fail open
    fmtbad = os.path.join(tdir, "fmt.json")
    m3 = base_mirror(); m3["format"] = 3
    write_mirror(fmtbad, m3)
    rc, out, err, rec = gate(["Bash:git push --force", "--circle", "acme"], fmtbad)
    check("H_badformat_rc0", rc == 0, f"rc={rc}")
    check("H_badformat_msg", "not the format this build reads" in err, err.strip()[:140])

    # entry naming an absent stageId -> malformed
    refbad = os.path.join(tdir, "ref.json")
    m4 = base_mirror(); m4["entries"][0]["stageId"] = "s-does-not-exist"
    write_mirror(refbad, m4)
    rc, out, err, rec = gate(["Bash:git push --force", "--circle", "acme"], refbad)
    check("H_badref_rc0", rc == 0, f"rc={rc}")
    check("H_badref_msg", "absent from stages[]" in err, err.strip()[:140])

    # ── I. overflow ask (exit 40) via --stdin ─────────────────────────────────
    big = "Bash:git push --force " + ("a" * 4300000)
    rc, out, err, rec = gate(["--stdin", "--circle", "acme"], mirror, stdin=big)
    check("I_overflow_rc40", rc == 40, f"rc={rc}")
    check("I_overflow_msg", "exceeds the refusal threshold" in err, err.strip()[:120])
    check("I_overflow_empty_stdout", out.strip() == "", out.strip()[:60])
    check("I_overflow_journal", disps(rec) == ["overflow"], str(disps(rec)))

    # ── J. claimType 'parsed' (mirror answer, not a live store read) ──────────
    rc, _, _, rec = gate(["Bash:terraform apply", "--circle", "acme"], mirror)
    check("J_claimType_parsed", rec and rec[0].get("claimType") == "parsed",
          str(rec[0].get("claimType") if rec else None))
    check("J_source_honest", rec and rec[0].get("claimType") != "source-observed", "wrong claimType")

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
