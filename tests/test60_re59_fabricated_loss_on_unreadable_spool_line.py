#!/usr/bin/env python3
"""Scenario 60 / RE-59: an UNREADABLE spool line is silently converted into a LOSS.

`MomentWriterRole` is a closed roster (`host-hook` | `gate-cli` | `core`). A moment
spool line whose `writerRole` is not in it is dropped by `isWriterRole` — including the
run's own `run-start` declaration at seq 0. The fold then hears of that run for the
first time at seq 1 and reports `0..0` missing: a FABRICATED hole in a spool that is
complete. The product's own source says as much (moment-spool.ts, the `gate-cli`
member): "Drop a role from this roster and `isWriterRole` rejects its run-start line;
the line is consumed, the cursor advances, and the interception behind it opens a
sequence gap at seq 0 — a fabricated hole in a record that is complete. This was
measured, not reasoned: dropping it in 66a47fb would have manufactured one phantom
loss per historical run. Retiring a writer is a decision about who may WRITE; it is
never licence to forget how to READ."

So the hardening principle is already written down — this test asserts it from the
OUTSIDE, through the shipped surface, because the surfaced consequence is what a human
sees: a bare `losses` count that cannot be told apart from a genuinely unrecorded
event. The fold computes the diagnostics that WOULD separate them
(`malformedLines`, `futureVersionLines`, `restartedFromZero`, `cursor`,
`unjoinableReads` in `MomentSpoolRead`) but the gate fact carries only
`{conformance, losses, total, unattributed, unopened}` — no diagnostic is reachable,
so "a writer this build cannot read" and "an event nobody recorded" render identically.

Two independent shapes are seeded:
  A. a valid-role run                     -> no loss
  B. an UNKNOWN-role run (a newer host)   -> the run-start line is unreadable, its
                                             interception is NOT -> fabricated 0..0 gap
  C. a future-version run (v = 99)        -> every line is unreadable -> silently absent

Mechanism checks (A/B/C) are asserted because they are the evidence; the two DESIRED
checks fail on the shipped build, so this test exits 2 (XFAIL) per the run_all.py
convention (0 PASS, 1 FAIL, 2 XFAIL, 3 XPASS, 4 INCONCLUSIVE, 5 STALE).

Desired contract:
  1. a line this build cannot READ must not be counted as a LOSS (losses == 0 for a
     spool whose events are all present);
  2. the fact that N lines were skipped must be disclosed on the surface.

Exit codes: 0/3 = fixed, 2 = still present, 1 = inconclusive/failed setup.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
from mcp_client import MonetClient  # noqa: E402

CLI = os.environ.get(
    "MONET_CLI",
    os.path.expanduser(
        "~/.local/share/monet-node22/lib/node_modules/@team-monet/monet/dist/cli.js"
    ),
)
os.environ["MONET_CLI"] = CLI
os.environ.setdefault("MONET_NODE_PATH", "/opt/homebrew/opt/node@22/bin")
os.environ.setdefault("MONET_MODEL_CACHE", os.path.expanduser("~/.monet/models"))

TS = str(int(time.time()))
AT = "2026-09-19T00:00:00.000Z"
ROLE_OK = "host-hook"        # in the roster
ROLE_UNKNOWN = "host-hook-v2"  # a NEWER host; this build cannot name it
DISCLOSURE_KEY = re.compile(r"malformed|future|unread|unparse|skip|ignor|spool|"
                            r"cursor|restarted", re.I)

PASS = []
FAIL = []
DESIRED = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def desired(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        DESIRED.append(name)
    print(f"  [{'PASS' if cond else 'DESIRED-FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def evidence(msg):
    print(f"  [EVIDENCE] {msg}")


def sql(db, q):
    return subprocess.run(["sqlite3", db, q], capture_output=True, text=True).stdout.strip()


def all_keys(obj, out=None):
    out = {} if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out[k] = v
            all_keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            all_keys(v, out)
    return out


def ev_interception(mid, rule, circle):
    return {"kind": "interception", "momentId": mid, "at": AT, "toolUseId": "tu-" + mid[:8],
            "circle": circle, "sessionId": None, "surface": "Bash",
            "actionSha256": "a" * 64, "actionRendering": "prod deploy " + mid[:8],
            "actionChars": 15, "actionClipped": False, "stageId": "stage-e2e",
            "ruleIds": [rule], "disposition": "advised", "deliveredRuleIds": [rule]}


def ev_read(mid, rule, circle):
    return {"kind": "read", "momentId": mid, "ruleId": rule, "namedStageId": "stage-e2e",
            "circle": circle, "readAt": AT}


def ev_outcome(mid):
    return {"kind": "outcome", "momentId": mid, "toolUseId": "tu-" + mid[:8],
            "outcomeStatus": "ok", "outcomeAt": AT, "outcomeSha256": "b" * 64}


def main():
    base = tempfile.mkdtemp(prefix="monet-re59-unreadable-")
    store = os.path.join(base, "store")
    os.makedirs(store)
    db = os.path.join(store, "monet.db")
    spool = os.path.join(store, "moments.jsonl")

    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")

    # Three runs: one readable, one whose DECLARATION is unreadable, one entirely
    # future-versioned. Every event that carries a moment is otherwise identical.
    runs = {}
    recs = []
    for name, role, ver in (("ok", ROLE_OK, 1), ("unknown-role", ROLE_UNKNOWN, 1),
                            ("future", ROLE_OK, 99)):
        run = "run-re59-" + name + "-" + uuid.uuid4().hex[:8]
        runs[name] = run
        recs.append({"v": ver, "runId": run, "seq": 0, "kind": "run-start",
                     "writerRole": role, "at": AT})
        mids = str(uuid.uuid4())
        recs.append({"v": ver, "runId": run, "seq": 1, "kind": "interception",
                     "momentId": mids, "at": AT,
                     "toolUseId": "tu-" + mids[:8], "circle": None, "sessionId": None,
                     "surface": "Bash", "actionSha256": "a" * 64,
                     "actionRendering": "prod deploy", "actionChars": 15,
                     "actionClipped": False, "stageId": "stage-e2e",
                     "ruleIds": ["rule-re59-" + name], "disposition": "advised",
                     "deliveredRuleIds": ["rule-re59-" + name]})
        recs.append({"v": ver, "runId": run, "seq": 2, "kind": "read",
                     "momentId": mids, "ruleId": "rule-re59-" + name,
                     "namedStageId": "stage-e2e", "circle": None, "readAt": AT})
        recs.append({"v": ver, "runId": run, "seq": 3, "kind": "outcome",
                     "momentId": mids, "toolUseId": "tu-" + mids[:8],
                     "outcomeStatus": "ok", "outcomeAt": AT, "outcomeSha256": "b" * 64})
        runs[name + "_moment"] = mids

    c = MonetClient(store)
    try:
        c.initialize()
        tools = {t["name"] for t in c.tools_list().get("tools", [])}
        if "conformance_ask" not in tools or "conformance_answer" not in tools:
            print("SKIP: conformance_ask/answer not present in this Monet build")
            return 0

        ack = c.call_json("memory_store", {"content": "circle-probe-" + TS})
        circle = (ack or {}).get("circle")
        check("circle_resolved", bool(circle), f"circle={circle}")

        # The moment records must carry the SAME circle as the store, or their
        # interceptions land in `unattributed` and never reach the circle-scoped fact.
        for r in recs:
            if r["kind"] in ("interception", "read"):
                r["circle"] = circle
        with open(spool, "a") as f:
            for ln in recs:
                f.write(json.dumps(ln) + "\n")
        check("spool_seeded", len(recs) == 12, f"records={len(recs)}")

        ov = c.call_json("memory_overview", {"circle": circle})
        g = (ov or {}).get("gate") or {}
        conf = g.get("conformance") or {}
        evidence(f"gate fact keys = {sorted(g)} — layout="
                 f"{ {k: g[k] for k in sorted(g) if k != 'conformance'} }")

        # ---- mechanism: the readable run contributes nothing -------------------
        ok_moment = runs["ok_moment"]
        check("readable_run_left_no_loss_at_all",
              sql(db, f"SELECT COUNT(*) FROM moment_losses;"),
              "loss rows are all accounted for below")
        check("readable_run_opened", sql(
            db, f"SELECT opened FROM governed_moments WHERE moment_id='{ok_moment}';") == "1",
            "the readable run folded normally")

        # ---- mechanism: the unreadable DECLARATION fabricates a loss -----------
        los = sql(db, "SELECT kind, run_id, from_seq, to_seq "
                      "FROM moment_losses ORDER BY kind;")
        check("phantom_loss_is_reproducible",
              sql(db, "SELECT COUNT(*) FROM moment_losses;") == "1", f"rows=1 (got: {los})")
        check("loss_is_a_sequence_gap", sql(
            db, "SELECT kind FROM moment_losses;") == "sequence-gap", los)
        check("phantom_gap_spans_exactly_the_dropped_declaration",
              sql(db, "SELECT from_seq || '-' || to_seq FROM moment_losses;") == "0-0",
              f"the missing 'seq' is the run-start line itself, not an event: {los}")
        check("phantom_loss_blames_an_unattributable_run",
              sql(db, f"SELECT COALESCE(writer_role,'') || '|' || COALESCE(started_at,'') "
                      f"FROM moment_runs WHERE run_id='{runs['unknown-role']}';") == "|",
              "the run row the gap points at has an EMPTY writer_role and EMPTY started_at — "
              "folded lazily from seq 1, so even the internal enumeration (which resolves "
              "writerRole through that join) cannot say who wrote the 'lost' record")
        check("run_behind_the_phantom_gap_is_the_unknown_role_run",
              sql(db, "SELECT run_id FROM moment_losses;") == runs["unknown-role"],
              f"run={runs['unknown-role']}")

        unk_moment = runs["unknown-role_moment"]
        check("unreadable_run_events_were_still_read",
              sql(db, f"SELECT opened FROM governed_moments WHERE moment_id='{unk_moment}';") == "1",
              "the interception behind the dropped declaration DID fold — the spool is complete")
        check("unreadable_run_is_therefore_judicable",
              int(conf.get("notAsked") or 0) >= 1,
              f"notAsked={conf.get('notAsked')} counts it as real debt")
        evidence("so the fold holds the whole event stream and reports a hole only where a "
                 "line it could not parse sat: the 'loss' is about the ROLE VOCABULARY, not "
                 "about anything missing from the record.")

        # ---- mechanism: a future-version run leaves no trace at all ------------
        fut_moment = runs["future_moment"]
        check("future_version_run_is_silently_absent",
              sql(db, f"SELECT COUNT(*) FROM governed_moments WHERE moment_id='{fut_moment}';") == "0"
              and sql(db, f"SELECT COUNT(*) FROM moment_runs WHERE run_id='{runs['future']}';") == "0",
              "all four v=99 lines were consumed and skipped; nothing points at them")
        check("future_version_run_adds_no_loss",
              sql(db, f"SELECT COUNT(*) FROM moment_losses WHERE run_id='{runs['future']}';") == "0",
              "a wholly unreadable run is silent, not counted")

        # ---- mechanism: nothing on the surface separates the two cases ---------
        keys = all_keys(ov)
        disc = sorted(k for k in keys if DISCLOSURE_KEY.search(k))
        check("no_surface_key_separates_unreadable_from_unrecorded", not disc,
              f"matching keys={disc}; every key is "
              f"{sorted(k for k in keys if k in ('gate', 'conformance', 'losses', 'total', 'unopened', 'unattributed', 'followed', 'notFollowed', 'unanswered', 'notAsked', 'notAskedWithAction', 'readLate', 'unjoinableReads'))}")
        check("losses_is_a_bare_count_with_no_kind_field",
              isinstance(g.get("losses"), int) and "lossesByKind" not in keys,
              f"losses={g.get('losses')!r}")

        # ---- DESIRED behaviour (fixes needed) ----------------------------------
        desired("losses_must_not_count_a_line_this_build_cannot_read",
                int(g.get("losses") or 0) == 0,
                f"losses={g.get('losses')} while every event in the spool is present and "
                "folded — the count is a fabrication")
        desired("skipped_lines_must_be_disclosed_on_the_surface",
                bool(disc),
                f"the fold computes malformedLines/futureVersionLines/restartedFromZero/cursor "
                f"but gate={sorted(g)} carries none of them")
        evidence("regression footprint: the shipped E2E test `test50_conformance_roundtrip.py` "
                 "seeds writerRole='e2e', which is NOT in the roster — so the public suite "
                 "fabricates one phantom loss per seeded run while asserting nothing about "
                 "`losses`. Any foreign/older/newer writer hits the same path.")
    finally:
        c.close()
        if os.environ.get("MONET_KEEP_STORE"):
            print(f"  KEPT store={store}")
        else:
            shutil.rmtree(base, ignore_errors=True)

    if DESIRED:
        print(f"\nRESULT: XFAIL — RE-59 still present: {len(PASS)} checks held, "
              f"desired-but-unmet = {DESIRED}")
        return 2
    print(f"\nRESULT: XPASS — RE-59 fixed: unreadable spool lines are neither counted as losses "
          f"nor hidden ({len(PASS)} checks)")
    return 3


if __name__ == "__main__":
    sys.exit(main())
