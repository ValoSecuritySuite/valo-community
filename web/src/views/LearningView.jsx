import { useCallback, useEffect, useState } from 'react'

import {
  acceptProposal,
  listProposals,
  refreshLearning,
  rejectProposal,
} from '../api/learning.js'

const STATUS_FILTERS = ['', 'pending', 'accepted', 'rejected', 'applied']
const KIND_FILTERS = ['', 'policy', 'playbook']

function statusChipClass(status) {
  switch (status) {
    case 'pending':
      return 'severity-chip severity-medium'
    case 'rejected':
      return 'severity-chip severity-low'
    case 'applied':
      return 'severity-chip severity-info'
    case 'accepted':
      return 'severity-chip severity-low'
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

function formatTimestamp(value) {
  if (!value) return '-'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString()
}

function formatPercent(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-'
  return `${(value * 100).toFixed(1)}%`
}

export default function LearningView() {
  const [proposals, setProposals] = useState([])
  const [filters, setFilters] = useState({ kind: '', status: 'pending' })
  const [selectedId, setSelectedId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [reviewerInput, setReviewerInput] = useState({ reviewer: '', reason: '' })
  const [refreshing, setRefreshing] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listProposals({
        kind: filters.kind || undefined,
        status: filters.status || undefined,
      })
      const list = data?.proposals || []
      setProposals(list)
      // Keep selection stable when possible.
      if (list.length === 0) {
        setSelectedId(null)
      } else if (!list.some((p) => p.proposal_id === selectedId)) {
        setSelectedId(list[0].proposal_id)
      }
    } catch (err) {
      setError(err.message || 'Failed to load proposals')
    } finally {
      setLoading(false)
    }
  }, [filters, selectedId])

  useEffect(() => {
    refresh()
  }, [refresh])

  const handleRefiner = async () => {
    setRefreshing(true)
    setError(null)
    setInfo(null)
    try {
      const result = await refreshLearning()
      setInfo(
        `Refiner produced ${result?.proposals_generated ?? 0} proposal${result?.proposals_generated === 1 ? '' : 's'}.`,
      )
      await refresh()
    } catch (err) {
      if (err.status === 503) {
        setError(
          'Learning loop is disabled. Set APP_LEARNING_LOOP_ENABLED=true and restart the backend.',
        )
      } else {
        setError(err.message || 'Failed to run refiner')
      }
    } finally {
      setRefreshing(false)
    }
  }

  const selected = proposals.find((p) => p.proposal_id === selectedId) || null

  const handleAccept = async () => {
    if (!selected) return
    setActionLoading(true)
    setError(null)
    setInfo(null)
    try {
      const result = await acceptProposal(selected.proposal_id, {
        reviewer: reviewerInput.reviewer || null,
        reason: reviewerInput.reason || null,
      })
      setInfo(
        `Accepted ${selected.heuristic} on ${selected.rule_kind} ${selected.rule_id}. Live rule updated.`,
      )
      setReviewerInput({ reviewer: '', reason: '' })
      await refresh()
      // Show the just-accepted proposal in detail.
      setSelectedId(result?.proposal?.proposal_id || selected.proposal_id)
    } catch (err) {
      setError(err.message || 'Failed to accept proposal')
    } finally {
      setActionLoading(false)
    }
  }

  const handleReject = async () => {
    if (!selected) return
    setActionLoading(true)
    setError(null)
    setInfo(null)
    try {
      await rejectProposal(selected.proposal_id, {
        reviewer: reviewerInput.reviewer || null,
        reason: reviewerInput.reason || null,
      })
      setInfo(`Rejected ${selected.proposal_id}.`)
      setReviewerInput({ reviewer: '', reason: '' })
      await refresh()
    } catch (err) {
      setError(err.message || 'Failed to reject proposal')
    } finally {
      setActionLoading(false)
    }
  }

  return (
    <section className="learning-view" aria-label="Phase 4 Learning Loop">
      <section className="panel panel-ops">
        <div className="panel-header">
          <h2>Learning Loop</h2>
          <span className="muted">Endpoint: /learning</span>
        </div>
        <p className="muted">
          The refiner reads labeled outcomes, scores each rule, and proposes
          tightening or disabling the noisy ones. Nothing changes a live rule
          until you click Accept.
        </p>

        <div className="settings-toolbar">
          <div className="settings-actions">
            <label className="field-stacked">
              <span className="muted small">Kind</span>
              <select
                value={filters.kind}
                onChange={(event) => {
                  setSelectedId(null)
                  setFilters((prev) => ({ ...prev, kind: event.target.value }))
                }}
              >
                {KIND_FILTERS.map((value) => (
                  <option key={`kind-${value || 'any'}`} value={value}>
                    {value || 'any'}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-stacked">
              <span className="muted small">Status</span>
              <select
                value={filters.status}
                onChange={(event) => {
                  setSelectedId(null)
                  setFilters((prev) => ({ ...prev, status: event.target.value }))
                }}
              >
                {STATUS_FILTERS.map((value) => (
                  <option key={`status-${value || 'any'}`} value={value}>
                    {value || 'any'}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="settings-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={refresh}
              disabled={loading}
            >
              {loading ? 'Refreshing...' : 'Refresh list'}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleRefiner}
              disabled={refreshing}
            >
              {refreshing ? 'Running refiner...' : 'Run refiner now'}
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

      <section className="learning-grid">
        <section className="panel learning-list">
          <div className="panel-header">
            <h2>Proposals</h2>
            <span className="muted small">{proposals.length} total</span>
          </div>
          {proposals.length === 0 ? (
            <div className="empty-cell">
              <p>
                {loading
                  ? 'Loading...'
                  : 'No proposals match the current filter. Run the refiner or label more outcomes to generate suggestions.'}
              </p>
            </div>
          ) : (
            <ul className="learning-proposal-list">
              {proposals.map((proposal) => (
                <li
                  key={proposal.proposal_id}
                  className={
                    selectedId === proposal.proposal_id
                      ? 'learning-proposal-item learning-proposal-item-active'
                      : 'learning-proposal-item'
                  }
                >
                  <button
                    type="button"
                    className="learning-proposal-button"
                    onClick={() => setSelectedId(proposal.proposal_id)}
                  >
                    <div className="learning-proposal-header">
                      <span className="tag-item">{proposal.rule_kind}</span>
                      <span className={statusChipClass(proposal.status)}>
                        {proposal.status}
                      </span>
                    </div>
                    <p className="learning-proposal-title">
                      <code>{proposal.rule_id}</code>
                    </p>
                    <p className="muted small">{proposal.heuristic}</p>
                    <div className="learning-proposal-meta">
                      <span className={fpRateClass(proposal.fp_rate)}>
                        FP {formatPercent(proposal.fp_rate)}
                      </span>
                      <span className="muted small">
                        n={proposal.sample_size}
                      </span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="panel learning-detail">
          {!selected ? (
            <div className="empty-cell">
              <p>Select a proposal on the left to see its diff and stats.</p>
            </div>
          ) : (
            <>
              <div className="panel-header">
                <h2>{selected.proposal_id}</h2>
                <span className={statusChipClass(selected.status)}>
                  {selected.status}
                </span>
              </div>

              <div className="learning-summary">
                <p>{selected.summary}</p>
                <div className="settings-actions">
                  <span className="muted small">
                    Created {formatTimestamp(selected.created_at)}
                  </span>
                  <span className="muted small">
                    Updated {formatTimestamp(selected.updated_at)}
                  </span>
                  <span className={fpRateClass(selected.fp_rate)}>
                    FP rate {formatPercent(selected.fp_rate)}
                  </span>
                  <span className="muted small">
                    Sample size {selected.sample_size}
                  </span>
                </div>
                {(selected.reviewer || selected.reviewer_reason) && (
                  <p className="muted small">
                    Reviewer: <strong>{selected.reviewer || 'unknown'}</strong>
                    {selected.reviewer_reason
                      ? ` - ${selected.reviewer_reason}`
                      : ''}
                  </p>
                )}
              </div>

              <section className="panel-section">
                <h3 className="muted small">Diff</h3>
                {(selected.diff_summary || []).length === 0 ? (
                  <p className="muted small">No fields changed.</p>
                ) : (
                  <ul className="learning-diff">
                    {selected.diff_summary.map((line, idx) => (
                      <li key={`diff-${idx}`}>
                        <code>{line}</code>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="panel-section">
                <h3 className="muted small">Supporting stats</h3>
                <pre className="learning-yaml">
                  {JSON.stringify(selected.stats, null, 2)}
                </pre>
              </section>

              <section className="panel-section learning-yaml-grid">
                <div>
                  <h3 className="muted small">Current YAML</h3>
                  <pre className="learning-yaml">
                    {JSON.stringify(selected.current_yaml, null, 2)}
                  </pre>
                </div>
                <div>
                  <h3 className="muted small">Proposed YAML</h3>
                  <pre className="learning-yaml">
                    {JSON.stringify(selected.proposed_yaml, null, 2)}
                  </pre>
                </div>
              </section>

              {selected.status === 'pending' && (
                <section className="panel-section">
                  <h3 className="muted small">Review</h3>
                  <div className="settings-toolbar outcomes-filters">
                    <label className="field-stacked">
                      <span className="muted small">Reviewer</span>
                      <input
                        type="text"
                        value={reviewerInput.reviewer}
                        onChange={(event) =>
                          setReviewerInput((prev) => ({
                            ...prev,
                            reviewer: event.target.value,
                          }))
                        }
                        placeholder="alice, soc-shift-1, ..."
                      />
                    </label>
                    <label className="field-stacked">
                      <span className="muted small">Reason</span>
                      <input
                        type="text"
                        value={reviewerInput.reason}
                        onChange={(event) =>
                          setReviewerInput((prev) => ({
                            ...prev,
                            reason: event.target.value,
                          }))
                        }
                        placeholder="optional rationale"
                      />
                    </label>
                  </div>
                  <div className="settings-actions top-gap">
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={handleReject}
                      disabled={actionLoading}
                    >
                      {actionLoading ? 'Working...' : 'Reject'}
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={handleAccept}
                      disabled={actionLoading}
                    >
                      {actionLoading ? 'Working...' : 'Accept and apply'}
                    </button>
                  </div>
                  <p className="muted small">
                    Accepting writes <code>proposed_yaml</code> through the
                    live store ({selected.rule_kind}). The change is atomic
                    and visible to the engine on the next request.
                  </p>
                </section>
              )}
            </>
          )}
        </section>
      </section>
    </section>
  )
}
