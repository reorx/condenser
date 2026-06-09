import path from 'node:path';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Dev server proxies /api to the FastAPI backend so the signed session cookie
// (HttpOnly, SameSite=Lax) is treated as same-origin. In production the backend
// serves this build from `frontend/dist` at `/`, so no proxy is needed there.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.CONDENSER_BACKEND ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
