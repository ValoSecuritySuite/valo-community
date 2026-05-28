import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { normalizeAndIngest } from '../api/ingestion.js'
import { formatNumber } from '../lib/format.js'

const DEFAULT_PAYLOAD = `{
  "result": {
    "scans": [
      {
        "scan_id": "ext-scan-001",
        "target": "external-scanner",
        "risk_score": 72.5,
        "findings": [
          {"severity": "High", "category": "prompt_injection"}
        ]
      }
    ]
  }
}`

export default function IngestionView() {
  const queryClient = useQueryClient()
  const [payload, setPayload] = useState(DEFAULT_PAYLOAD)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  const mutation = useMutation({
    mutationFn: normalizeAndIngest,
    onSuccess: (data) => {
      setResult(data)
      setError(null)
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: (err) => {
      setResult(null)
      setError(err?.message || 'Failed to ingest payload')
    },
  })

  const submit = (event) => {
    event.preventDefault()
    let parsed
    try {
      parsed = JSON.parse(payload)
    } catch (err) {
      setError(`Invalid JSON: ${err?.message || 'parse error'}`)
      return
    }
    mutation.mutate(parsed)
  }

  return (
    <div className="view-stack">
      <section className="panel panel-ops">
        <div className="panel-header">
          <h2>Ingestion workspace</h2>
          <span className="muted">Endpoint: POST /ingest/normalize</span>
        </div>

        <p className="muted">
          Paste tool output (your own scanner, an external SAST/SCA report, or a wrapped
          /scan/report dump) to normalize it into the Valo portfolio.
        </p>

        <form onSubmit={submit}>
          <div className="field-actions">
            <button type="submit" className="btn btn-primary" disabled={mutation.isPending}>
              {mutation.isPending ? 'Normalizing...' : 'Normalize + ingest JSON'}
            </button>
          </div>

          <textarea
            value={payload}
            onChange={(event) => setPayload(event.target.value)}
            rows={14}
            placeholder="Paste tool output, /scan/report output, or wrapped scans JSON"
          />
        </form>

        {error && <article className="message-card message-error in-panel">{error}</article>}
        {result && (
          <article className="message-card message-info in-panel">
            Ingested {formatNumber(result.accepted_count || 0)} scan(s), rejected{' '}
            {formatNumber(result.rejected_count || 0)}. Portfolio now has{' '}
            {formatNumber(result.portfolio_summary?.total_scans || 0)} total scan(s).
          </article>
        )}
      </section>
    </div>
  )
}
