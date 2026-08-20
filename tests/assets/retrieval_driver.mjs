// Driver for core/retrieval.ts — the query-ranking arms (scoring math only).
//
// This module exports the NATIVE and SOURCE retrieval scorers plus the
// card-emission floor helper. It is PURE (imports only ./embedding and
// ./lexical-overlap, neither of which has native deps), and its functions take
// a `db` shaped like StoragePort — which is literally what a better-sqlite3
// Database satisfies (`.prepare(sql).all(...params)`). So, unlike the
// conformance/spans/skeleton drivers, this one drives the REAL SQL against a
// REAL in-memory better-sqlite3 store (the native module is loaded by absolute
// path via createRequire, staying out of the esbuild bundle). That means the
// assertions cover the actual scoring queries (UNION-ALL segment/observation
// arms, json_each binding, token DF), not a mock.
//
// The MCP suite reaches scoreNativeConceptsByObservation through memory_search,
// but only the happy path — the 52.5% uncovered slice is the edge branches:
// zero-vector / non-positive / tie / superseded / source-kind exclusions, the
// observation-without-segment UNION-ALL fallback, the lexical arm's early
// returns and its per-observation overlap max, and all of scoreSourceConcepts.
//
// Isolation (GR-01): in-memory DB only; no store, no embedder, no ~/.monet.
//
// CONTRACT UNDER TEST (pinned from source):
//   NATIVE_SCORE_FLOOR === 0.12; nativeScoreFloorOf() honour/fence rules
//     (undefined/NaN/±Inf/-/<0 />=1 -> 0.12; in-range finite -> itself).
//   scoreNativeConceptsByObservation: max over segments picks highest cosine;
//     zero vectors excluded (placeholder); score<=0 excluded; tie -> smaller
//     observation id; superseded obs excluded; kind='source' excluded;
//     segment-less obs scored via the UNION-ALL fallback; empty candidate list
//     -> empty map; applyLexicalArm re-orders by per-observation overlap max,
//     never adds a candidate, early-returns on empty best / token-less probe.
//   scoreSourceConcepts: non-source rows ignored; zero chunks excluded; MAX
//     over {whole-file cosine, every ACTIVE chunk} (inactive chunks excluded);
//     no chunks -> whole-file; chunk>whole-file and whole-file>chunk.
import { createRequire } from "module";
import {
  NATIVE_SCORE_FLOOR,
  nativeScoreFloorOf,
  scoreNativeConceptsByObservation,
  scoreSourceConcepts,
} from "@retrieval-src";

const require = createRequire(import.meta.url);
const bsPath = process.env.E2E_BSQ3;
if (!bsPath) {
  console.error("E2E_BSQ3 (better-sqlite3 .node path) not set");
  process.exit(1);
}
const Database = require(bsPath);

// --- vectors as serialized JSON strings (what the embedding column holds) ---
const S_A = "[1,0]"; // cos(Q)=1.0
const S_B = "[0.6,0.8]"; // cos(Q)=0.6
const S_C = "[0.8,0.6]"; // cos(Q)=0.8
const S_ZERO = "[0,0]"; // zero placeholder
const S_ORTH = "[0,1]"; // cos(Q)=0 -> excluded by >0
const S_NEG = "[-1,0]"; // cos(Q)=-1 -> excluded by >0
const Q = new Float32Array([1, 0]); // unit query along axis 0

let PASS = 0;
let FAIL = 0;
function ok(cond, name) {
  if (cond) {
    PASS += 1;
  } else {
    FAIL += 1;
    console.log("  FAIL " + name);
  }
}
function approx(a, b, eps = 1e-5) {
  return Math.abs(a - b) <= eps;
}

