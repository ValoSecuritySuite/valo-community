const API_BASE = import.meta.env.VITE_BACKEND_URL || ''

export async function getEditionMeta() {
  const buildEdition = import.meta.env.VITE_VALO_EDITION || 'community'
  try {
    const res = await fetch(`${API_BASE}/meta/edition`)
    if (!res.ok) {
      return { edition: buildEdition, source: 'build' }
    }
    const data = await res.json()
    return { ...data, source: 'api' }
  } catch {
    return { edition: buildEdition, source: 'build' }
  }
}

export function isCommunityEdition(meta) {
  return (meta?.edition || import.meta.env.VITE_VALO_EDITION) === 'community'
}
