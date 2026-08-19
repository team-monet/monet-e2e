// Conformance-pass coverage driver (DIRECTION priority #1, monet-e2e#18).
//
// core/conformance.ts (33.1%, 169/510) is the largest non-deprecated core gap.
// It is PURE — no store, no clock, no I/O beyond importing gate-journal — and,
// critically, it has NO MCP/CLI surface: engine.runConformancePass() (the only
// caller of computeConformance) is not wired to any command or tool on either
// the shipped 1.6.3 binary or `main` (verified by grep; only the definition
// exists). So the only way to exercise it through the coverage bundle is a
// direct driver that calls the exported pure functions with crafted journal
// lines and asserts their exact outputs.
//
// This is the same reverse-engineering-verified semantics discipline as the
// MCP tests (the verdict decision table is pinned), just at function scope
// because no process boundary exposes it. Bundled from core SOURCE with an
// inline source map so V8 coverage remaps to packages/core/src/conformance.ts
// (and gate-journal.ts).
//
// All assertions are falsifiable (GR-07): each compares a real computed value
// to the expected one. Exit 0 on all pass, 1 on any FAIL.

import {
  computeConformance,
  tallyByRule,
  retirementCandidates,
  appendConformanceAnnotations,
} from "@conformance-src";

let pass = 0;
let fail = 0;

function check(name, cond, detail = "") {
  if (cond) {
    pass++;
    console.log(`  PASS ${name}` + (detail ? `  [${detail}]` : ""));
  } else {
    fail++;
    console.log(`  FAIL ${name}` + (detail ? `  [${detail}]` : ""));
  }
}

// helper: normalize an annotation to the fields we assert (drop key order
// dependence by comparing a stable projection)
const proj = (a) => JSON.stringify({
  fireEventId: a.fireEventId,
  ruleIds: a.ruleIds,
  verdictRuleIds: a.verdictRuleIds ?? null,
  verdict: a.verdict ?? null,
  claimType: a.claimType,
  retriedUnchanged: a.retriedUnchanged ?? null,
});

// ── 1. BLOCKING DENY, enforced, ONE rule, no retry ─────────────────────────
{
  const lines = [{
    phase: "disposition", id: "d1", disposition: "deny",
    ruleIds: ["r-force-push"], enforced: true,
    actionContext: "Bash:git push --force origin main",
  }];
  const ann = computeConformance(lines);
  check("1_deny_one_annotation", ann.length === 1, `len=${ann.length}`);
  check("1_deny_verdict_changed", ann[0].verdict === "changed", proj(ann[0]));
  check("1_deny_claim_source_observed", ann[0].claimType === "source-observed", proj(ann[0]));
  // single rule + no blockingRuleIds recorded -> verdictRuleIds ABSENT
  check("1_deny_no_scope_for_single_rule", ann[0].verdictRuleIds === undefined, proj(ann[0]));
  // no retry (only occurrence) -> retriedUnchanged false
  check("1_deny_not_retried", ann[0].retriedUnchanged === false, proj(ann[0]));
  check("1_deny_fire_event_id", ann[0].fireEventId === "d1", proj(ann[0]));
}

// ── 2. RETRY: same act (same actionContext), different chain, later ────────
{
  const lines = [
    { phase: "disposition", id: "dA", disposition: "deny", ruleIds: ["r1"],
      enforced: true, actionContext: "Bash:rm -rf /" },
    { phase: "disposition", id: "dB", disposition: "deny", ruleIds: ["r1"],
      enforced: true, actionContext: "Bash:rm -rf /" },
  ];
  const ann = computeConformance(lines);
  check("2_two_annotations", ann.length === 2, `len=${ann.length}`);
  // dA retried (same act appears again after it in a different chain)
  const a = ann.find((x) => x.fireEventId === "dA");
  const b = ann.find((x) => x.fireEventId === "dB");
  check("2_first_retried_true", a && a.retriedUnchanged === true, proj(a));
  check("2_second_retried_false", b && b.retriedUnchanged === false, proj(b));
  check("2_retry_reason_fought",
    a && a.reason.includes("was fought"), a ? a.reason : "no a");
}

// ── 3. MIXED-SEVERITY FIRE: blocking + advisory, blockingRuleIds recorded ──
{
  const lines = [{
    phase: "disposition", id: "m1", disposition: "deny",
    ruleIds: ["r-block", "r-adv"], enforced: true,
    blockingRuleIds: ["r-block"], actionContext: "Bash:terraform apply -auto-approve",
  }];
  const ann = computeConformance(lines);
  check("3_mixed_verdict_changed", ann[0].verdict === "changed", proj(ann[0]));
  // verdict scoped ONLY to the blocking rule
  check("3_mixed_scoped_to_block", JSON.stringify(ann[0].verdictRuleIds) === JSON.stringify(["r-block"]),
    proj(ann[0]));
}