function mkdb() {
  const db = new Database(":memory:");
  db.exec(
    `CREATE TABLE observations(
       id TEXT PRIMARY KEY, concept_id TEXT, kind TEXT,
       superseded_by TEXT, superseded_at TEXT, embedding TEXT);
     CREATE TABLE observation_segments(
       observation_id TEXT, segment_index INTEGER, embedding TEXT,
       PRIMARY KEY(observation_id, segment_index));
     CREATE TABLE observation_tokens(observation_id TEXT, token TEXT);
     CREATE TABLE source_chunks(concept_id TEXT, observation_id TEXT, lifecycle TEXT);`
  );
  return db;
}
function storeObs(db, { id, concept, kind = "native", embedding, superseded_by = null, superseded_at = null, segments = [], tokens = [] }) {
  db.prepare("INSERT INTO observations(id,concept_id,kind,superseded_by,superseded_at,embedding) VALUES(?,?,?,?,?,?)").run(
    id, concept, kind, superseded_by, superseded_at, embedding
  );
  segments.forEach((v, i) =>
    db.prepare("INSERT INTO observation_segments(observation_id,segment_index,embedding) VALUES(?,?,?)").run(id, i, v)
  );
  tokens.forEach((t) => db.prepare("INSERT INTO observation_tokens(observation_id,token) VALUES(?,?)").run(id, t));
}
function storeChunk(db, { concept, observation_id, lifecycle }) {
  db.prepare("INSERT INTO source_chunks(concept_id,observation_id,lifecycle) VALUES(?,?,?)").run(concept, observation_id, lifecycle);
}

// ============================ nativeScoreFloorOf ============================
ok(NATIVE_SCORE_FLOOR === 0.12, "floor const is 0.12");
ok(nativeScoreFloorOf(undefined) === 0.12, "floor undefined -> 0.12");
ok(Number.isNaN(nativeScoreFloorOf(NaN)) === false && nativeScoreFloorOf(NaN) === 0.12, "floor NaN -> 0.12");
ok(nativeScoreFloorOf(Infinity) === 0.12, "floor +Inf -> 0.12");
ok(nativeScoreFloorOf(-Infinity) === 0.12, "floor -Inf -> 0.12");
ok(nativeScoreFloorOf(-0.5) === 0.12, "floor negative -> 0.12");
ok(nativeScoreFloorOf(1.0) === 0.12, "floor ==1 -> 0.12 (must be <1)");
ok(nativeScoreFloorOf(1.7) === 0.12, "floor >1 -> 0.12");
ok(nativeScoreFloorOf(0.3) === 0.3, "floor in-range finite -> itself");
ok(nativeScoreFloorOf(0) === 0, "floor 0 -> 0 (valid lower bound)");

// ==================== scoreNativeConceptsByObservation =====================
// S1: max over segments; observation attribution.
{
  const db = mkdb();
  storeObs(db, { id: "o1", concept: "c1", embedding: S_A, segments: [S_B, S_A] });
  const res = scoreNativeConceptsByObservation(db, ["c1"], Q, "x", false);
  const m = res.get("c1");
  ok(m !== undefined, "s1 concept present");
  ok(m && approx(m.score, 1.0), "s1 max score 1.0");
  ok(m && approx(m.rank, 1.0) && m.rank === m.score, "s1 rank==score (no lexical)");
  ok(m && m.observationId === "o1", "s1 observation attribution");
}

// S2: zero-vector segment excluded (placeholder, not scored as 0).
{
  const db = mkdb();
  storeObs(db, { id: "o1", concept: "c1", embedding: S_ZERO, segments: [S_ZERO, S_B] });
  const res = scoreNativeConceptsByObservation(db, ["c1"], Q, "x", false);
  ok(approx(res.get("c1").score, 0.6), "s2 zero segment excluded, falls to 0.6");
}

// S3: non-positive cosines excluded (orth 0, neg -1) -> falls to 0.6.
{
  const db = mkdb();
  storeObs(db, { id: "o1", concept: "c1", embedding: S_A, segments: [S_ORTH, S_NEG, S_B] });
  const res = scoreNativeConceptsByObservation(db, ["c1"], Q, "x", false);
  ok(approx(res.get("c1").score, 0.6), "s3 non-positive cosines excluded");
}

// S4: tie between two observations of one concept -> lexicographically smaller id.
{
  const db = mkdb();
  storeObs(db, { id: "aa", concept: "c1", embedding: S_A, segments: [S_A] });
  storeObs(db, { id: "bb", concept: "c1", embedding: S_A, segments: [S_A] });
  const res = scoreNativeConceptsByObservation(db, ["c1"], Q, "x", false);
  ok(approx(res.get("c1").score, 1.0), "s4 tie score 1.0");
  ok(res.get("c1").observationId === "aa", "s4 tie -> smaller observation id");
}

