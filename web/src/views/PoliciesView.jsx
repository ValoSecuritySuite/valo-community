import { useCallback, useEffect, useState } from 'react'

import {
  deletePolicy,
  evaluatePolicies,
  listPolicies,
  reloadPolicies,
} from '../api/policies.js'
import JsonContextEditor from '../components/JsonContextEditor.jsx'
import { parseContext } from '../components/jsonContext.js'
import PolicyBadge from '../components/PolicyBadge.jsx'
import PolicyDecisionsPanel from '../components/PolicyDecisionsPanel.jsx'
import PolicyEditorModal from '../components/PolicyEditorModal.jsx'

const EVAL_PRESETS = [
  {
    label: 'High-risk score',
    value: { combined_score: 90, matched_rule_ids: [] },
  },
  {
    label: 'PII signal',
    value: { contains_email: true, combined_score: 25 },
  },
  {
    label: 'Secret leak',
    value: {
      combined_score: 60,
      matched_rule_ids: ['secret_signal'],
      contains_secret_keyword: true,
    },
  },
]

function formatList(values) {
  if (!values || values.length === 0) return '-'
  return values.join(', ')
}

export default function PoliciesView() {
  const [policies, setPolicies] = useState([])
  const [fingerprints, setFingerprints] = useState({})
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)

  const [editorState, setEditorState] = useState({ open: false, mode: 'create', policy: null })
  const [confirmDelete, setConfirmDelete] = useState(null)

  const [evalContext, setEvalContext] = useState('')
  const [evalLoading, setEvalLoading] = useState(false)
  const [evalError, setEvalError] = useState(null)
  const [evalResult, setEvalResult] = useState(null)

  const [reloadLoading, setReloadLoading] = useState(false)
  const [reloadDiff, setReloadDiff] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listPolicies()
      setPolicies(data?.policies || [])
      setFingerprints(data?.fingerprints || {})
      setTotal(Number(data?.total || 0))
    } catch (err) {
      setError(err.message || 'Failed to load policies')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const handleReload = async () => {
    setReloadLoading(true)
    setReloadDiff(null)
    setError(null)
    try {
      const result = await reloadPolicies()
      setReloadDiff(result?.diff || null)
      setInfo(
        `Reloaded ${result?.new_policy_count ?? 0} polic${(result?.new_policy_count ?? 0) === 1 ? 'y' : 'ies'} from ${result?.policies_path || 'disk'}.`,
      )
      await refresh()
    } catch (err) {
      setError(err.message || 'Failed to reload policies')
    } finally {
      setReloadLoading(false)
    }
  }

  const handleDelete = async (policyId) => {
    setError(null)
    try {
      await deletePolicy(policyId)
      setInfo(`Deleted policy ${policyId}.`)
      setConfirmDelete(null)
      await refresh()
    } catch (err) {
      setError(err.message || 'Failed to delete policy')
    }
  }

  const handleSaved = (saved) => {
    setEditorState({ open: false, mode: 'create', policy: null })
    setInfo(`Saved policy ${saved?.id || ''}.`)
    refresh()
  }

  const handleEvaluate = async () => {
    setEvalError(null)
    setEvalResult(null)
    const parsed = parseContext(evalContext)
    if (!parsed.ok) {
      setEvalError(`Invalid context: ${parsed.error}`)
      return
    }
    setEvalLoading(true)
    try {
      const result = await evaluatePolicies(parsed.value)
      setEvalResult(result)
    } catch (err) {
      setEvalError(err.message || 'Failed to evaluate policies')
    } finally {
      setEvalLoading(false)
    }
  }

  return (
    <section className="policies-view" aria-label="Governance Policies">
      <section className="panel panel-ops">
        <div className="panel-header">
          <h2>Governance Policies</h2>
          <span className="muted">Endpoint: /policies</span>
        </div>

        <div className="settings-toolbar">
          <p className="muted">
            {loading ? 'Loading policies...' : `${total} polic${total === 1 ? 'y' : 'ies'} loaded.`}
          </p>
          <div className="settings-actions">
            <button type="button" className="btn btn-secondary" onClick={refresh} disabled={loading}>
              {loading ? 'Refreshing...' : 'Refresh'}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleReload}
              disabled={reloadLoading}
            >
              {reloadLoading ? 'Reloading...' : 'Reload from Disk'}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setEditorState({ open: true, mode: 'create', policy: null })}
            >
              New Policy
            </button>
          </div>
        </div>

        {(error || info) && (
          <div className="message-grid in-panel">
            {error && <article className="message-card message-error">{error}</article>}
            {info && <article className="message-card message-info">{info}</article>}
          </div>
        )}

        {reloadDiff && (
          <article className="diff-toast in-panel">
            <strong>Reload diff:</strong>
            <span className="diff-pill diff-added">added {reloadDiff.added?.length || 0}</span>
            <span className="diff-pill diff-removed">
              removed {reloadDiff.removed?.length || 0}
            </span>
            <span className="diff-pill diff-changed">
              changed {reloadDiff.changed?.length || 0}
            </span>
            <span className="diff-pill diff-unchanged">
              unchanged {Number(reloadDiff.unchanged || 0)}
            </span>
            {(reloadDiff.added?.length || 0) > 0 && (
              <p className="muted">Added: {formatList(reloadDiff.added)}</p>
            )}
            {(reloadDiff.removed?.length || 0) > 0 && (
              <p className="muted">Removed: {formatList(reloadDiff.removed)}</p>
            )}
            {(reloadDiff.changed?.length || 0) > 0 && (
              <p className="muted">Changed: {formatList(reloadDiff.changed)}</p>
            )}
          </article>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Policy Catalog</h2>
        </div>

        {policies.length === 0 ? (
          <div className="empty-cell">
            <p>No policies on disk yet.</p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setEditorState({ open: true, mode: 'create', policy: null })}
            >
              Author your first policy
            </button>
          </div>
        ) : (
          <div className="table-wrap policies-table">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Name</th>
                  <th>Decision</th>
                  <th>Enabled</th>
                  <th>Enforced</th>
                  <th>Conditions</th>
                  <th>Tags</th>
                  <th>Fingerprint</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {policies.map((policy) => (
                  <tr key={policy.id}>
                    <td>
                      <code>{policy.id}</code>
                    </td>
                    <td>{policy.name}</td>
                    <td>
                      <PolicyBadge
                        decision={policy.then?.decision}
                        severity={policy.then?.severity}
                      />
                    </td>
                    <td>{policy.enabled ? 'yes' : 'no'}</td>
                    <td>
                      {policy.enforce === false ? (
                        <span className="severity-chip severity-medium">monitor</span>
                      ) : (
                        <span className="severity-chip severity-low">enforced</span>
                      )}
                    </td>
                    <td>{policy.when?.length || 0}</td>
                    <td>
                      <div className="tag-list">
                        {(policy.tags || []).map((tag) => (
                          <span className="tag-item" key={`${policy.id}-tag-${tag}`}>
                            {tag}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td>
                      <code className="fingerprint-cell">
                        {(fingerprints[policy.id] || '').slice(0, 8) || '-'}
                      </code>
                    </td>
                    <td className="policies-actions">
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={() => setEditorState({ open: true, mode: 'edit', policy })}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary policies-btn-danger"
                        onClick={() => setConfirmDelete(policy)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel panel-ops">
        <div className="panel-header">
          <h2>Ad-hoc Policy Evaluation</h2>
          <span className="muted">Endpoint: POST /policies/evaluate</span>
        </div>

        <JsonContextEditor
          value={evalContext}
          onChange={setEvalContext}
          presets={EVAL_PRESETS}
          rows={8}
        />

        <div className="field-actions top-gap">
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleEvaluate}
            disabled={evalLoading}
          >
            {evalLoading ? 'Evaluating...' : 'Evaluate Policies'}
          </button>
        </div>

        {evalError && <article className="message-card message-error in-panel">{evalError}</article>}
      </section>

      {evalResult && (
        <PolicyDecisionsPanel
          decisions={evalResult.decisions || []}
          finalDecision={evalResult.final_decision || 'allow'}
          title="Ad-hoc Evaluation Result"
        />
      )}

      {editorState.open && (
        <PolicyEditorModal
          mode={editorState.mode}
          policy={editorState.policy}
          onClose={() => setEditorState({ open: false, mode: 'create', policy: null })}
          onSaved={handleSaved}
        />
      )}

      {confirmDelete && (
        <div className="modal-backdrop" onClick={() => setConfirmDelete(null)}>
          <div
            className="modal"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
            aria-modal="true"
          >
            <div className="modal-header">
              <h2>Delete policy {confirmDelete.id}?</h2>
            </div>
            <p>
              This removes <code>{confirmDelete.id}</code> from disk. The change cannot be undone
              from the UI.
            </p>
            <div className="settings-actions top-gap">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setConfirmDelete(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary policies-btn-danger"
                onClick={() => handleDelete(confirmDelete.id)}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