// ── 4. MULTI-RULE deny, NO blockingRuleIds recorded -> attribution unavailable
{
  const lines = [{
    phase: "disposition", id: "u1", disposition: "deny",
    ruleIds: ["r1", "r2"], enforced: true, actionContext: "Bash:foo --force",
  }];
  const ann = computeConformance(lines);
  check("4_unscoped_verdict_changed", ann[0].verdict === "changed", proj(ann[0]));
  // empty scope -> no rule credited
  check("4_unscoped_empty_scope", JSON.stringify(ann[0].verdictRuleIds) === JSON.stringify([]),
    proj(ann[0]));
  check("4_unscoped_reason_discloses",
    ann[0].reason.includes("which rules blocked is unavailable"), ann[0].reason);
}

// ── 5. DENY delivered but NOT enforced (advisory path) -> unavailable ──────
{
  const lines = [{
    phase: "disposition", id: "n1", disposition: "deny",
    ruleIds: ["r-block"], enforced: false, // stage-lookup mouth: delivered, not enforced
    actionContext: "Bash:things",
  }];
  const ann = computeConformance(lines);
  check("5_not_enforced_no_changed", ann[0].verdict === undefined, proj(ann[0]));
  check("5_not_enforced_claim_unavailable", ann[0].claimType === "unavailable", proj(ann[0]));
  check("5_not_enforced_reason_delivered",
    ann[0].reason.includes("DELIVERED but not enforced"), ann[0].reason);
}

// ── 6. ADVISORY fire -> unavailable ────────────────────────────────────────
{
  const lines = [{
    phase: "disposition", id: "a1", disposition: "advisory",
    ruleIds: ["r-adv"], actionContext: "Bash:terraform plan",
  }];
  const ann = computeConformance(lines);
  check("6_advisory_no_verdict", ann[0].verdict === undefined, proj(ann[0]));
  check("6_advisory_claim_unavailable", ann[0].claimType === "unavailable", proj(ann[0]));
  check("6_advisory_reason_judgment",
    ann[0].reason.includes("judgment half"), ann[0].reason);
}

// ── 7. NON-FIRE dispositions ignored (silent / stage-hit-no-rules) ─────────
{
  const lines = [
    { phase: "disposition", id: "s1", disposition: "silent", actionContext: "Bash:echo" },
    { phase: "disposition", id: "s2", disposition: "stage-hit-no-rules", actionContext: "Bash:frob" },
  ];
  const ann = computeConformance(lines);
  check("7_nonfire_ignored", ann.length === 0, `len=${ann.length}`);
}

// ── 8. MULTI-MOUTH CHAIN: wrapper + gate share parentId, one verdict ───────
// Representative = the line naming the most rules (the gate). Enforced read
// across the whole chain: the wrapper's enforced=false must demote it.
{
  const lines = [
    // wrapper mouth: refuses the call, names no rules; part of the SAME chain as root
    { phase: "disposition", id: "wrap", parentId: "root", disposition: "deny", enforced: false, actionContext: "Bash:git push" },
    // gate mouth: same interception, same parent chain, names the rule
    { phase: "disposition", id: "gate", disposition: "deny", parentId: "root",
      enforced: true, ruleIds: ["r-git"], actionContext: "Bash:git push" },
    { phase: "disposition", id: "root", disposition: "deny", enforced: true, actionContext: "Bash:git push" },
  ];
  const ann = computeConformance(lines);
  // foldChainsToOneFire -> representative = gate (names 1 rule). Only it gets a verdict.
  check("8_one_verdict_per_chain", ann.length === 1, `len=${ann.map(proj).join(",")}`);
  check("8_representative_is_gate", ann[0].fireEventId === "gate", proj(ann[0]));
  // enforced read across chain: wrapper says false -> NOT changed
  check("8_enforced_false_across_chain", ann[0].verdict === undefined, proj(ann[0]));
  check("8_unavailable_claim", ann[0].claimType === "unavailable", proj(ann[0]));
}

// ── 9. IDEMPOTENCE: prior conformance line suppresses re-annotation ────────
{
  const lines = [
    { phase: "disposition", id: "f1", disposition: "deny", ruleIds: ["r1"],
      enforced: true, actionContext: "Bash:go" },
    // a prior pass already annotated f1 as changed, retried false
    { phase: "conformance", fireEventId: "f1", ruleIds: ["r1"], verdict: "changed",
      claimType: "source-observed", retriedUnchanged: false },
  ];
  const ann = computeConformance(lines);
  // prior exists, no retry improvement, no scope change -> skip
  check("9_idempotent_no_reannotate", ann.length === 0, `len=${ann.length}`);
}