// S5: superseded observation excluded from the scoring join.
{
  const db = mkdb();
  storeObs(db, { id: "o1", concept: "c1", embedding: S_A, superseded_by: "x", segments: [S_A] });
  storeObs(db, { id: "o2", concept: "c1", embedding: S_A, segments: [S_B] });
  const res = scoreNativeConceptsByObservation(db, ["c1"], Q, "x", false);
  ok(approx(res.get("c1").score, 0.6), "s5 superseded excluded, live obs 0.6");
  ok(res.get("c1").observationId === "o2", "s5 attribution to live obs");
}

// S6: kind='source' observation excluded from the NATIVE arm.
{
  const db = mkdb();
  storeObs(db, { id: "o1", concept: "c1", kind: "source", embedding: S_A, segments: [S_A] });
  storeObs(db, { id: "o2", concept: "c1", embedding: S_A, segments: [S_B] });
  const res = scoreNativeConceptsByObservation(db, ["c1"], Q, "x", false);
  ok(approx(res.get("c1").score, 0.6), "s6 source-kind obs excluded");
}

// S7: UNION-ALL fallback — observation with NO segments scored by its own vector.
{
  const db = mkdb();
  storeObs(db, { id: "o1", concept: "c1", embedding: S_A }); // no segments
  const res = scoreNativeConceptsByObservation(db, ["c1"], Q, "x", false);
  ok(approx(res.get("c1").score, 1.0), "s7 no-segment obs via fallback arm");
}

// S8: empty candidate list -> empty map (no query issued).
{
  const db = mkdb();
  storeObs(db, { id: "o1", concept: "c1", embedding: S_A, segments: [S_A] });
  const res = scoreNativeConceptsByObservation(db, [], Q, "x", false);
  ok(res.size === 0, "s8 empty candidates -> empty map");
}

// S9: lexical arm re-orders; distills to per-observation overlap max; rank>=score.
{
  const db = mkdb();
  // dense: c1=0.6, c2=0.8, c3=1.0 ; probe "sigma tau" (N=3)
  storeObs(db, { id: "o1", concept: "c1", embedding: S_A, segments: [S_B], tokens: ["sigma", "tau"] });
  storeObs(db, { id: "o2", concept: "c2", embedding: S_A, segments: [S_C], tokens: ["sigma"] });
  storeObs(db, { id: "o3", concept: "c3", embedding: S_A, segments: [S_A], tokens: [] });
  const res = scoreNativeConceptsByObservation(db, ["c1", "c2", "c3"], Q, "sigma tau", true);
  // idf(tau)=ln(3/2)=0.4055>0 (df=1); idf(sigma)=ln(3/3)=0 (df=2). c1 shares tau -> overlap 1 -> rank boosted.
  ok(approx(res.get("c1").rank, 0.6 * 2), "s9 c1 rank boosted 1.2");
  ok(res.get("c1").rank > res.get("c1").score, "s9 c1 rank > score");
  ok(approx(res.get("c2").rank, 0.8) && approx(res.get("c2").rank, res.get("c2").score), "s9 c2 no overlap rank==score");
  ok(approx(res.get("c3").rank, 1.0) && approx(res.get("c3").rank, res.get("c3").score), "s9 c3 no overlap rank==score");
  ok(res.get("c1").rank > res.get("c3").rank && res.get("c3").rank > res.get("c2").rank, "s9 lexical reorders c1 to top");
}

// S10: lexical arm early-returns when probe has no tokens (rank left == score).
{
  const db = mkdb();
  storeObs(db, { id: "o1", concept: "c1", embedding: S_A, segments: [S_A], tokens: ["sigma"] });
  const res = scoreNativeConceptsByObservation(db, ["c1"], Q, "!!!", true); // no [a-z0-9]
  ok(approx(res.get("c1").rank, 1.0) && approx(res.get("c1").rank, res.get("c1").score), "s10 token-less probe no change");
}

// S11: lexical arm early-returns when best is empty (orthogonal query).
{
  const db = mkdb();
  storeObs(db, { id: "o1", concept: "c1", embedding: S_A, segments: [S_ORTH] }); // cos 0 -> no candidate
  const res = scoreNativeConceptsByObservation(db, ["c1"], Q, "sigma tau", true);
  ok(res.size === 0, "s11 empty best -> lexical early return");
}

