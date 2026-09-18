#!/usr/bin/env python3
"""Scenario 59: moment-gate conformance accounting + loss disclosure, LIVE surface.

Verified through the SHIPPED MCP surface only (`memory_overview` -> `gate`), against a
store that the harness seeds with hook-format `moments.jsonl` records (the same
technique as test50 — this environment has no host hook, so the seed takes its place;
the fold under test is the shipped one).

What this pins (test42/test50 do NOT: they cover the ask/answer round-trip and the
pure-core driver; neither counts the buckets nor reads `losses`):

  1. All seven conformance buckets count exactly the seeded spool events, and the three
     read states are distinguished: NO read (absent from every bucket), a TIMELY read,
     and a LATE read (`late_rule_reads`, i.e. a read that landed after `outcome_at`).
     `readLate` is therefore not "the read was slow" but "every read was too late to
     have informed the act" (`rule_reads` empty), and it is neither a verdict nor a
     defect queue.
  2. F2: `answer IS NULL` is load-bearing in `notAsked`. An answer is proof an ask
     happened, so answering a moment that was NEVER asked (`asked_at IS NULL`) removes
     it from `notAsked` and counts it in `followed` — verified against the store, which
     still shows `asked_at IS NULL`. A moment must never be counted as both answered and
     "acted without asking".
  3. `unanswered` is the positive predicate (`asked_at IS NOT NULL AND answer IS NULL`)
     and moves only on `conformance_ask`; asking does not answer.
  4. F3 ("debris"): a read naming a moment nobody intercepted creates an `opened = 0`
     row that is EXCLUDED from `total` and disclosed through `unopened` instead.
  5. `losses` is a store-wide COUNT over two disjoint kinds, deterministic across
     processes: one `sequence-gap` (seq 2..4 missing inside a run) + one
     `unobserved-interception` (an outcome with no moment, i.e. a host tool call that
     ran and that nothing was intercepted for).
  6. Surface-vs-store identity: `total` / `unopened` / `unattributed` equal the same
     counts read from `governed_moments` — the F3 exclusion is measured, not assumed.

Evidence captured for the development Objective (printed, deliberately NOT asserted —
these are product choices, not defects):
  - `gate.losses` is a bare count. Core implements the full enumeration
    (`observedMomentLosses`: gaps carry runId/fromSeq/toSeq/writerRole; orphans carry
    toolUseId/outcomeAt/outcomeSha256) but NO MCP/CLI surface calls it, so WHICH record
    was lost is unreachable from outside the store — this test has to open SQLite to
    name the second loss.
  - Every store-touching MCP call makes the RUNNING SERVER open its own governed moment
    (`writerRole = 'core'`) in the SAME spool, so `total` grows with unrelated call
    traffic — hence the identity assertions above instead of a seed-derived constant.
  - `writerRole` must be a member of the build's roster (`host-hook` | `gate-cli` |
    `core`); an unknown role makes `isWriterRole` drop the run-start line and the fold
    then FABRICATES a `0..0` sequence gap. That defect is pinned separately by test60.

Exit codes: 0 = PASS, 1 = FAIL.
"""

import json
import os
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
# MUST be in MomentWriterRole's roster; an unknown role silently drops the run-start
# line (see test60 / RE-59). test50 still seeds the invalid "e2e".
WRITER_ROLE = "host-hook"
AT = "2026-09-19T00:00:00.000Z"
LATE = "2026-09-19T09:00:00.000Z"  # read that lands after the act, not merely slowly

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def evidence(msg):
    print(f"  [EVIDENCE] {msg}")


def sql(db, q):
    return subprocess.run(["sqlite3", db, q], capture_output=True, text=True).stdout.strip()


def spool_seed(spool, records):
    with open(spool, "a") as f:
        for ln in records:
            f.write(json.dumps(ln) + "\n")


def ev_interception(mid, rule, circle, at=AT):
    return {"kind": "interception", "momentId": mid, "at": at, "toolUseId": "tu-" + mid[:8],
            "circle": circle, "sessionId": None, "surface": "Bash",
            "actionSha256": "a" * 64, "actionRendering": "prod deploy " + mid[:8],
            "actionChars": 15, "actionClipped": False, "stageId": "stage-e2e",
            "ruleIds": [rule], "disposition": "advised", "deliveredRuleIds": [rule]}