// ── 10. RETRY IMPROVEMENT re-annotates: prior false, now retried true ──────
{
  const lines = [
    { phase: "disposition", id: "r1", disposition: "deny", ruleIds: ["r1"], enforced: true, actionContext: "Bash:dup" },
    { phase: "disposition", id: "r2", disposition: "deny", ruleIds: ["r1"], enforced: true, actionContext: "Bash:dup" },
    { phase: "conformance", fireEventId: "r1", verdict: "changed", claimType: "source-observed", retriedUnchanged: false },
  ];
  const ann = computeConformance(lines);
  // r1 gets RE-annotated (prior false -> now retried true); r2 is its own fire event
  const r1 = ann.find((x) => x.fireEventId === "r1");
  check("10_retry_improvement_reannotates", r1 !== undefined, proj(r1));
  check("10_now_retried_true", r1 && r1.retriedUnchanged === true, proj(r1));
  check("10_two_annotations", ann.length === 2, `len=${ann.map(proj).join(",")}`);
}

// ── 11. SCOPE MIGRATION re-annotates: prior unscoped, now scoped ───────────
{
  const lines = [
    { phase: "disposition", id: "s1", disposition: "deny", ruleIds: ["rA", "rB"],
      enforced: true, blockingRuleIds: ["rA"], actionContext: "Bash:z" },
    // prior annotation carries NO verdictRuleIds (old contract) -> annotatedScoped lacks s1
    { phase: "conformance", fireEventId: "s1", verdict: "changed", claimType: "source-observed" },
  ];
  const ann = computeConformance(lines);
  // attribution moved -> re-annotated once, scoped to rA
  check("11_scope_migration_reannotates", ann.length === 1, `len=${ann.map(proj).join(",")}`);
  check("11_scoped_after_migration",
    JSON.stringify(ann[0].verdictRuleIds) === JSON.stringify(["rA"]), proj(ann[0]));
}

// ── 12. actionKey: sha256 wins over text when both present ─────────────────
{
  const lines = [
    { phase: "disposition", id: "k1", disposition: "deny", ruleIds: ["r1"],
      enforced: true, actionContext: "long text a", actionContextSha256: "AAAA" },
    { phase: "disposition", id: "k2", disposition: "deny", ruleIds: ["r1"],
      enforced: true, actionContext: "long text b", actionContextSha256: "AAAA" },
  ];
  // both keyed by sha256:AAAA -> k1's act appears again -> k1 retried
  const ann = computeConformance(lines);
  const k = ann.find((x) => x.fireEventId === "k1");
  check("12_sha_key_retry_detection", k && k.retriedUnchanged === true, proj(k));
}

// ── 13. buildChainIds multi-hop: grandchild -> root, one chain id ──────────
{
  // three-deep interception: root <- child <- grandchild, same actionKey.
  // Without chain correlation, "deny at root" would see grandchild later and
  // report a retry across the SAME evaluation. buildChainIds roots them.
  const lines = [
    { phase: "disposition", id: "root", disposition: "deny", ruleIds: ["r1"], enforced: true, actionContext: "Bash:act" },
    { phase: "disposition", id: "child", parentId: "root", disposition: "deny", ruleIds: ["r1"], enforced: true, actionContext: "Bash:act" },
    { phase: "disposition", id: "gchild", parentId: "child", disposition: "deny", ruleIds: ["r1"], enforced: true, actionContext: "Bash:act" },
  ];
  const ann = computeConformance(lines);
  // all three are one chain; representative = first (ties keep earlier). Only 1 verdict.
  check("13_chain_fold_one", ann.length === 1, `len=${ann.map(proj).join(",")}`);
  // the single representative must NOT be marked retried (its own chain's other lines
  // are the "occurrences", but they are the SAME chain -> not a retry)
  check("13_no_false_retry_in_chain", ann[0].retriedUnchanged === false, proj(ann[0]));
}

