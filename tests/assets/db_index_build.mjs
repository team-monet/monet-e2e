// Static esbuild build script for test43 (cli/db/index.ts pure-source driver).
// Copied into packages/cli/ at run time (esbuild resolves from there) and driven
// entirely by E2E_* env vars, so it needs no per-run code generation.
import { build } from "esbuild";

await build({
  entryPoints: [process.env.E2E_DRIVER],
  outfile: process.env.E2E_OUT,
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node22",
  sourcemap: "inline",
  sourcesContent: true,
  minify: false,
  legalComments: "none",
  alias: {
    "@dbindex-src": process.env.E2E_DBINDEX,
    "@team-monet/core": process.env.E2E_CORE_BARREL,
  },
  logLevel: "warning",
});
console.log("built");
