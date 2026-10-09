// Post-build step: make the `tsc` declaration output valid for BOTH module systems.
//
// tsc emits one set of `.d.ts` files whose relative imports have no file extension
// ("./types", "./hooks"). Node's ESM resolver (moduleResolution node16/nodenext) rejects
// extension-less relative specifiers, and a `.d.ts` is typed as ESM only because the package
// declares "type": "module". So:
//   * `*.d.ts`  -> rewritten in place so relative specifiers end in `.js` (ESM types)
//   * `*.d.cts` -> a copy whose relative specifiers end in `.cjs` (CommonJS types)
// package.json `exports` points `import.types` at the former and `require.types` at the
// latter. Bundlers/`moduleResolution: bundler` and node10 (via `typesVersions`) keep working
// because TypeScript maps `./x.js` to `./x.d.ts`.
import { readdirSync, readFileSync, statSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

const dist = resolve(process.argv[2] ?? "dist");

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

const SPECIFIER = /(\bfrom\s*|\bimport\s*\(\s*|\bimport\s+|\bexport\s+\*\s+from\s*)(["'])(\.{1,2}\/[^"']*)\2/g;

function rewrite(source, file, ext) {
  return source.replace(SPECIFIER, (match, lead, quote, spec) => {
    if (/\.(c|m)?js$|\.json$|\.css$/.test(spec)) return match;
    const base = resolve(dirname(file), spec);
    let target;
    if (existsSync(`${base}.d.ts`)) target = `${spec}.${ext}`;
    else if (existsSync(join(base, "index.d.ts"))) target = `${spec.replace(/\/$/, "")}/index.${ext}`;
    else throw new Error(`dual-types: cannot resolve "${spec}" imported from ${file}`);
    return `${lead}${quote}${target}${quote}`;
  });
}

const declarations = walk(dist).filter((f) => f.endsWith(".d.ts"));
if (declarations.length === 0) throw new Error(`dual-types: no .d.ts files in ${dist}`);

for (const file of declarations) {
  const original = readFileSync(file, "utf8");
  // CJS copy is written first: it resolves against the untouched `.d.ts` siblings.
  writeFileSync(file.replace(/\.d\.ts$/, ".d.cts"), rewrite(original, file, "cjs"));
  writeFileSync(file, rewrite(original, file, "js"));
}
console.log(`dual-types: rewrote ${declarations.length} declaration files (.d.ts + .d.cts)`);