// S12: overlap MAX over a concept's observations (two obs, one high-overlap).
{
  const db = mkdb();
  // probe "alpha beta gamma" (3 unique tokens, each df=1 -> idf=ln(3/2)>0), N=3
  storeObs(db, { id: "o1", concept: "c1", embedding: S_A, segments: [S_B], tokens: ["alpha"] });
  storeObs(db, { id: "o2", concept: "c1", embedding: S_A, segments: [S_B], tokens: ["alpha", "beta", "gamma"] });
  storeObs(db, { id: "o3", concept: "c2", embedding: S_A, segments: [S_C], tokens: [] });
  storeObs(db, { id: "o4", concept: "c3", embedding: S_A, segments: [S_A], tokens: [] });
  const res = scoreNativeConceptsByObservation(db, ["c1", "c2", "c3"], Q, "alpha beta gamma", true);
  // c1 dense 0.6; o1 overlap ~0.333; o2 overlap 1.0 -> max 1.0 -> rank 1.2
  ok(approx(res.get("c1").rank, 0.6 * 2), "s12 c1 rank uses max-over-observations overlap (1.2)");
}

// ========================== scoreSourceConcepts ============================
// SS1: empty rows / non-source rows -> empty map.
{
  const db = mkdb();
  ok(scoreSourceConcepts(db, [], Q).size === 0, "ss1 empty rows -> empty");
  ok(scoreSourceConcepts(db, [{ id: "n1", kind: "native", embedding: S_A }], Q).size === 0, "ss1 non-source ignored");
}

// SS2: all-zero chunk excluded -> whole-file cosine alone.
{
  const db = mkdb();
  const rows = [{ id: "s1", kind: "source", embedding: S_A }];
  storeObs(db, { id: "o1", concept: "s1", kind: "source", embedding: S_ZERO });
  storeChunk(db, { concept: "s1", observation_id: "o1", lifecycle: "active" });
  const res = scoreSourceConcepts(db, rows, Q);
  ok(approx(res.get("s1"), 1.0), "ss2 zero chunk excluded -> whole-file 1.0");
}

// SS3: active chunk beats whole-file.
{
  const db = mkdb();
  const rows = [{ id: "s1", kind: "source", embedding: S_B }]; // whole-file 0.6
  storeObs(db, { id: "o1", concept: "s1", kind: "source", embedding: S_A }); // chunk 1.0
  storeChunk(db, { concept: "s1", observation_id: "o1", lifecycle: "active" });
  const res = scoreSourceConcepts(db, rows, Q);
  ok(approx(res.get("s1"), 1.0), "ss3 active chunk max -> 1.0");
}

// SS4: whole-file beats chunk.
{
  const db = mkdb();
  const rows = [{ id: "s1", kind: "source", embedding: S_A }]; // whole-file 1.0
  storeObs(db, { id: "o1", concept: "s1", kind: "source", embedding: S_B }); // chunk 0.6
  storeChunk(db, { concept: "s1", observation_id: "o1", lifecycle: "active" });
  const res = scoreSourceConcepts(db, rows, Q);
  ok(approx(res.get("s1"), 1.0), "ss4 whole-file max -> 1.0");
}

// SS5: inactive chunk excluded from the max.
{
  const db = mkdb();
  const rows = [{ id: "s1", kind: "source", embedding: S_B }]; // 0.6
  storeObs(db, { id: "o1", concept: "s1", kind: "source", embedding: S_A }); // would be 1.0 but INACTIVE
  storeObs(db, { id: "o2", concept: "s1", kind: "source", embedding: S_C }); // active 0.8
  storeChunk(db, { concept: "s1", observation_id: "o1", lifecycle: "archived" });
  storeChunk(db, { concept: "s1", observation_id: "o2", lifecycle: "active" });
  const res = scoreSourceConcepts(db, rows, Q);
  ok(approx(res.get("s1"), 0.8), "ss5 inactive chunk excluded -> 0.8");
}

// SS6: source row with no chunks -> whole-file cosine.
{
  const db = mkdb();
  const rows = [{ id: "s1", kind: "source", embedding: S_A }];
  const res = scoreSourceConcepts(db, rows, Q);
  ok(approx(res.get("s1"), 1.0), "ss6 no chunks -> whole-file 1.0");
}

console.log(`RESULT: ${PASS} passed, ${FAIL} failed`);
process.exit(FAIL ? 1 : 0);

// Re-export the module under test so the bundle is also introspectable (used by
// ad-hoc drivers / coverage attribution debugging), harmless to the direct-run path.
export { NATIVE_SCORE_FLOOR, nativeScoreFloorOf, scoreNativeConceptsByObservation, scoreSourceConcepts };
