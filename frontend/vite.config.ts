import path from 'node:path';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

// Dev server proxies /api to the FastAPI backend so the signed session cookie
// (HttpOnly, SameSite=Lax) is treated as same-origin. In production the backend
// serves this build from `frontend/dist` at `/`, so no proxy is needed there.
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // Prompt-mode service worker: precache the app shell so the installed PWA
    // opens instantly from local cache, then toast when a new build is waiting
    // (src/lib/swUpdate.ts) — updates only apply on user confirm, so SW caching
    // can't strand anyone on a stale deploy silently.
    VitePWA({
      registerType: 'prompt',
      injectRegister: false, // main.tsx registers via virtual:pwa-register
      manifest: false, // the hand-written public/manifest.json stays authoritative
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        navigateFallback: 'index.html',
        // Never serve the SPA shell for API calls; the SW passes them through.
        navigateFallbackDenylist: [/^\/api\//],
      },
    }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5792,
    strictPort: true,
    // portless proxies external hostnames (e.g. condenser.reorx.com) to this dev
    // server; Vite blocks unknown Host headers unless they're allow-listed.
    allowedHosts: ['condenser.reorx.com'],
    proxy: {
      '/api': {
        target: process.env.CONDENSER_BACKEND ?? 'http://localhost:8792',
        changeOrigin: true,
      },
    },
  },
});