// ─────────────────────── tallyByRule ───────────────────────────────────────
{
  // hand-built annotations covering the FULL verdict vocabulary
  // (changed/conformed/breached/no-effect/vacuous) + scoping + awaitingJudgment
  const anns = [
    { fireEventId: "a", ruleIds: ["R1"], verdict: "changed", claimType: "source-observed" },
    { fireEventId: "b", ruleIds: ["R1"], verdict: "conformed", claimType: "judgment" },
    { fireEventId: "c", ruleIds: ["R1"], verdict: "breached", claimType: "judgment" },
    { fireEventId: "d", ruleIds: ["R1"], verdict: "no-effect", claimType: "judgment" },
    { fireEventId: "e", ruleIds: ["R1"], verdict: "vacuous", claimType: "judgment" },
    // verdict scoped away from R2 -> R2 gets awaitingJudgment, R1 unaffected
    { fireEventId: "f", ruleIds: ["R1", "R2"], verdict: "changed", claimType: "source-observed", verdictRuleIds: ["R1"] },
    // advisory -> verdict undefined -> awaitingJudgment
    { fireEventId: "g", ruleIds: ["R3"], verdict: undefined, claimType: "unavailable" },
  ];
  const tallies = tallyByRule(anns);
  const byId = Object.fromEntries(tallies.map((t) => [t.ruleId, t]));
  check("tally_R1_fires6", byId["R1"] && byId["R1"].fires === 6, JSON.stringify(tallies));
  check("tally_R1_all_verdicts",
    byId["R1"] && byId["R1"].changed === 2 && byId["R1"].conformed === 1 &&
    byId["R1"].breached === 1 && byId["R1"].noEffect === 1 && byId["R1"].vacuous === 1,
    JSON.stringify(byId["R1"]));
  check("tally_R1_no_awaiting", byId["R1"] && byId["R1"].awaitingJudgment === 0,
    JSON.stringify(byId["R1"]));
  // R2: only the scoped-away fire -> awaitingJudgment 1, no verdict
  check("tally_R2_awaiting", byId["R2"] && byId["R2"].fires === 1 && byId["R2"].awaitingJudgment === 1,
    JSON.stringify(byId["R2"]));
  // R3: advisory -> awaitingJudgment 1
  check("tally_R3_awaiting", byId["R3"] && byId["R3"].awaitingJudgment === 1, JSON.stringify(byId["R3"]));
}

// ─────────────────────── retirementCandidates ──────────────────────────────
{
  const tallies = [
    // fired, never changed/conformed, nothing awaiting -> candidate
    { ruleId: "RET", fires: 3, changed: 0, conformed: 0, breached: 0, vacuous: 0, noEffect: 0, awaitingJudgment: 0 },
    // no-effect counts as measured + moved nothing -> candidate
    { ruleId: "RET2", fires: 1, changed: 0, conformed: 0, breached: 0, vacuous: 0, noEffect: 1, awaitingJudgment: 0 },
    // changed once -> NOT a candidate
    { ruleId: "KEEP", fires: 5, changed: 1, conformed: 0, breached: 0, vacuous: 0, noEffect: 0, awaitingJudgment: 0 },
    // conformed -> NOT a candidate
    { ruleId: "KEEP2", fires: 2, changed: 0, conformed: 2, breached: 0, vacuous: 0, noEffect: 0, awaitingJudgment: 0 },
    // never fired -> excluded
    { ruleId: "NEVER", fires: 0, changed: 0, conformed: 0, breached: 0, vacuous: 0, noEffect: 0, awaitingJudgment: 0 },
    // all fires awaiting judgment -> unmeasured, NOT a candidate
    { ruleId: "UNMEAS", fires: 4, changed: 0, conformed: 0, breached: 0, vacuous: 0, noEffect: 0, awaitingJudgment: 4 },
  ];
  const cands = retirementCandidates(tallies);
  const ids = cands.map((c) => c.ruleId).sort();
  check("retirement_candidates", JSON.stringify(ids) === JSON.stringify(["RET", "RET2"]),
    JSON.stringify(ids));
  check("retirement_filters_awaiting", !ids.includes("UNMEAS"), JSON.stringify(ids));
  check("retirement_keeps_measured", !ids.includes("KEEP") && !ids.includes("KEEP2"), JSON.stringify(ids));
}

// ────────────────────── appendConformanceAnnotations ────────────────────────
{
  const { writeFileSync, readFileSync, unlinkSync } = await import("node:fs");
  const { join } = await import("node:path");
  const { tmpdir } = await import("node:os");
  const jp = join(tmpdir(), `conform-journal-${Date.now()}.jsonl`);
  writeFileSync(jp, "");
  const anns = [
    { fireEventId: "f1", ruleIds: ["r1"], verdict: "changed", claimType: "source-observed", reason: "x" },
    { fireEventId: "f2", ruleIds: ["r2"], claimType: "unavailable", reason: "y" },
  ];
  appendConformanceAnnotations(jp, anns);
  const lines = readFileSync(jp, "utf8").trim().split("\n").map((l) => JSON.parse(l));
  check("append_two_lines", lines.length === 2, `len=${lines.length}`);
  check("append_phase_conformance", lines.every((l) => l.phase === "conformance"),
    JSON.stringify(lines.map((l) => l.phase)));
  check("append_fields", lines[0].fireEventId === "f1" && lines[0].verdict === "changed" &&
    lines[1].ruleIds[0] === "r2" && lines[1].claimType === "unavailable",
    JSON.stringify(lines));
  check("append_empty_noop", (() => {
    const before = readFileSync(jp, "utf8").length;
    appendConformanceAnnotations(jp, []);
    return readFileSync(jp, "utf8").length === before;
  })());
  unlinkSync(jp);
}

console.log(`\nRESULT: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
