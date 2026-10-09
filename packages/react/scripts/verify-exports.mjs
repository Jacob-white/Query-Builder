// Fails if any path referenced from package.json (main/module/types/exports/typesVersions)
// is missing from the built package, or if a built entry cannot actually be loaded as ESM
// and as CommonJS. Run after `pnpm run build`.
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const root = resolve(import.meta.dirname, "..");
const pkg = JSON.parse(readFileSync(resolve(root, "package.json"), "utf8"));
const problems = [];
const paths = new Set();

function collect(node) {
  if (typeof node === "string") paths.add(node);
  else if (Array.isArray(node)) node.forEach(collect);
  else if (node && typeof node === "object") Object.values(node).forEach(collect);
}
collect([pkg.main, pkg.module, pkg.types, pkg.exports, pkg.typesVersions]);

for (const p of paths) {
  if (!existsSync(resolve(root, p))) problems.push(`missing file referenced by package.json: ${p}`);
}

const require = createRequire(import.meta.url);
for (const [subpath, conditions] of Object.entries(pkg.exports)) {
  if (typeof conditions === "string") continue;
  const esm = resolve(root, conditions.import.default);
  const cjs = resolve(root, conditions.require.default);
  try {
    const mod = await import(pathToFileURL(esm).href);
    if (Object.keys(mod).length === 0) problems.push(`${subpath}: ESM entry has no exports`);
  } catch (error) {
    problems.push(`${subpath}: ESM import failed: ${error.message}`);
  }
  try {
    const mod = require(cjs);
    if (Object.keys(mod).length === 0) problems.push(`${subpath}: CJS entry has no exports`);
  } catch (error) {
    problems.push(`${subpath}: CJS require failed: ${error.message}`);
  }
}

if (problems.length > 0) {
  console.error(problems.map((p) => `  - ${p}`).join("\n"));
  process.exit(1);
}
console.log(`verify-exports: ${paths.size} referenced paths exist; every entry loads as ESM and CJS`);
