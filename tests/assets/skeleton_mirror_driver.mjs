// Pure-source driver for core/skeleton-mirror.ts (test45) — pins the
// skeleton-mirror contract: manifest parse/rejection, skeletonBlock marker
// extraction, skeletonStateHash canonical ordering, hasCoveringSkeletonSurface
// breadth/alias coverage, and inspectSkeletonMirrors staleness detection
// (block-missing / block-edited / store-moved). Bundled from source with esbuild
// (alias @skeleton-src -> packages/core/src/skeleton-mirror.ts; the module's
// only imports are node:crypto / node:fs / node:path, so the bundle is
// self-contained) then executed with node@22. No store, no embedder, no ~/.monet
// touched (GR-01). Fixtures are written to a throwaway os.tmpdir().
//
// The module exports only the 2 instruction constants + 3 functions
// (hasCoveringSkeletonSurface / skeletonStateHash / inspectSkeletonMirrors);
// parseManifest + skeletonBlock + sha256 are private and exercised indirectly
// through those exports. The MCP/cli bundle reaches only the "write/cover" slice
// (via mcp-server.ts / engine.ts); this driver covers the read/inspection
// edge cases the bundle never runs.
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  MIRROR_STALE_INSTRUCTION,
  SKELETON_CHANGED_INSTRUCTION,
  hasCoveringSkeletonSurface,
  skeletonStateHash,
  inspectSkeletonMirrors,
} from "@skeleton-src";

const PASS = [];
const FAIL = [];
function check(name, cond, detail = "") {
  if (cond) { PASS.push(name); console.log(`  PASS ${name}` + (detail ? `  [${detail}]` : "")); }
  else { FAIL.push(name); console.log(`  FAIL ${name}` + (detail ? `  [${detail}]` : "")); }
}
const J = (o) => JSON.stringify(o);
const eq = (a, b) => J(a) === J(b);
const sha = (t) => createHash("sha256").update(t).digest("hex");
const HEX64 = /^[0-9a-f]{64}$/;

const BS = "<!-- BEGIN monet:skeleton"; // marker prefix (scope-attributed form, as materialize writes)
const END = "<!-- END monet:skeleton -->";
const BEGIN_MARK = (scope) => `${BS} scope=${scope} -->`;
const blockOf = (scope, body) => `${BEGIN_MARK(scope)}\n${body}\n${END}`;

// ---- temp root for fixtures ----
let ROOT;
try { ROOT = mkdtempSync(join(tmpdir(), "skel-drv-")); } catch (e) { console.error("no tmpdir", e); process.exit(1); }
const storeHome = join(ROOT, "store");
mkdirSync(storeHome, { recursive: true });
const surfA = join(ROOT, "a.md");     // a standalone surface file
const surfB = join(ROOT, "b.md");

