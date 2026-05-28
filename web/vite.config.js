import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const BACKEND = process.env.VITE_BACKEND_URL || 'http://localhost:8000'

const PROXY_PREFIXES = [
  '/meta',
  '/health',
  '/rules',
  '/policies',
  '/playbooks',
  '/outcomes',
  '/learning',
  '/executive',
  '/scan',
  '/portfolio',
  '/ingest',
  '/dashboard/data',
  '/settings',
  '/report/pdf',
  '/report/pdf/rollup',
  '/report/pdf/scan',
  '/reports',
  '/analyze',
  '/enforcement',
  '/v1',
]

const proxy = Object.fromEntries(
  PROXY_PREFIXES.map((prefix) => [
    prefix,
    { target: BACKEND, changeOrigin: true },
  ]),
)

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy,
  },
})
