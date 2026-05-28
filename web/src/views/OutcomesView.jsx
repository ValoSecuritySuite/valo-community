import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  OUTCOME_LABELS,
  labelOutcome,
  listOutcomes,
  outcomeStats,
} from '../api/outcomes.js'

const PAGE_SIZE = 25

const LABEL_LOOKUP = OUTCOME_LABELS.reduce((acc, value) => {
  acc[value] = value.replace(/_/g, ' ')
  return acc
}, {})

function severityChipClass(label) {
  switch (label) {
    case 'false_positive':
    case 'benign_block':
      return 'severity-chip severity-medium'
    case 'malicious_allow':
      return 'severity-chip severity-high'
    case 'true_positive':
      return 'severity-chip severity-low'
    case 'suppressed':
    case 'dismissed':
      return 'severity-chip severity-info'
    default:
      return 'severity-chip'
  }
}

function fpRateClass(rate) {
  if (rate >= 0.3) return 'severity-chip severity-high'
  if (rate >= 0.05) return 'severity-chip severity-medium'
  if (rate > 0) return 'severity-chip severity-low'
  return 'severity-chip severity-info'
}

function formatPercent(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-'
  return `${(value * 100).toFixed(1)}%`
}

function formatTimestamp(value) {
  if (!value) return '-'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString()
}

