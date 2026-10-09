import { resolve } from 'path';
import { defineConfig } from 'vite';

// Entries that need a React client boundary (they render or call React hooks).
const USE_CLIENT_ENTRIES = new Set(['index', 'hooks']);

function banner(chunk: { isEntry: boolean; name: string }): string {
  return chunk.isEntry && USE_CLIENT_ENTRIES.has(chunk.name) ? '"use client";\n' : '';
}

// Every file gets an explicit module extension (.mjs / .cjs). The package declares
// "type": "module", so an extension-less ".js" chunk would be ambiguous for CJS output.
const common = { banner, globals: { react: 'React', 'react-dom': 'ReactDOM' } };

export default defineConfig({
  build: {
    outDir: 'dist',
    // dist/ is wiped first so renamed/removed entries and old hashed chunks can never be
    // published. Declarations are emitted afterwards by `tsc` (see the build script).
    emptyOutDir: true,
    sourcemap: true,
    lib: {
      entry: {
        index: resolve(__dirname, 'src/index.ts'),
        adapters: resolve(__dirname, 'src/adapters/index.ts'),
        hooks: resolve(__dirname, 'src/hooks/index.ts'),
        client: resolve(__dirname, 'src/client/index.ts'),
        olap: resolve(__dirname, 'src/olap/index.ts'),
      },
      formats: ['es', 'cjs'],
    },
    rollupOptions: {
      external: ['react', 'react-dom', 'react/jsx-runtime'],
      output: [
        {
          ...common,
          format: 'es',
          entryFileNames: '[name].mjs',
          chunkFileNames: 'chunks/[name]-[hash].mjs',
        },
        {
          ...common,
          format: 'cjs',
          entryFileNames: '[name].cjs',
          chunkFileNames: 'chunks/[name]-[hash].cjs',
        },
      ],
    },
  },
});
