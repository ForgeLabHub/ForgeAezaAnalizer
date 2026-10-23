import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dev server proxies the API so the SPA can use same-origin relative URLs,
// which also removes any need for permissive CORS in development.
// Override the backend with AEZA_API_TARGET when the API is not on port 8000.
const target = process.env.AEZA_API_TARGET ?? 'http://127.0.0.1:8000'
const proxy = {
  '/api': { target, changeOrigin: true },
  '/metrics': { target, changeOrigin: true },
  '/health': { target, changeOrigin: true },
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: Number(process.env.AEZA_WEB_PORT ?? 5173),
    proxy,
  },
  preview: {
    host: '0.0.0.0',
    port: Number(process.env.AEZA_PREVIEW_PORT ?? 4173),
    proxy,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