export default function OutcomesView() {
  const [outcomes, setOutcomes] = useState([])
  const [total, setTotal] = useState(0)
  const [persisted, setPersisted] = useState(0)
  const [page, setPage] = useState(0)
  const [filters, setFilters] = useState({
    source: '',
    label: '',
    has_label: '',
    matched_only: '',
    trace_id: '',
  })

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)

  const [stats, setStats] = useState({ policies: [], playbooks: [], total_outcomes: 0 })
  const [statsLoading, setStatsLoading] = useState(false)

  const [labelDrawer, setLabelDrawer] = useState(null) // outcome row or null
  const [labelForm, setLabelForm] = useState({
    label: 'true_positive',
    reason: '',
    labeled_by: '',
  })
  const [labelSaving, setLabelSaving] = useState(false)

  const queryParams = useMemo(() => {
    const params = { limit: PAGE_SIZE, offset: page * PAGE_SIZE }
    if (filters.source) params.source = filters.source
    if (filters.label) params.label = filters.label
    if (filters.has_label === 'yes') params.has_label = true
    if (filters.has_label === 'no') params.has_label = false
    if (filters.matched_only === 'yes') params.matched_only = true
    if (filters.matched_only === 'no') params.matched_only = false
    if (filters.trace_id) params.trace_id = filters.trace_id.trim()
    return params
  }, [filters, page])

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listOutcomes(queryParams)
      setOutcomes(data?.outcomes || [])
      setTotal(Number(data?.total || 0))
      setPersisted(Number(data?.persisted || 0))
    } catch (err) {
      setError(err.message || 'Failed to load outcomes')
    } finally {
      setLoading(false)
    }
  }, [queryParams])

  const refreshStats = useCallback(async () => {
    setStatsLoading(true)
    try {
      const data = await outcomeStats()
      setStats({
        policies: data?.policies || [],
        playbooks: data?.playbooks || [],
        total_outcomes: Number(data?.total_outcomes || 0),
      })
    } catch (err) {
      setError(err.message || 'Failed to load outcome stats')
    } finally {
      setStatsLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    refreshStats()
  }, [refreshStats])

  const handleFilterChange = (key) => (event) => {
    setPage(0)
    setFilters((prev) => ({ ...prev, [key]: event.target.value }))
  }

  const openLabelDrawer = (outcome) => {
    setLabelDrawer(outcome)
    setLabelForm({
      label: outcome.label || 'true_positive',
      reason: outcome.label_reason || '',
      labeled_by: outcome.labeled_by || '',
    })
  }

  const closeLabelDrawer = () => {
    setLabelDrawer(null)
    setLabelSaving(false)
  }

  const handleLabelSubmit = async (event) => {
    event.preventDefault()
    if (!labelDrawer) return
    setLabelSaving(true)
    setError(null)
    setInfo(null)
    try {
      await labelOutcome(labelDrawer.trace_id || labelDrawer.outcome_id, {
        label: labelForm.label,
        reason: labelForm.reason || null,
        labeled_by: labelForm.labeled_by || null,
        outcome_id: labelDrawer.outcome_id,
      })
      setInfo(
        `Labeled outcome ${labelDrawer.outcome_id.slice(0, 8)} as ${labelForm.label.replace(/_/g, ' ')}.`,
      )
      closeLabelDrawer()
      await refresh()
      await refreshStats()
    } catch (err) {
      setError(err.message || 'Failed to label outcome')
    } finally {
      setLabelSaving(false)
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const currentPage = Math.min(page + 1, totalPages)

  return (
    <section className="outcomes-view" aria-label="Phase 4 Outcomes">
      <section className="panel panel-ops">
        <div className="panel-header">
          <h2>Outcomes</h2>
          <span className="muted">Endpoint: /outcomes</span>
        </div>
        <p className="muted">
          Every playbook execution that fires lands here for analyst review.
          Labels are the input the refiner uses to propose rule changes.
        </p>

        <div className="settings-toolbar">
          <p className="muted">
            {loading
              ? 'Loading outcomes...'
              : `Showing ${outcomes.length} of ${total} matching (page ${currentPage} of ${totalPages}, ${persisted} persisted total).`}
          </p>
          <div className="settings-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                refresh()
                refreshStats()
              }}
              disabled={loading || statsLoading}
            >
              {loading || statsLoading ? 'Refreshing...' : 'Refresh'}
            </button>
          </div>
        </div>

        {(error || info) && (
          <div className="message-grid in-panel">
            {error && <article className="message-card message-error">{error}</article>}
            {info && <article className="message-card message-info">{info}</article>}
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Filters</h2>
        </div>
        <div className="settings-toolbar outcomes-filters">
          <label className="field-stacked">
            <span className="muted small">Source</span>
            <input
              type="text"
              value={filters.source}
              onChange={handleFilterChange('source')}
              placeholder="valo, llmshadow, ..."
            />
          </label>
          <label className="field-stacked">
            <span className="muted small">Label</span>
            <select
              value={filters.label}
              onChange={handleFilterChange('label')}
            >
              <option value="">any</option>
              {OUTCOME_LABELS.map((label) => (
                <option key={label} value={label}>
                  {LABEL_LOOKUP[label]}
                </option>
              ))}
            </select>
          </label>
          <label className="field-stacked">
            <span className="muted small">Has label?</span>
            <select
              value={filters.has_label}
              onChange={handleFilterChange('has_label')}
            >
              <option value="">any</option>
              <option value="yes">labeled</option>
              <option value="no">unlabeled</option>
            </select>
          </label>
          <label className="field-stacked">
            <span className="muted small">Matched a playbook?</span>
            <select
              value={filters.matched_only}
              onChange={handleFilterChange('matched_only')}
            >
              <option value="">any</option>
              <option value="yes">matched</option>
              <option value="no">no match</option>
            </select>
          </label>
          <label className="field-stacked">
            <span className="muted small">Trace id</span>
            <input
              type="text"
              value={filters.trace_id}
              onChange={handleFilterChange('trace_id')}
              placeholder="trace-..."
            />
          </label>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Recent Outcomes</h2>
        </div>

        {outcomes.length === 0 ? (
          <div className="empty-cell">
            <p>
              {loading
                ? 'Loading...'
                : 'No outcomes match the current filters. Generate playbook traffic or post via /outcomes/ingest to populate this list.'}
            </p>
          </div>
        ) : (
          <div className="table-wrap policies-table">
            <table>
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Source</th>
                  <th>Severity</th>
                  <th>Decision</th>
                  <th>Matched playbooks</th>
                  <th>Matched policies</th>
                  <th>Label</th>
                  <th>Trace id</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {outcomes.map((outcome) => (
                  <tr key={outcome.outcome_id}>
                    <td>{formatTimestamp(outcome.started_at)}</td>
                    <td>
                      <code>{outcome.source}</code>
                    </td>
                    <td>{outcome.severity || '-'}</td>
                    <td>{outcome.decision || '-'}</td>
                    <td>
                      <div className="tag-list">
                        {(outcome.matched_playbook_ids || []).map((id) => (
                          <span
                            className="tag-item"
                            key={`${outcome.outcome_id}-pb-${id}`}
                          >
                            {id}
                          </span>
                        ))}
                        {(outcome.matched_playbook_ids || []).length === 0 && '-'}
                      </div>
                    </td>
                    <td>
                      <div className="tag-list">
                        {(outcome.matched_policy_ids || []).map((id) => (
                          <span
                            className="tag-item"
                            key={`${outcome.outcome_id}-pol-${id}`}
                          >
                            {id}
                          </span>
                        ))}
                        {(outcome.matched_policy_ids || []).length === 0 && '-'}
                      </div>
                    </td>
                    <td>
                      {outcome.label ? (
                        <span className={severityChipClass(outcome.label)}>
                          {LABEL_LOOKUP[outcome.label] || outcome.label}
                        </span>
                      ) : (
                        <span className="muted small">unlabeled</span>
                      )}
                    </td>
                    <td>
                      <code className="fingerprint-cell">
                        {(outcome.trace_id || '').slice(0, 12) || '-'}
                      </code>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={() => openLabelDrawer(outcome)}
                      >
                        {outcome.label ? 'Re-label' : 'Label'}
                      </button>
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

      <section className="panel">
        <div className="panel-header">
          <h2>Per-rule stats</h2>
          <span className="muted">Endpoint: /outcomes/stats</span>
        </div>
        {statsLoading ? (
          <p className="muted">Loading stats...</p>
        ) : (
          <div className="outcomes-stats-grid">
            <div>
              <h3 className="muted small">Playbooks</h3>
              {stats.playbooks.length === 0 ? (
                <div className="empty-cell">
                  <p>No labeled playbook outcomes yet.</p>
                </div>
              ) : (
                <div className="table-wrap policies-table">
                  <table>
                    <thead>
                      <tr>
                        <th>Playbook</th>
                        <th>Total</th>
                        <th>Labeled</th>
                        <th>FP</th>
                        <th>TP</th>
                        <th>FP rate</th>
                        <th>Last labeled</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.playbooks.map((row) => (
                        <tr key={`pb-${row.rule_id}`}>
                          <td>
                            <code>{row.rule_id}</code>
                          </td>
                          <td>{row.total}</td>
                          <td>{row.labeled}</td>
                          <td>{row.false_positives + row.benign_blocks}</td>
                          <td>{row.true_positives}</td>
                          <td>
                            <span className={fpRateClass(row.fp_rate)}>
                              {formatPercent(row.fp_rate)}
                            </span>
                          </td>
                          <td>{formatTimestamp(row.last_label_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <div>
              <h3 className="muted small">Policies</h3>
              {stats.policies.length === 0 ? (
                <div className="empty-cell">
                  <p>No labeled policy outcomes yet.</p>
                </div>
              ) : (
                <div className="table-wrap policies-table">
                  <table>
                    <thead>
                      <tr>
                        <th>Policy</th>
                        <th>Total</th>
                        <th>Labeled</th>
                        <th>FP</th>
                        <th>TP</th>
                        <th>FP rate</th>
                        <th>Last labeled</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.policies.map((row) => (
                        <tr key={`pol-${row.rule_id}`}>
                          <td>
                            <code>{row.rule_id}</code>
                          </td>
                          <td>{row.total}</td>
                          <td>{row.labeled}</td>
                          <td>{row.false_positives + row.benign_blocks}</td>
                          <td>{row.true_positives}</td>
                          <td>
                            <span className={fpRateClass(row.fp_rate)}>
                              {formatPercent(row.fp_rate)}
                            </span>
                          </td>
                          <td>{formatTimestamp(row.last_label_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      {labelDrawer && (
        <div className="modal-backdrop" onClick={closeLabelDrawer}>
          <div
            className="modal"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
            aria-modal="true"
          >
            <div className="modal-header">
              <h2>Label outcome</h2>
              <p className="muted small">
                <code>{labelDrawer.outcome_id}</code>
              </p>
            </div>
            <form onSubmit={handleLabelSubmit} className="form-stack">
              <label className="field-stacked">
                <span className="muted small">Label</span>
                <select
                  value={labelForm.label}
                  onChange={(event) =>
                    setLabelForm((prev) => ({
                      ...prev,
                      label: event.target.value,
                    }))
                  }
                >
                  {OUTCOME_LABELS.map((label) => (
                    <option key={label} value={label}>
                      {LABEL_LOOKUP[label]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field-stacked">
                <span className="muted small">Reason (optional)</span>
                <input
                  type="text"
                  value={labelForm.reason}
                  onChange={(event) =>
                    setLabelForm((prev) => ({
                      ...prev,
                      reason: event.target.value,
                    }))
                  }
                  placeholder="why is this true / false / suppressed?"
                />
              </label>
              <label className="field-stacked">
                <span className="muted small">Labeled by (optional)</span>
                <input
                  type="text"
                  value={labelForm.labeled_by}
                  onChange={(event) =>
                    setLabelForm((prev) => ({
                      ...prev,
                      labeled_by: event.target.value,
                    }))
                  }
                  placeholder="analyst id, alice, soc-shift-1, ..."
                />
              </label>

              <div className="settings-actions top-gap">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={closeLabelDrawer}
                  disabled={labelSaving}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={labelSaving}
                >
                  {labelSaving ? 'Saving...' : 'Save label'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  )
}
