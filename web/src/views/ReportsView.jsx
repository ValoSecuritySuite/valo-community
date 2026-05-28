import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  deleteReport,
  downloadReport,
  generateReport,
  getSchedulerState,
  listReportKinds,
  listReports,
  runScheduler,
} from '../api/reports.js'
import { downloadFromResponse } from '../api/scan.js'
import { triggerDownload } from '../lib/format.js'

const PAGE_SIZE = 25

const FORMAT_OPTIONS = ['', 'pdf', 'csv', 'json']
const STATUS_OPTIONS = ['', 'ok', 'failed']

function formatTimestamp(value) {
  if (!value) return '-'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString()
}

function formatBytes(value) {
  const n = Number(value || 0)
  if (!Number.isFinite(n) || n <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = n
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i += 1
  }
  return `${size.toFixed(size >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

export default function ReportsView() {
  const [reports, setReports] = useState([])
  const [total, setTotal] = useState(0)
  const [persisted, setPersisted] = useState(0)
  const [page, setPage] = useState(0)
  const [filters, setFilters] = useState({
    kind: '',
    format: '',
    status: '',
  })

  const [kinds, setKinds] = useState([])
  const [schedulerState, setSchedulerState] = useState(null)

  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [runningScheduler, setRunningScheduler] = useState(false)
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)

  const [generateForm, setGenerateForm] = useState({
    kind: 'executive_pdf_7d',
    scan_id: '',
  })

  const queryParams = useMemo(() => {
    const params = { limit: PAGE_SIZE, offset: page * PAGE_SIZE }
    if (filters.kind) params.kind = filters.kind
    if (filters.format) params.format = filters.format
    if (filters.status) params.status = filters.status
    return params
  }, [filters, page])

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listReports(queryParams)
      setReports(data?.reports || [])
      setTotal(Number(data?.total || 0))
      setPersisted(Number(data?.persisted || 0))
    } catch (err) {
      setError(err.message || 'Failed to load reports')
    } finally {
      setLoading(false)
    }
  }, [queryParams])

  const refreshScheduler = useCallback(async () => {
    try {
      const data = await getSchedulerState()
      setSchedulerState(data)
    } catch (err) {
      setError(err.message || 'Failed to load scheduler state')
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    listReportKinds()
      .then((data) => {
        if (!cancelled) setKinds(data?.kinds || [])
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load report kinds')
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    refreshScheduler()
  }, [refreshScheduler])

  const handleFilterChange = (key) => (event) => {
    setPage(0)
    setFilters((prev) => ({ ...prev, [key]: event.target.value }))
  }

  const selectedKind = useMemo(
    () => kinds.find((k) => k.name === generateForm.kind),
    [kinds, generateForm.kind],
  )

  const handleGenerate = async (event) => {
    event.preventDefault()
    setGenerating(true)
    setError(null)
    setInfo(null)
    try {
      const payload = { kind: generateForm.kind }
      if (selectedKind?.requires_scan_id) {
        if (!generateForm.scan_id.trim()) {
          throw new Error('scan_id is required for this kind')
        }
        payload.scan_id = generateForm.scan_id.trim()
      }
      const result = await generateReport(payload)
      setInfo(
        `Generated ${result?.report?.kind || generateForm.kind} (${formatBytes(
          result?.report?.size_bytes,
        )}).`,
      )
      await refresh()
    } catch (err) {
      setError(err.message || 'Failed to generate report')
    } finally {
      setGenerating(false)
    }
  }

  const handleDownload = async (record) => {
    setError(null)
    try {
      const resp = await downloadReport(record.report_id)
      const { blob, filename } = await downloadFromResponse(
        resp,
        record.filename || `${record.kind}.${record.format}`,
      )
      triggerDownload(blob, filename)
    } catch (err) {
      setError(err.message || 'Failed to download report')
    }
  }

  const handleDelete = async (record) => {
    setError(null)
    setInfo(null)
    try {
      await deleteReport(record.report_id)
      setInfo(`Deleted report ${record.report_id.slice(0, 8)}.`)
      await refresh()
    } catch (err) {
      setError(err.message || 'Failed to delete report')
    }
  }

  const handleRunScheduler = async ({ force = false } = {}) => {
    setRunningScheduler(true)
    setError(null)
    setInfo(null)
    try {
      const result = await runScheduler({ force })
      const ran = (result?.results || []).filter((r) => r.status === 'ran')
      const failed = (result?.results || []).filter(
        (r) => r.status === 'failed',
      )
      const skipped = (result?.results || []).filter(
        (r) => r.status === 'skipped',
      )
      const segments = []
      if (ran.length) segments.push(`${ran.length} ran`)
      if (skipped.length) segments.push(`${skipped.length} skipped`)
      if (failed.length) segments.push(`${failed.length} failed`)
      setInfo(
        `Scheduler tick: ${segments.join(', ') || 'no kinds eligible'}` +
          (result?.pruned ? `; pruned ${result.pruned} old report(s)` : ''),
      )
      if (failed.length) {
        setError(
          `Some kinds failed: ${failed
            .map((row) => `${row.kind} (${row.error || 'unknown error'})`)
            .join(', ')}`,
        )
      }
      await refresh()
      await refreshScheduler()
    } catch (err) {
      setError(err.message || 'Failed to trigger scheduler')
    } finally {
      setRunningScheduler(false)
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const currentPage = Math.min(page + 1, totalPages)

  return (
    <section className="reports-view view-stack" aria-label="Phase 4 Reports">
      <section className="panel panel-ops">
        <div className="panel-header">
          <h2>Reports</h2>
          <span className="muted">Endpoint: /reports</span>
        </div>
        <p className="muted">
          Persistent weekly reports plus on-demand generation. Reuses the
          existing executive metrics and portfolio rollup engines: see the
          Reporting Automation plan for details.
        </p>

        <div className="settings-toolbar">
          <p className="muted">
            {loading
              ? 'Loading reports...'
              : `Showing ${reports.length} of ${total} matching (page ${currentPage} of ${totalPages}, ${persisted} persisted total).`}
          </p>
          <div className="settings-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                refresh()
                refreshScheduler()
              }}
              disabled={loading || runningScheduler}
            >
              {loading ? 'Refreshing...' : 'Refresh'}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => handleRunScheduler({ force: false })}
              disabled={runningScheduler}
              title="Run weekly cadence for any kinds that have not produced a report this window"
            >
              {runningScheduler ? 'Running...' : 'Run scheduler now'}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => handleRunScheduler({ force: true })}
              disabled={runningScheduler}
              title="Force-run every default kind (ignores last-run timestamps)"
            >
              {runningScheduler ? 'Running...' : 'Force run all'}
            </button>
          </div>
        </div>

        {(error || info) && (
          <div className="message-grid in-panel">
            {error && (
              <article className="message-card message-error">{error}</article>
            )}
            {info && (
              <article className="message-card message-info">{info}</article>
            )}
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Scheduler</h2>
          <span className="muted">Endpoint: /reports/scheduler</span>
        </div>
        {schedulerState ? (
          <>
            <div className="settings-grid">
              <article className="setting-card">
                <span>Enabled</span>
                <strong>{schedulerState.enabled ? 'Yes' : 'No'}</strong>
              </article>
              <article className="setting-card">
                <span>Weekly cadence</span>
                <strong>
                  weekday {schedulerState.weekly_weekday}, {schedulerState.weekly_hour}
                  :00 UTC
                </strong>
              </article>
              <article className="setting-card">
                <span>Tick (s)</span>
                <strong>{schedulerState.tick_seconds}</strong>
              </article>
              <article className="setting-card">
                <span>Retention</span>
                <strong>{schedulerState.retention_days} days</strong>
              </article>
              <article className="setting-card setting-card-wide">
                <span>Default kinds</span>
                <strong>
                  {(schedulerState.default_kinds || []).join(', ') || '-'}
                </strong>
              </article>
              <article className="setting-card">
                <span>Window start</span>
                <strong>
                  {formatTimestamp(schedulerState.current_window_start)}
                </strong>
              </article>
              <article className="setting-card">
                <span>Next window</span>
                <strong>
                  {formatTimestamp(schedulerState.next_window_start)}
                </strong>
              </article>
            </div>
            <div className="table-wrap top-gap">
              <table>
                <thead>
                  <tr>
                    <th>Kind</th>
                    <th>Last run</th>
                    <th>In current window?</th>
                  </tr>
                </thead>
                <tbody>
                  {(schedulerState.last_runs || []).map((row) => (
                    <tr key={row.kind}>
                      <td>
                        <code>{row.kind}</code>
                      </td>
                      <td>{formatTimestamp(row.last_run_at)}</td>
                      <td>{row.in_current_window ? 'yes' : 'no'}</td>
                    </tr>
                  ))}
                  {(schedulerState.last_runs || []).length === 0 && (
                    <tr>
                      <td colSpan={3} className="empty-cell">
                        Nothing scheduled.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p className="muted">Loading scheduler state...</p>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Generate now</h2>
          <span className="muted">Endpoint: POST /reports/generate</span>
        </div>
        <form className="form-stack" onSubmit={handleGenerate}>
          <label className="field-stacked">
            <span className="muted small">Kind</span>
            <select
              value={generateForm.kind}
              onChange={(event) =>
                setGenerateForm((prev) => ({
                  ...prev,
                  kind: event.target.value,
                }))
              }
            >
              {kinds.map((kind) => (
                <option key={kind.name} value={kind.name}>
                  {kind.label}
                </option>
              ))}
            </select>
          </label>
          {selectedKind?.description && (
            <p className="muted small">{selectedKind.description}</p>
          )}
          {selectedKind?.requires_scan_id && (
            <label className="field-stacked">
              <span className="muted small">Scan ID</span>
              <input
                type="text"
                value={generateForm.scan_id}
                onChange={(event) =>
                  setGenerateForm((prev) => ({
                    ...prev,
                    scan_id: event.target.value,
                  }))
                }
                placeholder="paste a scan id from the dashboard..."
              />
            </label>
          )}
          <div className="settings-actions">
            <button
              type="submit"
              className="btn btn-primary"
              disabled={generating}
            >
              {generating ? 'Generating...' : 'Generate report'}
            </button>
          </div>
        </form>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Filters</h2>
        </div>
        <div className="settings-toolbar outcomes-filters">
          <label className="field-stacked">
            <span className="muted small">Kind</span>
            <select
              value={filters.kind}
              onChange={handleFilterChange('kind')}
            >
              <option value="">any</option>
              {kinds.map((kind) => (
                <option key={kind.name} value={kind.name}>
                  {kind.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field-stacked">
            <span className="muted small">Format</span>
            <select
              value={filters.format}
              onChange={handleFilterChange('format')}
            >
              {FORMAT_OPTIONS.map((option) => (
                <option key={option || 'any'} value={option}>
                  {option || 'any'}
                </option>
              ))}
            </select>
          </label>
          <label className="field-stacked">
            <span className="muted small">Status</span>
            <select
              value={filters.status}
              onChange={handleFilterChange('status')}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option || 'any'} value={option}>
                  {option || 'any'}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Persisted reports</h2>
        </div>
        {reports.length === 0 ? (
          <div className="empty-cell">
            <p>
              {loading
                ? 'Loading...'
                : 'No reports match the current filters. Generate one above or run the scheduler to populate this list.'}
            </p>
          </div>
        ) : (
          <div className="table-wrap policies-table">
            <table>
              <thead>
                <tr>
                  <th>Generated</th>
                  <th>Kind</th>
                  <th>Window</th>
                  <th>Format</th>
                  <th>Status</th>
                  <th>Size</th>
                  <th>Filename</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {reports.map((row) => (
                  <tr key={row.report_id}>
                    <td>{formatTimestamp(row.generated_at)}</td>
                    <td>
                      <code>{row.kind}</code>
                    </td>
                    <td>{row.window || '-'}</td>
                    <td>{row.format}</td>
                    <td>
                      <span
                        className={`severity-chip severity-${
                          row.status === 'ok' ? 'low' : 'high'
                        }`}
                      >
                        {row.status}
                      </span>
                    </td>
                    <td>{formatBytes(row.size_bytes)}</td>
                    <td>
                      <code className="fingerprint-cell">{row.filename}</code>
                    </td>
                    <td>
                      <div className="settings-actions">
                        <button
                          type="button"
                          className="btn btn-secondary btn-tight"
                          onClick={() => handleDownload(row)}
                          disabled={row.status !== 'ok'}
                          title={
                            row.status === 'ok'
                              ? 'Download'
                              : 'Failed reports have no downloadable payload'
                          }
                        >
                          Download
                        </button>
                        <button
                          type="button"
                          className="btn btn-secondary btn-tight policies-btn-danger"
                          onClick={() => handleDelete(row)}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="settings-toolbar top-gap">
          <p className="muted small">
            Page {currentPage} / {totalPages}
          </p>
          <div className="settings-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0 || loading}
            >
              Previous
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setPage((p) => p + 1)}
              disabled={(page + 1) * PAGE_SIZE >= total || loading}
            >
              Next
            </button>
          </div>
        </div>
      </section>
    </section>
  )
}
