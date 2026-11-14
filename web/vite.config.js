import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { resolve } from 'node:path';

const API = process.env.AROIOD || 'http://localhost:8140';

export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    host: true,
    proxy: { '/api': { target: API, ws: true, changeOrigin: false } },
  },
  build: {
    target: 'es2020',
    rollupOptions: {
      input: { app: resolve(import.meta.dirname, 'index.html'), sim: resolve(import.meta.dirname, 'sim.html') },
    },
  },
});
