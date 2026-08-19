// Pure-source driver for core/spans.ts (test44) — pins the span:// URI
// parse/format bijection contract, including every rejection branch. Bundled
// from source with esbuild (alias @spans-src -> packages/core/src/spans.ts; the
// module has NO imports, so the bundle is self-contained), then executed with
// node@22. No store, no embedder, no ~/.monet touched (GR-01).
//
// Contract under test (all from source, pinned as falsifiable assertions):
//   - SPAN_SCHEME "span://"; CLAUDE_CODE_HOST "claude-code".
//   - isSpanRef: prefix test only (deliberately NOT parseSpan(s)!==null — a
//     malformed span must fail loudly through parseSpan, not be mis-tested).
//   - formatSpan: canonical URI; host grammar via HOST_RE; throws on invalid
//     host / empty session / empty anchor / known-host-invalid anchor /
//     unencodable lone surrogate (encodeField catch).
//   - parseSpan: strict, bijective (parseSpan(formatSpan(x))==x AND
//     formatSpan(parseSpan(s))==s for every parses-able s); rejects no-scheme,
//     missing/extra '#', missing '/', raw '/' in session, invalid host, empty
//     session/anchor, bad percent-escapes, non-canonical spellings, and
//     known-host-invalid anchors; unknown hosts carry anchors OPAQUELY.
//   - parseClaudeCodeAnchor / formatClaudeCodeAnchor: L<start>-L<end> grammar,
//     no leading zeros, start>=1, end>=start, safe integers; round-trip.
import {
  SPAN_SCHEME,
  CLAUDE_CODE_HOST,
  isSpanRef,
  formatSpan,
  parseSpan,
  parseClaudeCodeAnchor,
  formatClaudeCodeAnchor,
} from "@spans-src";

const PASS = [];
const FAIL = [];

function check(name, cond, detail = "") {
  if (cond) {
    PASS.push(name);
    console.log(`  PASS ${name}` + (detail ? `  [${detail}]` : ""));
  } else {
    FAIL.push(name);
    console.log(`  FAIL ${name}` + (detail ? `  [${detail}]` : ""));
  }
}

const J = (o) => JSON.stringify(o);
const eq = (a, b) => J(a) === J(b);

function throws(fn) {
  try {
    fn();
    return false;
  } catch {
    return true;
  }
}
function throwsMatching(fn, re) {
  try {
    fn();
    return false;
  } catch (e) {
    return re.test(String(e && e.message));
  }
}

