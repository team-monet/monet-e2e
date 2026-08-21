// Resolution/dedup engine coverage driver (test49).
//
// core/resolution.ts (the store-time resolution decision — "find by evidence,
// confirm by identity") is PURE: no db handle, no clock, no I/O. The MCP store
// path executes resolveIncoming() on every memory_store, so the suite observes
// its OUTPUT indirectly but never isolates the decision function or its band
// boundaries. This driver calls the exported pure functions directly with
// crafted nominations/centroids and pins the ENTIRE band matrix as falsifiable
// assertions (GR-07).
//
// The band mapping under test (design of record, resolution.ts header):
//   obsScore >= tauAttach & centroidScore >= tauAmbiguous -> ATTACH (mode "attach")
//   obsScore >= tauAttach & centroidScore <  tauAmbiguous -> FORK (mode "fork-signal")
//   tauAmbiguous <= obsScore < tauAttach                  -> ambiguous band
//        kind=="correction" -> correction-attach | else ambiguous-fork
//   obsScore <  tauAmbiguous & centroidTop >= tauAttach   -> create + PAIR (mode "blur-duplicate")
//   obsScore <  tauAmbiguous                             -> CREATE (mode "new")
//   nomination === null  -> createOrPair(input, 0) (centroid has NO attach power)
// Band boundaries are INCLUSIVE at the bottom (>=), matching the engine.
//
// Bundled from core SOURCE with an inline source map (alias @resolution-src ->
// packages/core/src/resolution.ts) so V8 coverage remaps to the source file.
// When the suite runs WITHOUT coverage this is still a real functional test:
// it asserts the driver's own assertion count passes, gating the dedup
// decision semantics.
//
// Exit 0 on all pass, 1 on any FAIL.

import {
  resolveIncoming,
  isDecidedResolutionMode,
  DECIDED_RESOLUTION_MODES,
} from "@resolution-src";

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

// canonical thresholds
const T = { tauAttach: 0.7, tauAmbiguous: 0.5 };
// helper to build a nomination
const nom = (conceptId, obsScore, centroidScore, observationId = "o1") =>
  ({ conceptId, obsScore, centroidScore, observationId });

// ---- 1. ATTACH: evidence + identity both agree ----------------------------
{
  const d = resolveIncoming({ nomination: nom("c1", 0.9, 0.6), thresholds: T });
  check("attach_action", d.action === "attached", d.action);
  check("attach_mode", d.mode === "attach", d.mode);
  check("attach_target", d.attachToConceptId === "c1", d.attachToConceptId);
  check("attach_score", d.score === 0.9, d.score);
  check("attach_no_dup_edge", d.duplicateEdge === undefined, JSON.stringify(d.duplicateEdge));
}

// ---- 2. ATTACH boundary: obs exactly ON tauAttach (>= inclusive) ----------
{
  const d = resolveIncoming({ nomination: nom("c1", 0.7, 0.6), thresholds: T });
  check("attach_on_tauAttach_attaches", d.action === "attached" && d.mode === "attach", `${d.action}/${d.mode}`);
}

// ---- 3. FORK-SIGNAL: evidence strong but centroid drifted below tauAmbiguous
{
  const d = resolveIncoming({ nomination: nom("c1", 0.9, 0.4), thresholds: T });
  check("fork_action_ambiguous", d.action === "ambiguous", d.action);
  check("fork_mode", d.mode === "fork-signal", d.mode);
  check("fork_dup_edge", d.duplicateEdge?.conceptId === "c1" && d.duplicateEdge.weight === 0.9,
    JSON.stringify(d.duplicateEdge));
  check("fork_nearmatch", d.nearMatchId === "c1" && d.nearMatchScore === 0.9,
    `${d.nearMatchId}/${d.nearMatchScore}`);
  check("fork_no_attachTo", d.attachToConceptId === undefined, String(d.attachToConceptId));
}

// ---- 4. centroid boundary: exactly tauAmbiguous stays attach, below forks --
{
  const dA = resolveIncoming({ nomination: nom("c1", 0.9, 0.5), thresholds: T });
  check("centroid_on_tauAmbiguous_attaches", dA.mode === "attach", dA.mode);
  const dB = resolveIncoming({ nomination: nom("c1", 0.9, 0.499), thresholds: T });
  check("centroid_below_tauAmbiguous_forks", dB.mode === "fork-signal", dB.mode);
}

// ---- 5. AMBIGUOUS-FORK: tauAmbiguous <= obs < tauAttach, plain kind --------
{
  const d = resolveIncoming({ nomination: nom("c1", 0.6, 0.8), thresholds: T });
  check("amb_action_ambiguous", d.action === "ambiguous", d.action);
  check("amb_mode", d.mode === "ambiguous-fork", d.mode);
  check("amb_dup_edge", d.duplicateEdge?.conceptId === "c1" && d.duplicateEdge.weight === 0.6,
    JSON.stringify(d.duplicateEdge));
  check("amb_no_attachTo", d.attachToConceptId === undefined, String(d.attachToConceptId));
}

// ---- 6. AMBIGUOUS boundary: obs exactly ON tauAmbiguous (>=) --------------
{
  const d = resolveIncoming({ nomination: nom("c1", 0.5, 0.8), thresholds: T });
  check("amb_on_tauAmbiguous_forks", d.mode === "ambiguous-fork", d.mode);
}

