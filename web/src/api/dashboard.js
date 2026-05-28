import { jsonFetch } from './client.js'

export const getDashboard = () =>
  jsonFetch('/dashboard/data', { label: 'GET /dashboard/data' })

export const getHealth = () => jsonFetch('/health', { label: 'GET /health' })
