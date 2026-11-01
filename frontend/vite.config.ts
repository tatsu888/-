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
  test: { environment: 'node' },
} as any);
