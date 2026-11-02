import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev: the FastAPI backend runs on :8000; Vite proxies /api and /ws to it.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
  // single local app bundle (~530 kB, mostly React + lightweight-charts); code-splitting not needed yet
  build: { chunkSizeWarningLimit: 1200 },
  test: { environment: 'node' },
} as any);