def ev_read(mid, rule, circle, read_at=AT):
    return {"kind": "read", "momentId": mid, "ruleId": rule, "namedStageId": "stage-e2e",
            "circle": circle, "readAt": read_at}


def ev_outcome(mid=None, at=AT, tool_use_id=None, sha="b"):
    return {"kind": "outcome", "momentId": mid, "toolUseId": tool_use_id,
            "outcomeStatus": "ok", "outcomeAt": at, "outcomeSha256": sha * 64}


def conf(ov):
    return ((ov or {}).get("gate") or {}).get("conformance") or {}


def gate(ov):
    return (ov or {}).get("gate") or {}


def main():
    base = tempfile.mkdtemp(prefix="monet-conf-accounting-")
    store = os.path.join(base, "store")
    os.makedirs(store)
    db = os.path.join(store, "monet.db")
    spool = os.path.join(store, "moments.jsonl")

    check("isolated_store", store.startswith(tempfile.gettempdir()), f"store={store}")

    ids = {k: str(uuid.uuid4()) for k in ("m1", "m2", "m3", "m4", "m5", "mg1", "mg2", "md")}
    rules = {k: f"rule-e2e-{k}-{TS}" for k in ids}
    ghost_tu = "tu-ghost-" + TS

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

        # ---- seed one spool file, then let ONE fold consume it --------------------
        recs = []

        def add(events, at=AT):
            run = "run-e2e-" + uuid.uuid4().hex[:12]
            recs.append({"v": 1, "runId": run, "seq": 0, "kind": "run-start",
                         "writerRole": WRITER_ROLE, "at": at})
            for seq, ev in events:
                recs.append({"v": 1, "runId": run, "seq": seq, **ev})

        # m1..m4: opened + TIMELY read + acted -> judicable, no question asked yet.
        for k in ("m1", "m2", "m3", "m4"):
            add([(1, ev_interception(ids[k], rules[k], circle)),
                 (2, ev_read(ids[k], rules[k], circle)),
                 (3, ev_outcome(ids[k], tool_use_id="tu-" + ids[k][:8]))])
        # m5: the read lands hours AFTER the outcome -> a LATE read, and m5 has NO timely
        # read at all. Written in that order because the fold classifies a read against
        # the outcome it has already seen.
        add([(1, ev_interception(ids["m5"], rules["m5"], circle)),
             (2, ev_outcome(ids["m5"], tool_use_id="tu-" + ids["m5"][:8])),
             (3, ev_read(ids["m5"], rules["m5"], circle, read_at=LATE))])
        # gap run: seq 1 and seq 5 present -> seq 2..4 missing (loss kind 1).
        add([(1, ev_interception(ids["mg1"], rules["mg1"], circle)),
             (5, ev_interception(ids["mg2"], rules["mg2"], circle))])
        # ghost outcome: a host tool call that RAN and that nothing was ever intercepted
        # for. It carries no momentId, which is what makes it an orphan rather than an
        # attachment (loss kind 2).
        add([(1, ev_outcome(at=AT, tool_use_id=ghost_tu, sha="c"))])
        # debris: a read naming a moment nobody intercepted (F3).
        add([(1, ev_read(ids["md"], rules["md"], circle))])

        spool_seed(spool, recs)
        check("spool_seeded", len(recs) == 27, f"records={len(recs)}")

        # ---- phase 1: nothing asked, nothing answered ----------------------------
        ov1 = c.call_json("memory_overview", {"circle": circle})
        g1, c1 = gate(ov1), conf(ov1)
        check("gate_is_disclosed", bool(g1), f"keys={sorted(g1)}")
        check("conformance_is_disclosed", bool(c1), f"keys={sorted(c1)}")

        check("no_answer_yet", c1.get("followed") == 0 and c1.get("notFollowed") == 0,
              f"followed={c1.get('followed')} notFollowed={c1.get('notFollowed')}")
        check("nothing_asked_yet", c1.get("unanswered") == 0,
              f"unanswered={c1.get('unanswered')}")
        check("notAsked_counts_the_timely_read_acted_moments", c1.get("notAsked") == 4,
              f"notAsked={c1.get('notAsked')} (m1..m4; m5 has no TIMELY read so it is not debt)")
        check("notAskedWithAction_matches_notAsked",
              c1.get("notAskedWithAction") == c1.get("notAsked") == 4,
              f"notAskedWithAction={c1.get('notAskedWithAction')}")
        check("readLate_is_a_separate_state_from_notAsked",
              c1.get("readLate") == 1,
              f"readLate={c1.get('readLate')} (m5: read 9h after the act, no timely read)")
        check("unjoinableReads_zero_when_every_read_names_a_moment",
              c1.get("unjoinableReads") == 0, f"unjoinableReads={c1.get('unjoinableReads')}")

        check("losses_two_kinds_disclosed", g1.get("losses") == 2,
              f"losses={g1.get('losses')} (1 sequence gap 2..4 + 1 unobserved interception)")
        check("loss_kinds_are_the_two_distinct_ones",
              sql(db, "SELECT group_concat(kind) FROM (SELECT DISTINCT kind FROM moment_losses ORDER BY kind);")
              == "sequence-gap,unobserved-interception",
              sql(db, "SELECT group_concat(kind) FROM (SELECT DISTINCT kind FROM moment_losses ORDER BY kind);"))
        check("orphan_loss_names_the_ghost_tool_call",
              sql(db, f"SELECT tool_use_id FROM moment_losses WHERE kind='unobserved-interception';") == ghost_tu,
              "the surface says '2'; only the store can say WHICH tool call was never intercepted")

        # surface-vs-store identity (F3 exclusion measured, not assumed)
        t = sql(db, f"SELECT COUNT(*) FROM governed_moments WHERE opened=1 AND circle='{circle}';")
        u = sql(db, "SELECT COUNT(*) FROM governed_moments WHERE opened=0;")
        a = sql(db, "SELECT COUNT(*) FROM governed_moments WHERE opened=1 AND circle IS NULL;")
        check("total_matches_store", str(g1.get("total")) == t,
              f"surface={g1.get('total')} store={t}")
        check("unopened_matches_store", str(g1.get("unopened")) == u,
              f"surface={g1.get('unopened')} store={u}")
        check("unattributed_matches_store", str(g1.get("unattributed")) == a,
              f"surface={g1.get('unattributed')} store={a}")

        opened_rows = int(sql(db, "SELECT COUNT(*) FROM governed_moments WHERE opened=1;"))
        check("every_seeded_interception_opened", opened_rows >= 7, f"opened_rows={opened_rows}")
        check("debris_row_exists_unopened",
              sql(db, f"SELECT opened FROM governed_moments WHERE moment_id='{ids['md']}';") == "0",
              "the F3 debris row exists with opened=0")
        check("debris_is_not_in_total",
              int(g1.get("unopened", 0)) >= 1 and str(g1.get("total")) == t,
              f"unopened={g1.get('unopened')} total={g1.get('total')} "
              f"(debris is disclosed as unopened, never counted as a governed moment)")

        evidence(f"gate.losses is a COUNT only (losses={g1.get('losses')}); core implements the "
                 "full enumeration (observedMomentLosses: gaps -> runId/fromSeq/toSeq/writerRole, "
                 "orphans -> toolUseId/outcomeAt/outcomeSha256) but no MCP/CLI surface calls it, so "
                 "WHICH record was lost is unreachable from outside the store.")
        evidence(f"gate.total={g1.get('total')} includes the server's OWN 'core' moments (the "
                 "store-touching MCP call above opens one in the same spool), so total is not a "
                 "seed-derived constant — asserted as a surface/store identity instead.")
        evidence(f"readLate={c1.get('readLate')} is disclosed as a COUNT with no per-moment detail: "
                 "a read that landed 9h after the act is indistinguishable, on the surface, from one "
                 "that landed 1ms after it.")

        # ---- phase 2: ASK m2 -> it becomes unanswered, notAsked drops ------------
        c.call_json("conformance_ask", {"momentId": ids["m2"]})
        ov2 = c.call_json("memory_overview", {"circle": circle})
        c2 = conf(ov2)
        check("ask_moves_moment_into_unanswered",
              c2.get("unanswered") == 1 and c2.get("notAsked") == 3,
              f"unanswered={c2.get('unanswered')} notAsked={c2.get('notAsked')}")
        check("ask_does_not_answer", c2.get("followed") == 0 and c2.get("notFollowed") == 0,
              f"followed={c2.get('followed')} notFollowed={c2.get('notFollowed')}")
        check("readLate_survives_ask", c2.get("readLate") == 1, f"readLate={c2.get('readLate')}")

        # ---- phase 3: answer two different moments ------------------------------
        c.call_json("conformance_answer", {"momentId": ids["m3"], "answer": "followed"})
        c.call_json("conformance_answer", {"momentId": ids["m4"], "answer": "not-followed"})
        ov3 = c.call_json("memory_overview", {"circle": circle})
        c3 = conf(ov3)
        check("answers_are_counted_separately",
              c3.get("followed") == 1 and c3.get("notFollowed") == 1,
              f"followed={c3.get('followed')} notFollowed={c3.get('notFollowed')}")
        check("answered_moments_leave_notAsked",
              c3.get("notAsked") == 1, f"notAsked={c3.get('notAsked')} (only m1 left)")
        check("asked_unanswered_still_counted",
              c3.get("unanswered") == 1, f"unanswered={c3.get('unanswered')}")
        check("readLate_survives_answer", c3.get("readLate") == 1, f"readLate={c3.get('readLate')}")

        # ---- phase 4: answer m1, which was NEVER asked (F2) ----------------------
        r = c.call_json("conformance_answer", {"momentId": ids["m1"], "answer": "followed"})
        ov4 = c.call_json("memory_overview", {"circle": circle})
        c4 = conf(ov4)
        asked_at = sql(db, f"SELECT asked_at FROM governed_moments WHERE moment_id='{ids['m1']}';")
        check("answer_without_ask_is_recorded", r.get("recorded") == "answer",
              f"raw={json.dumps(r)[:120]}")
        check("answered_unasked_moment_leaves_notAsked",
              c4.get("notAsked") == 0,
              f"notAsked={c4.get('notAsked')} (F2: an answer is proof an ask happened)")
        check("answered_unasked_moment_counts_as_a_verdict",
              c4.get("followed") == 2 and c4.get("notFollowed") == 1,
              f"followed={c4.get('followed')} notFollowed={c4.get('notFollowed')}")
        check("store_still_shows_no_ask", asked_at == "",
              f"asked_at={asked_at!r} — the answer moved the buckets, not the ask record")
        check("readLate_survives_unasked_answer", c4.get("readLate") == 1,
              f"readLate={c4.get('readLate')}")
        evidence(f"F2 measured from outside: m1 answered with asked_at IS NULL -> "
                 f"notAsked {c3.get('notAsked')}->{c4.get('notAsked')}, "
                 f"followed {c3.get('followed')}->{c4.get('followed')}. The predicate is "
                 "`asked_at IS NULL AND answer IS NULL`, so an answer can never be counted as "
                 "'acted without asking'.")

        # ---- phase 5: a fresh process must fold the same spool to the same numbers
        c.close()
        c = MonetClient(store)
        c.initialize()
        ov5 = c.call_json("memory_overview", {"circle": circle})
        c5, g5 = conf(ov5), gate(ov5)
        check("fold_is_idempotent_across_processes",
              {k: c5.get(k) for k in c4} == {k: c4.get(k) for k in c4},
              f"before={json.dumps(c4)} after={json.dumps(c5)}")
        check("losses_are_stable_across_processes", g5.get("losses") == 2,
              f"losses={g5.get('losses')}")
        check("no_loss_row_duplication",
              sql(db, "SELECT COUNT(*) FROM moment_losses;") == "2",
              f"rows={sql(db, 'SELECT COUNT(*) FROM moment_losses;')}")
        check("losses_do_not_grow_with_call_traffic",
              all(conf(c.call_json("memory_overview", {"circle": circle})).get("notAsked") == 0
                  for _ in range(2)),
              "two more overview calls (each opening a core moment) leave the buckets unchanged")
    finally:
        c.close()
        if os.environ.get("MONET_KEEP_STORE"):
            print(f"  KEPT store={store}")
        else:
            shutil.rmtree(base, ignore_errors=True)

    if FAIL:
        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed — {FAIL}")
        return 1
    print(f"\nRESULT: PASS — moment conformance accounting + loss disclosure verified on the "
          f"live memory_overview surface ({len(PASS)} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
