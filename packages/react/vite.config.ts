import { resolve } from 'path';
import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    outDir: 'dist',
    emptyOutDir: false,
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
      fileName: (format, entryName) => `${entryName}.${format === 'es' ? 'mjs' : 'cjs'}`,
    },
    rollupOptions: {
      external: ['react', 'react-dom', 'react/jsx-runtime'],
      output: {
        globals: {
          react: 'React',
          'react-dom': 'ReactDOM',
        },
        banner: (chunk) => {
          if (chunk.isEntry && (chunk.name === 'index' || chunk.name === 'hooks')) {
            return '"use client";\n';
          }
          return '';
        },
      },
    },
  },
});