function writeManifest(surfaces, materialized) {
  const text = JSON.stringify({ surfaces, materialized });
  writeFileSync(join(storeHome, "materialize.json"), text);
}
function writeSurface(path, blockText) {
  writeFileSync(path, "# Title\n\n" + blockText + "\n\ntrailing");
}
// ---- skeletonStateHash ----
{
  const h = skeletonStateHash([]);
  check("hash_empty_hex64", HEX64.test(h), h);
  const m1 = [{ conceptId: "c1", body: "A", breadth: "global" }, { conceptId: "c2", body: "B", breadth: "local" }];
  const m2 = [{ conceptId: "c2", body: "B", breadth: "local" }, { conceptId: "c1", body: "A", breadth: "global" }];
  const h1 = skeletonStateHash(m1), h2 = skeletonStateHash(m2);
  check("hash_order_invariant", h1 === h2);
  check("hash_sorts_by_conceptId", h1 !== skeletonStateHash([{ conceptId: "c0", body: "A", breadth: "global" }]));
  const withExtra = [{ conceptId: "c1", body: "A", breadth: "global", extra: "x" }];
  const plain = [{ conceptId: "c1", body: "A", breadth: "global" }];
  check("hash_strips_extra_fields", skeletonStateHash(withExtra) === skeletonStateHash(plain));
  check("hash_sensitive_to_body", h1 !== skeletonStateHash([{ conceptId: "c1", body: "Z", breadth: "global" }, { conceptId: "c2", body: "B", breadth: "local" }]));
  check("hash_sensitive_to_breadth", h1 !== skeletonStateHash([{ conceptId: "c1", body: "A", breadth: "local" }, { conceptId: "c2", body: "B", breadth: "local" }]));
  const ha = skeletonStateHash([{ conceptId: "c1", body: "A", breadth: "global" }]);
  check("hash_deterministic", ha === skeletonStateHash([{ conceptId: "c1", body: "A", breadth: "global" }]));
}
// ---- hasCoveringSkeletonSurface ----
{
  check("cover_null_store_false", hasCoveringSkeletonSurface(null, "x", "global") === false);
  check("cover_missing_manifest_false", hasCoveringSkeletonSurface(storeHome, "x", "global") === false);
  writeFileSync(join(storeHome, "materialize.json"), "{ not json");
  check("cover_malformed_false", hasCoveringSkeletonSurface(storeHome, "x", "global") === false);
  writeManifest([{ path: surfA, scope: "global" }], {});
  check("cover_global_global_true", hasCoveringSkeletonSurface(storeHome, "c", "global") === true);
  check("cover_global_local_false", hasCoveringSkeletonSurface(storeHome, "c", "local") === false);
  writeManifest([{ path: surfA, scope: { circle: "team" } }], {});
  check("cover_local_match_true", hasCoveringSkeletonSurface(storeHome, "team", "local") === true);
  check("cover_local_mismatch_false", hasCoveringSkeletonSurface(storeHome, "other", "local") === false);
  check("cover_local_global_false", hasCoveringSkeletonSurface(storeHome, "team", "global") === false);
  // alias resolution: surface declares scope.circle='alias'; caller resolves it to 'team'
  writeManifest([{ path: surfA, scope: { circle: "alias" } }], {});
  check("cover_local_alias_maps_true", hasCoveringSkeletonSurface(storeHome, "team", "local", (c) => c === "alias" ? "team" : c) === true);
  check("cover_local_alias_no_map_false", hasCoveringSkeletonSurface(storeHome, "team", "local", (c) => c) === false);
}
// ---- inspectSkeletonMirrors ----
{
  // null store
  let r = inspectSkeletonMirrors(null, "c", [{ conceptId: "c1", body: "A", breadth: "global" }]);
  check("ins_null_store", eq(r, { globalCovered: false, localCovered: false }), J(r));
  // missing manifest
  rmSync(join(storeHome, "materialize.json"), { force: true });
  r = inspectSkeletonMirrors(storeHome, "c", [{ conceptId: "c1", body: "A", breadth: "global" }]);
  check("ins_missing_manifest", eq(r, { globalCovered: false, localCovered: false }), J(r));
  // malformed manifest
  writeFileSync(join(storeHome, "materialize.json"), "!!!");
  r = inspectSkeletonMirrors(storeHome, "c", [{ conceptId: "c1", body: "A", breadth: "global" }]);
  check("ins_malformed_manifest", eq(r, { globalCovered: false, localCovered: false }), J(r));
  // invalid manifest shape: non-array surfaces
  writeFileSync(join(storeHome, "materialize.json"), JSON.stringify({ surfaces: "nope", materialized: {} }));
  r = inspectSkeletonMirrors(storeHome, "c", [{ conceptId: "c1", body: "A", breadth: "global" }]);
  check("ins_bad_surfaces_shape", eq(r, { globalCovered: false, localCovered: false }), J(r));
  // global surface only (matching circle irrelevant)
  const gmem = [{ conceptId: "g1", body: "GOV", breadth: "global" }];
  const lmem = [{ conceptId: "l1", body: "LOC", breadth: "local" }];
  const blockG = blockOf("global", "PRE" + sha("x"));
  writeSurface(surfA, blockG);
  writeManifest([{ path: surfA, scope: "global" }], { [surfA]: { blockHash: sha(skeletonBlockInner(blockG)), skeletonState: skeletonStateHash(gmem), when: 1 } });
  r = inspectSkeletonMirrors(storeHome, "team", [...gmem, ...lmem]);
  check("ins_global_covered", r.globalCovered === true && r.localCovered === false, J(r));
  // block-edited: blockHash deliberately wrong (matches a different block)
  writeManifest([{ path: surfA, scope: "global" }], { [surfA]: { blockHash: sha("totally different block"), skeletonState: skeletonStateHash(gmem), when: 1 } });
  // NOTE: block in file is blockG but manifest says hash of other text -> block-edited
  r = inspectSkeletonMirrors(storeHome, "team", [...gmem, ...lmem]);
  check("ins_block_edited", r.globalCovered === true && Array.isArray(r.mirrorStale) && r.mirrorStale[0].reason === "block-edited" && r.mirrorStale[0].path === surfA, J(r));
  check("ins_stale_instruction", typeof r.instruction === "string" && r.instruction.includes("monet materialize"), r.instruction);
  // block-missing: materialized entry absent
  writeManifest([{ path: surfA, scope: "global" }], {});
  r = inspectSkeletonMirrors(storeHome, "team", [...gmem, ...lmem]);
  check("ins_block_missing_no_materialized", r.mirrorStale && r.mirrorStale[0].reason === "block-missing", J(r));
  // block-missing: file has no skeleton markers
  writeFileSync(surfA, "# just prose, no markers");
  writeManifest([{ path: surfA, scope: "global" }], { [surfA]: { blockHash: sha("x"), skeletonState: skeletonStateHash(gmem), when: 1 } });
  r = inspectSkeletonMirrors(storeHome, "team", [...gmem, ...lmem]);
  check("ins_block_missing_no_markers", r.mirrorStale && r.mirrorStale[0].reason === "block-missing", J(r));
  // store-moved: blockHash matches but skeletonState stale (member changed since materialize)
  writeSurface(surfA, blockG);
  const stateAtMaterialize = skeletonStateHash([{ conceptId: "g1", body: "OLD-GOV", breadth: "global" }]); // different from current gmem
  writeManifest([{ path: surfA, scope: "global" }], { [surfA]: { blockHash: sha(skeletonBlockInner(blockG)), skeletonState: stateAtMaterialize, when: 1 } });
  r = inspectSkeletonMirrors(storeHome, "team", [...gmem, ...lmem]);
  check("ins_store_moved", r.mirrorStale && r.mirrorStale[0].reason === "store-moved", J(r));
  // not stale: blockHash + skeletonState both current
  writeManifest([{ path: surfA, scope: "global" }], { [surfA]: { blockHash: sha(skeletonBlockInner(blockG)), skeletonState: skeletonStateHash(gmem), when: 99 } });
  r = inspectSkeletonMirrors(storeHome, "team", [...gmem, ...lmem]);
  check("ins_not_stale", r.globalCovered === true && r.mirrorStale === undefined && "instruction" in r === false, J(r));
  // local surface + alias resolution: registered under circle alias, caller resolves it to the query circle
  const blockL = blockOf("alias", "PREL");
  writeSurface(surfB, blockL);
  writeManifest([{ path: surfB, scope: { circle: "alias" } }], { [surfB]: { blockHash: sha(skeletonBlockInner(blockL)), skeletonState: skeletonStateHash(lmem), when: 1 } });
  r = inspectSkeletonMirrors(storeHome, "team", [...gmem, ...lmem], (c) => c === "alias" ? "team" : c);
  check("ins_local_alias_covered", r.localCovered === true, J(r));
  check("ins_local_alias_not_stale", r.mirrorStale === undefined, J(r));
  // multi-surface: one stale local + one clean global -> both reflected
  writeManifest(
    [{ path: surfA, scope: "global" }, { path: surfB, scope: "global" }],
    {
      [surfA]: { blockHash: sha(skeletonBlockInner(blockG)), skeletonState: skeletonStateHash(gmem), when: 1 },
      [surfB]: { blockHash: sha("stale"), skeletonState: skeletonStateHash(gmem), when: 1 },
    }
  );
  r = inspectSkeletonMirrors(storeHome, "team", [...gmem, ...lmem]);
  check("ins_multi_surface_stale_count", Array.isArray(r.mirrorStale) && r.mirrorStale.length === 1 && r.mirrorStale[0].path === surfB, J(r));
  // only-local relevant: local surface for other circle excluded from 'relevant'
  writeManifest([{ path: surfB, scope: { circle: "elsewhere" } }], { [surfB]: { blockHash: sha(skeletonBlockInner(blockL)), skeletonState: skeletonStateHash(lmem), when: 1 } });
  r = inspectSkeletonMirrors(storeHome, "real-circle", [...gmem, ...lmem], (c) => c);
  check("ins_irrelevant_circle_excluded", r.globalCovered === false && r.localCovered === false && (r.mirrorStale === undefined || r.mirrorStale.length === 0), J(r));
  // begin marker present but no end marker -> skeletonBlock null -> block-missing
  writeFileSync(surfA, BEGIN_MARK("global") + "\nno end marker here");
  writeManifest([{ path: surfA, scope: "global" }], { [surfA]: { blockHash: sha("x"), skeletonState: skeletonStateHash(gmem), when: 1 } });
  r = inspectSkeletonMirrors(storeHome, "team", [...gmem, ...lmem]);
  check("ins_block_missing_begin_no_end", r.mirrorStale && r.mirrorStale[0].reason === "block-missing", J(r));
  // parseManifest: non-absolute surface path -> null
  writeManifest([{ path: "relative.md", scope: "global" }], {});
  r = inspectSkeletonMirrors(storeHome, "team", [...gmem, ...lmem]);
  check("ins_parse_relpath_surface", eq(r, { globalCovered: false, localCovered: false }), J(r));
  // parseManifest: invalid scope -> null
  writeManifest([{ path: surfA, scope: { circle: 123 } }], {});
  r = inspectSkeletonMirrors(storeHome, "team", [...gmem, ...lmem]);
  check("ins_parse_bad_scope", eq(r, { globalCovered: false, localCovered: false }), J(r));
  // parseManifest: materialized entry missing blockHash -> null
  writeManifest([{ path: surfA, scope: "global" }], { [surfA]: { skeletonState: "x", when: 1 } });
  r = inspectSkeletonMirrors(storeHome, "team", [...gmem, ...lmem]);
  check("ins_parse_bad_materialized_missing_hash", eq(r, { globalCovered: false, localCovered: false }), J(r));
  // parseManifest: non-numeric when -> null
  writeManifest([{ path: surfA, scope: "global" }], { [surfA]: { blockHash: "x", skeletonState: "y", when: "nope" } });
  r = inspectSkeletonMirrors(storeHome, "team", [...gmem, ...lmem]);
  check("ins_parse_bad_when", eq(r, { globalCovered: false, localCovered: false }), J(r));
  // instruction constants
  check("cst_stale_instruction", typeof MIRROR_STALE_INSTRUCTION === "string" && MIRROR_STALE_INSTRUCTION.includes("monet materialize"));
  check("cst_changed_instruction", typeof SKELETON_CHANGED_INSTRUCTION === "string" && SKELETON_CHANGED_INSTRUCTION.includes("monet materialize"));
}

// helper: replicate END-inclusive block slice used by skeletonBlock (only for fixture hashing)
function skeletonBlockInner(text) {
  const i = text.indexOf("<!-- BEGIN monet:skeleton");
  if (i < 0) return null;
  const e = text.indexOf(END, i + "<!-- BEGIN monet:skeleton".length);
  if (e < 0) return null;
  return text.slice(i, e + END.length);
}

try { rmSync(ROOT, { recursive: true, force: true }); } catch {}

console.log(`\nRESULT: ${PASS.length} passed, ${FAIL.length} failed`);
process.exit(FAIL.length ? 1 : 0);
