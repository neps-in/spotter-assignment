import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// During dev the React app runs on :5173 and proxies /api to the Django
// backend on :8000 — same-origin from the browser's view, so no CORS setup.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
