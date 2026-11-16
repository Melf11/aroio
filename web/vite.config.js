import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { resolve } from 'node:path';

const API = process.env.AROIOD || 'http://localhost:8140';

// "demo": the app with the simulated Aroio in the browser, for GitHub Pages (tools/build-demo.sh)
export default defineConfig(({ mode }) => ({
  base: mode === 'demo' ? process.env.AROIO_DEMO_BASE || '/aroio/' : '/',
  plugins: [svelte()],
  server: {
    port: 5173,
    host: true,
    proxy: { '/api': { target: API, ws: true, changeOrigin: false } },
  },
  build: {
    target: 'es2020',
    outDir: mode === 'demo' ? 'dist-demo' : 'dist',
    rollupOptions: {
      input: mode === 'demo' ? { app: resolve(import.meta.dirname, 'index.html') }
        : { app: resolve(import.meta.dirname, 'index.html'), sim: resolve(import.meta.dirname, 'sim.html') },
    },
  },
}));
