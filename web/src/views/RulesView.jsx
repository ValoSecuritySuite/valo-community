import { useCallback, useEffect, useState } from 'react'

import { evaluateRules, getRules, reloadRules } from '../api/rules.js'
import JsonContextEditor from '../components/JsonContextEditor.jsx'
import { parseContext } from '../components/jsonContext.js'

const EVAL_PRESETS = [
  {
    label: 'PII / email',
    value: { contains_email: true, severity: 'medium' },
  },
  {
    label: 'Oversized prompt',
    value: { token_count: 4096, severity: 'medium' },
  },
  {
    label: 'Critical severity',
    value: { severity: 'critical', combined_score: 90 },
  },
]

export default function RulesView() {
  const [contextRules, setContextRules] = useState([])
  const [textRules, setTextRules] = useState([])
  const [rulesInfo, setRulesInfo] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)

  const [reloadLoading, setReloadLoading] = useState(false)
  const [reloadDiff, setReloadDiff] = useState(null)

  const [evalContext, setEvalContext] = useState('')
  const [evalLoading, setEvalLoading] = useState(false)
  const [evalError, setEvalError] = useState(null)
  const [evalResult, setEvalResult] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getRules()
      setContextRules(data?.rules || [])
      setTextRules(data?.text_scan_rules || [])
      setRulesInfo(data?.rules_info || null)
    } catch (err) {
      setError(err.message || 'Failed to load rules')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const handleReload = async () => {
    setReloadLoading(true)
    setError(null)
    setReloadDiff(null)
    try {
      const result = await reloadRules()
      setReloadDiff(result?.diff || null)
      setInfo(`Reloaded ${result?.new_rule_count ?? 0} rules from ${result?.rules_path || 'disk'}.`)
      await refresh()
    } catch (err) {
      setError(err.message || 'Failed to reload rules')
    } finally {
      setReloadLoading(false)
    }
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
      const result = await evaluateRules(parsed.value)
      setEvalResult(result)
    } catch (err) {
      setEvalError(err.message || 'Failed to evaluate rules')
    } finally {
      setEvalLoading(false)
    }
  }

  return (
    <section className="rules-view" aria-label="Rules viewer">
      <section className="panel panel-ops">
        <div className="panel-header">
          <h2>Rules Surface</h2>
          <span className="muted">Endpoint: /rules</span>
        </div>

        <div className="settings-toolbar">
          <p className="muted">
            {loading
              ? 'Loading rules...'
              : `${contextRules.length} context rule${contextRules.length === 1 ? '' : 's'}, ${textRules.length} text-scan rule${textRules.length === 1 ? '' : 's'}.`}
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
          </div>
        </div>

        {rulesInfo && (
          <div className="settings-grid top-gap">
            <div className="setting-card setting-card-wide">
              <span>Rules File</span>
              <strong>
                <code>{rulesInfo.filepath}</code>
              </strong>
            </div>
            <div className="setting-card">
              <span>Context Rules</span>
              <strong>{rulesInfo.context_rule_count}</strong>
            </div>
            <div className="setting-card">
              <span>Text-scan Rules</span>
              <strong>{rulesInfo.text_scan_rule_count}</strong>
            </div>
          </div>
        )}

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
          </article>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Context Rules</h2>
          <span className="muted">Used by /analyze stage 3 and /rules/evaluate.</span>
        </div>
        {contextRules.length === 0 ? (
          <p className="muted">No context rules loaded.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Severity</th>
                  <th>Weight</th>
                  <th>Enabled</th>
                  <th>Patterns</th>
                </tr>
              </thead>
              <tbody>
                {contextRules.map((rule) => (
                  <tr key={rule.name}>
                    <td>
                      <code>{rule.name}</code>
                    </td>
                    <td>{rule.severity}</td>
                    <td>{rule.weight}</td>
                    <td>{rule.enabled ? 'yes' : 'no'}</td>
                    <td>{(rule.patterns || []).length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Text-scan Rules</h2>
          <span className="muted">Regex / keyword / entropy detectors run against raw input.</span>
        </div>
        {textRules.length === 0 ? (
          <p className="muted">No text-scan rules loaded.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Family</th>
                  <th>Category</th>
                  <th>Severity</th>
                  <th>Weight</th>
                  <th>Enabled</th>
                </tr>
              </thead>
              <tbody>
                {textRules.map((rule) => (
                  <tr key={rule.id}>
                    <td>
                      <code>{rule.id}</code>
                    </td>
                    <td>{rule.family || '-'}</td>
                    <td>{rule.category}</td>
                    <td>{rule.severity}</td>
                    <td>{rule.weight}</td>
                    <td>{rule.enabled ? 'yes' : 'no'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel panel-ops">
        <div className="panel-header">
          <h2>Ad-hoc Context Rule Evaluation</h2>
          <span className="muted">Endpoint: POST /rules/evaluate</span>
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
            {evalLoading ? 'Evaluating...' : 'Evaluate Rules'}
          </button>
        </div>

        {evalError && <article className="message-card message-error in-panel">{evalError}</article>}

        {evalResult && (
          <div className="top-gap">
            <div className="settings-grid">
              <div className="setting-card">
                <span>Total Score</span>
                <strong>{Number(evalResult.total_score || 0).toFixed(2)}</strong>
              </div>
              <div className="setting-card">
                <span>Passed</span>
                <strong>{evalResult.passed_count || 0}</strong>
              </div>
              <div className="setting-card">
                <span>Failed</span>
                <strong>{evalResult.failed_count || 0}</strong>
              </div>
            </div>

            <div className="table-wrap top-gap">
              <table>
                <thead>
                  <tr>
                    <th>Rule</th>
                    <th>Severity</th>
                    <th>Weight</th>
                    <th>Matched</th>
                  </tr>
                </thead>
                <tbody>
                  {(evalResult.matched_rules || []).map((rule) => (
                    <tr
                      key={rule.rule_name}
                      className={rule.matched ? 'table-row-matched' : ''}
                    >
                      <td>
                        <code>{rule.rule_name}</code>
                      </td>
                      <td>{rule.severity}</td>
                      <td>{rule.weight}</td>
                      <td>{rule.matched ? 'yes' : 'no'}</td>
                    </tr>
                  ))}
                  {(evalResult.matched_rules || []).length === 0 && (
                    <tr>
                      <td colSpan={4} className="empty-cell">
                        No rules evaluated for this context.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    </section>
  )
}
