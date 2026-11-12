import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The frontend never hard-codes the backend origin. In development the relative
// `/api` paths are proxied to the local Flask server; in production the same
// relative paths work behind a reverse proxy. Override the target with
// VITE_DEV_API_TARGET (see .env.example) if the backend runs elsewhere.
const apiTarget = process.env.VITE_DEV_API_TARGET || 'http://127.0.0.1:5000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: false,
        secure: false,
      },
    },
  },
  preview: {
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: false,
        secure: false,
      },
    },
  },
})