// ---- 7. CORRECTION-ATTACH: ambiguous band, kind="correction" --------------
{
  const d = resolveIncoming({ nomination: nom("c1", 0.6, 0.8), kind: "correction", thresholds: T });
  check("corr_mode", d.mode === "correction-attach", d.mode);
  check("corr_action_ambiguous", d.action === "ambiguous", d.action);
  check("corr_attachTo", d.attachToConceptId === "c1", d.attachToConceptId);
  check("corr_nearmatch", d.nearMatchId === "c1" && d.nearMatchScore === 0.6, `${d.nearMatchId}/${d.nearMatchScore}`);
  check("corr_no_dup_edge", d.duplicateEdge === undefined, JSON.stringify(d.duplicateEdge));
}

// ---- 8. BLUR-DUPLICATE: obs below ambiguous, centroid claims identity ------
{
  const d = resolveIncoming({
    nomination: nom("c1", 0.3, 0.2),
    centroidTop: { conceptId: "c2", centroidScore: 0.8 },
    thresholds: T,
  });
  check("blur_action_ambiguous", d.action === "ambiguous", d.action);
  check("blur_mode", d.mode === "blur-duplicate", d.mode);
  check("blur_dup_edge_target_c2", d.duplicateEdge?.conceptId === "c2", d.duplicateEdge?.conceptId);
  check("blur_dup_edge_weight_centroid", d.duplicateEdge?.weight === 0.8, String(d.duplicateEdge?.weight));
  check("blur_nearmatch_c2", d.nearMatchId === "c2" && d.nearMatchScore === 0.8, `${d.nearMatchId}/${d.nearMatchScore}`);
  // score is the nomination obsScore (evidence), even though centroid triggered the pair
  check("blur_score_is_obs", d.score === 0.3, String(d.score));
}

// ---- 9. CREATE (plain new): obs below ambiguous, no centroid claim ---------
{
  const d = resolveIncoming({ nomination: nom("c1", 0.3, 0.2), thresholds: T });
  check("new_action_created", d.action === "created", d.action);
  check("new_mode", d.mode === "new", d.mode);
  check("new_score", d.score === 0.3, String(d.score));
  check("new_no_attachTo", d.attachToConceptId === undefined, String(d.attachToConceptId));
  check("new_no_dup_edge", d.duplicateEdge === undefined, JSON.stringify(d.duplicateEdge));
}

// ---- 10. centroid boundary: exactly tauAttach pairs, just below creates ----
{
  const dA = resolveIncoming({
    nomination: nom("c1", 0.3, 0.2),
    centroidTop: { conceptId: "c2", centroidScore: 0.7 },
    thresholds: T,
  });
  check("blur_on_tauAttach_pairs", dA.mode === "blur-duplicate", dA.mode);
  const dB = resolveIncoming({
    nomination: nom("c1", 0.3, 0.2),
    centroidTop: { conceptId: "c2", centroidScore: 0.699 },
    thresholds: T,
  });
  check("blur_below_tauAttach_creates", dB.mode === "new", dB.mode);
}

// ---- 11. NULL nomination: no evidence anywhere; centroid can PAIR but not ATTACH
{
  // centroid above tauAttach -> blur-duplicate, score forced to 0 (nothing nominated)
  const dP = resolveIncoming({ nomination: null, centroidTop: { conceptId: "c9", centroidScore: 0.9 }, thresholds: T });
  check("nullnom_blur", dP.mode === "blur-duplicate" && dP.action === "ambiguous", `${dP.mode}/${dP.action}`);
  check("nullnom_blur_score0", dP.score === 0, String(dP.score));
  check("nullnom_blur_target", dP.duplicateEdge?.conceptId === "c9", dP.duplicateEdge?.conceptId);
  // no centroid claim -> plain create, score 0
  const dN = resolveIncoming({ nomination: null, thresholds: T });
  check("nullnom_create", dN.mode === "new" && dN.action === "created", `${dN.mode}/${dN.action}`);
  check("nullnom_create_score0", dN.score === 0, String(dN.score));
}

// ---- 12. isDecidedResolutionMode: scored modes decided, bypasses not -------
{
  const decided = ["attach", "fork-signal", "species-fork", "stage-fork", "ambiguous-fork", "correction-attach", "blur-duplicate", "new"];
  const decidedOk = decided.every((m) => isDecidedResolutionMode(m));
  check("decided_modes_true", decidedOk === true, `${decided.length} modes`);
  check("bypass_modes_false", isDecidedResolutionMode("direct-attach") === false &&
    isDecidedResolutionMode("force-new") === false, "direct-attach/force-new");
  check("unknown_mode_false", isDecidedResolutionMode("bogus") === false, "bogus");
}

// ---- 13. DECIDED_RESOLUTION_MODES constant: exact 8-mode closed set ---------
{
  check("const_len_8", DECIDED_RESOLUTION_MODES.length === 8, String(DECIDED_RESOLUTION_MODES.length));
  const expected = ["attach", "fork-signal", "species-fork", "stage-fork", "ambiguous-fork", "correction-attach", "blur-duplicate", "new"];
  check("const_members", JSON.stringify([...DECIDED_RESOLUTION_MODES]) === JSON.stringify(expected),
    JSON.stringify([...DECIDED_RESOLUTION_MODES]));
}

console.log(`\nRESULT: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