function main() {
  // --- A. constants + isSpanRef ---
  check("const_scheme", SPAN_SCHEME === "span://", SPAN_SCHEME);
  check("const_claude_host", CLAUDE_CODE_HOST === "claude-code", CLAUDE_CODE_HOST);
  check("isSpanRef_true", isSpanRef("span://host/s#a") === true);
  check("isSpanRef_malformed_still_true", isSpanRef("span://") === true, "prefix test, not parse");
  check("isSpanRef_plain_ref", isSpanRef("src:repo/path#x") === false);
  check("isSpanRef_empty", isSpanRef("") === false);

  // --- B. formatSpan canonical + escapes ---
  const f1 = formatSpan({ host: "claude-code", sessionId: "sess 1", anchor: "L1-L3" });
  check("format_basic", f1 === "span://claude-code/sess%201#L1-L3", f1);
  const f2 = formatSpan({ host: "claude-code", sessionId: "a/b#c", anchor: "L1-L2" });
  check("format_escapes_delims", f2 === "span://claude-code/a%2Fb%23c#L1-L2", f2);
  check("format_throws_bad_host", throws(() => formatSpan({ host: "Bad Host!", sessionId: "s", anchor: "a" })));
  check(
    "format_throws_known_host_bad_anchor",
    throws(() => formatSpan({ host: "claude-code", sessionId: "s", anchor: "not-an-anchor" })),
  );
  check("format_throws_empty_session", throws(() => formatSpan({ host: "claude-code", sessionId: "", anchor: "L1-L2" })));
  check("format_throws_empty_anchor", throws(() => formatSpan({ host: "claude-code", sessionId: "s", anchor: "" })));
  // unknown opaque host: anchor carried unvalidated and escaped
  const f3 = formatSpan({ host: "some-agent", sessionId: "s", anchor: "x#y/z" });
  check("format_opaque_host_escapes_anchor", f3 === "span://some-agent/s#x%23y%2Fz", f3);
  // lone surrogate -> encodeField catch rethrow
  check(
    "format_throws_lone_surrogate_session",
    throwsMatching(() => formatSpan({ host: "claude-code", sessionId: "\uD800", anchor: "L1-L2" }), /not encodable \(unpaired surrogate\)/),
  );
  check(
    "format_throws_lone_surrogate_anchor",
    throwsMatching(() => formatSpan({ host: "some-agent", sessionId: "s", anchor: "L1-\uD800" }), /not encodable \(unpaired surrogate\)/),
  );

  // --- C. round-trip bijection ---
  const roundtrips = [
    { host: "claude-code", sessionId: "sess", anchor: "L1-L2" },
    { host: "claude-code", sessionId: "spaces and/slashes#", anchor: "L10-L20" },
    { host: "other-host", sessionId: "xyz", anchor: "anything/opaque#here" },
    { host: "a.b-c", sessionId: "s%", anchor: "a%2Fb" },
  ];
  for (const [i, x] of roundtrips.entries()) {
    check(`roundtrip_fmt_parse_${i}`, eq(parseSpan(formatSpan(x)), x), formatSpan(x));
    check(`roundtrip_parse_fmt_${i}`, formatSpan(parseSpan(formatSpan(x))) === formatSpan(x), formatSpan(x));
  }
  check(
    "parse_opaque_anchor_raw",
    eq(parseSpan("span://foo/s#a%2Fb"), { host: "foo", sessionId: "s", anchor: "a/b" }),
    "unknown host anchor uninterpreted",
  );

  // --- D. parseSpan negative cases ---
  check("parse_no_scheme", parseSpan("not-a-span") === null);
  check("parse_no_anchor_marker", parseSpan("span://host/sess") === null);
  check("parse_empty_anchor", parseSpan("span://host/sess#") === null);
  check("parse_extra_hash_in_anchor", parseSpan("span://host/sess#a#b") === null);
  check("parse_no_slash", parseSpan("span://host#a") === null);
  check("parse_raw_slash_in_session", parseSpan("span://host/s1/s2#a") === null);
  check("parse_bad_host", parseSpan("span://Bad-Host!/s#a") === null);
  check("parse_empty_session", parseSpan("span://host/#a") === null);
  check("parse_bad_escape_zz", parseSpan("span://host/s#%ZZ") === null);
  check("parse_trailing_percent", parseSpan("span://host/s#a%") === null);
  check("parse_noncanonical_raw_slash_anchor", parseSpan("span://host/sess#a/b") === null, "not bijective spelling");
  check("parse_known_host_bad_anchor", parseSpan("span://claude-code/s#nope") === null);
  check("parse_unknown_host_anchor_opaque_valid", eq(parseSpan("span://host/s#nope"), { host: "host", sessionId: "s", anchor: "nope" }));

  // --- E. parseClaudeCodeAnchor ---
  check("cc_anchor_ok", eq(parseClaudeCodeAnchor("L1-L3"), { startLine: 1, endLine: 3 }));
  check("cc_anchor_zero_start", parseClaudeCodeAnchor("L0-L5") === null);
  check("cc_anchor_leading_zero", parseClaudeCodeAnchor("L01-L2") === null);
  check("cc_anchor_reversed", parseClaudeCodeAnchor("L2-L1") === null);
  check("cc_anchor_no_match", parseClaudeCodeAnchor("line5") === null);
  check("cc_anchor_unsafe_int", parseClaudeCodeAnchor("L99999999999999999999-L2") === null);

  // --- F. formatClaudeCodeAnchor ---
  check("cc_fmt_ok", formatClaudeCodeAnchor({ startLine: 1, endLine: 5 }) === "L1-L5");
  check("cc_fmt_zero_start_throws", throws(() => formatClaudeCodeAnchor({ startLine: 0, endLine: 5 })));
  check("cc_fmt_nonint_throws", throws(() => formatClaudeCodeAnchor({ startLine: 1.5, endLine: 5 })));
  check("cc_fmt_reversed_throws", throws(() => formatClaudeCodeAnchor({ startLine: 5, endLine: 2 })));
  check("cc_fmt_roundtrip", formatClaudeCodeAnchor(parseClaudeCodeAnchor("L7-L9")) === "L7-L9");

  console.log(`\nRESULT: ${PASS.length} passed, ${FAIL.length} failed`);
  return FAIL.length ? 1 : 0;
}

process.exit(main());
