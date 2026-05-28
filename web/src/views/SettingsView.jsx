import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getSettings, patchSettings } from '../api/settings.js'
import { formatNumber } from '../lib/format.js'

const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

function emptyForm() {
  return {
    log_level: 'INFO',
    default_rate_limit: '100/minute',
    rules_cache_ttl_seconds: 0,
    rules_cache_enabled: false,
    endpoint_rate_limits: [],
  }
}

function buildForm(payload) {
  if (!payload) return emptyForm()
  return {
    log_level: String(payload.log_level || 'INFO').toUpperCase(),
    default_rate_limit: String(payload.default_rate_limit || '100/minute'),
    rules_cache_ttl_seconds: Number(payload.rules_cache_ttl_seconds || 0),
    rules_cache_enabled: Boolean(payload.rules_cache_enabled),
    endpoint_rate_limits: Array.isArray(payload.endpoint_rate_limits)
      ? payload.endpoint_rate_limits.map((item) => ({
          method: String(item.method || 'GET').toUpperCase(),
          path: String(item.path || '/'),
          limit: String(item.limit || '60/minute'),
        }))
      : [],
  }
}

export default function SettingsView() {
  const queryClient = useQueryClient()
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: getSettings })
  const [form, setForm] = useState(emptyForm())
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)

  useEffect(() => {
    if (settingsQuery.data) {
      setForm(buildForm(settingsQuery.data))
    }
  }, [settingsQuery.data])

  const mutation = useMutation({
    mutationFn: patchSettings,
    onSuccess: () => {
      setInfo('Settings saved.')
      setError(null)
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: (err) => {
      setInfo(null)
      setError(err?.message || 'Failed to save settings')
    },
  })

  const updateLimit = (index, value) => {
    setForm((current) => ({
      ...current,
      endpoint_rate_limits: current.endpoint_rate_limits.map((item, itemIndex) =>
        itemIndex === index ? { ...item, limit: value } : item,
      ),
    }))
  }

  const submit = (event) => {
    event.preventDefault()
    setError(null)
    setInfo(null)
    const ttl = Number(form.rules_cache_ttl_seconds)
    if (!Number.isInteger(ttl) || ttl < 0) {
      setError('Rules cache TTL must be a non-negative whole number.')
      return
    }
    mutation.mutate({
      log_level: form.log_level,
      default_rate_limit: form.default_rate_limit,
      rules_cache_enabled: Boolean(form.rules_cache_enabled),
      rules_cache_ttl_seconds: form.rules_cache_enabled ? ttl : 0,
      endpoint_rate_limits: form.endpoint_rate_limits,
    })
  }

  if (settingsQuery.isLoading) {
    return <section className="panel">Loading settings...</section>
  }

  if (settingsQuery.isError) {
    return (
      <section className="panel">
        <article className="message-card message-error">
          {settingsQuery.error?.message || 'Failed to load settings.'}
        </article>
      </section>
    )
  }

  const data = settingsQuery.data || {}

  return (
    <form className="view-stack" onSubmit={submit}>
      <section className="panel">
        <div className="panel-header">
          <h2>Core runtime</h2>
          <span className="muted">Endpoint: GET / PATCH /settings</span>
        </div>

        <div className="settings-form-grid">
          <label className="field-label">
            Log level
            <select
              value={form.log_level}
              onChange={(event) =>
                setForm((current) => ({ ...current, log_level: event.target.value.toUpperCase() }))
              }
            >
              {LOG_LEVELS.map((level) => (
                <option key={level} value={level}>{level}</option>
              ))}
            </select>
          </label>

          <label className="field-label">
            Default rate limit
            <input
              type="text"
              value={form.default_rate_limit}
              onChange={(event) =>
                setForm((current) => ({ ...current, default_rate_limit: event.target.value }))
              }
              placeholder="100/minute"
            />
          </label>

          <label className="field-label">
            Rules cache TTL (seconds)
            <input
              type="number"
              min={0}
              value={form.rules_cache_ttl_seconds}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  rules_cache_ttl_seconds: Number(event.target.value || 0),
                }))
              }
              disabled={!form.rules_cache_enabled}
            />
          </label>

          <label className="field-label settings-toggle">
            <span>Rules cache enabled</span>
            <input
              type="checkbox"
              checked={form.rules_cache_enabled}
              onChange={(event) =>
                setForm((current) => ({ ...current, rules_cache_enabled: event.target.checked }))
              }
            />
          </label>
        </div>

        <p className="muted settings-readonly">
          Rules path: <code>{data.rules_path || '-'}</code>{' '}
          ({data.rules_file_exists ? 'present on disk' : 'missing on disk'})
        </p>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Endpoint rate limits</h2>
          <span className="muted">{formatNumber(form.endpoint_rate_limits.length)} configured</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Method</th>
                <th>Path</th>
                <th>Limit</th>
              </tr>
            </thead>
            <tbody>
              {form.endpoint_rate_limits.map((item, index) => (
                <tr key={`${item.method}-${item.path}`}>
                  <td>{item.method}</td>
                  <td><code>{item.path}</code></td>
                  <td>
                    <input
                      className="limit-input"
                      type="text"
                      value={item.limit}
                      onChange={(event) => updateLimit(index, event.target.value)}
                      placeholder="60/minute"
                    />
                  </td>
                </tr>
              ))}
              {form.endpoint_rate_limits.length === 0 && (
                <tr>
                  <td colSpan={3} className="empty-cell">No endpoint limits configured.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="settings-actions">
          <button type="submit" className="btn btn-primary" disabled={mutation.isPending}>
            {mutation.isPending ? 'Saving...' : 'Save settings'}
          </button>
        </div>
        {info && <article className="message-card message-info in-panel">{info}</article>}
        {error && <article className="message-card message-error in-panel">{error}</article>}
      </section>
    </form>
  )
}
