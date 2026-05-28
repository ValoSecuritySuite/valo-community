import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { patchConfig } from '../api/enforcement.js'

export default function ProxyConfigCard({ config }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    proxy_upstream_url: '',
    proxy_request_timeout_seconds: 60,
    enforcement_max_body_bytes: 65536,
  })
  const [info, setInfo] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!config) return
    setForm({
      proxy_upstream_url: config.proxy_upstream_url || '',
      proxy_request_timeout_seconds: config.proxy_request_timeout_seconds ?? 60,
      enforcement_max_body_bytes: config.enforcement_max_body_bytes ?? 65536,
    })
  }, [config])

  const mutation = useMutation({
    mutationFn: patchConfig,
    onSuccess: () => {
      setInfo('Proxy configuration saved.')
      setError(null)
      queryClient.invalidateQueries({ queryKey: ['enforcement'] })
    },
    onError: (err) => {
      setInfo(null)
      setError(err?.message || 'Failed to save configuration')
    },
  })

  const handleSubmit = (event) => {
    event.preventDefault()
    setInfo(null)
    setError(null)
    mutation.mutate({
      proxy_upstream_url: form.proxy_upstream_url.trim(),
      proxy_request_timeout_seconds: Number(form.proxy_request_timeout_seconds),
      enforcement_max_body_bytes: Number(form.enforcement_max_body_bytes),
    })
  }

  return (
    <article className="panel">
      <div className="panel-header">
        <h2>Proxy upstream</h2>
        <span className="muted">Used by POST /v1/proxy/chat/completions</span>
      </div>

      <form className="settings-form-grid" onSubmit={handleSubmit}>
        <label className="field-label proxy-config-url">
          Upstream URL
          <input
            type="text"
            value={form.proxy_upstream_url}
            onChange={(event) =>
              setForm((current) => ({ ...current, proxy_upstream_url: event.target.value }))
            }
            placeholder="https://api.openai.com/v1/chat/completions"
          />
        </label>

        <label className="field-label">
          Timeout (seconds)
          <input
            type="number"
            min={1}
            step={0.5}
            value={form.proxy_request_timeout_seconds}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                proxy_request_timeout_seconds: event.target.value,
              }))
            }
          />
        </label>

        <label className="field-label">
          Max body bytes
          <input
            type="number"
            min={1024}
            step={1024}
            value={form.enforcement_max_body_bytes}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                enforcement_max_body_bytes: event.target.value,
              }))
            }
          />
        </label>

        <div className="field-actions proxy-config-actions">
          <button type="submit" className="btn btn-primary" disabled={mutation.isPending}>
            {mutation.isPending ? 'Saving...' : 'Save configuration'}
          </button>
        </div>
      </form>

      {info && <article className="message-card message-info in-panel">{info}</article>}
      {error && <article className="message-card message-error in-panel">{error}</article>}
    </article>
  )
}
