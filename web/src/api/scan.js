import { apiEndpoint, jsonFetch } from './client.js'

export const analyzePrompt = ({ prompt, target = 'web-ui' }) =>
  jsonFetch('/analyze', {
    method: 'POST',
    body: { prompt, target },
    label: 'POST /analyze',
  })

export async function downloadRollupPdf() {
  const resp = await fetch(apiEndpoint('/report/pdf/rollup'))
  if (!resp.ok) {
    throw new Error(`Failed to export PDF (${resp.status})`)
  }
  return resp
}

export async function downloadScanPdf({ scanId, prompt, target = 'web-ui' }) {
  if (scanId) {
    const resp = await fetch(apiEndpoint(`/report/pdf/scan/${encodeURIComponent(scanId)}`))
    if (!resp.ok) {
      throw new Error(`Failed to export scan PDF (${resp.status})`)
    }
    return resp
  }

  const resp = await fetch(apiEndpoint('/report/pdf'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, target }),
  })
  if (!resp.ok) {
    throw new Error(`Failed to export scan PDF (${resp.status})`)
  }
  return resp
}

export async function downloadFromResponse(resp, fallbackName) {
  const blob = await resp.blob()
  const cd = resp.headers.get('content-disposition') || ''
  const match = cd.match(/filename=([^;]+)/i)
  const filename = match ? match[1].replace(/"/g, '').trim() : fallbackName
  return { blob, filename }
}
