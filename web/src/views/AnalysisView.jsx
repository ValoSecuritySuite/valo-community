import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { analyzePrompt, downloadFromResponse, downloadScanPdf } from '../api/scan.js'
import PolicyBadge from '../components/PolicyBadge.jsx'
import PolicyDecisionsPanel from '../components/PolicyDecisionsPanel.jsx'
import { clipText, copyToClipboard, formatNumber, formatScore, triggerDownload } from '../lib/format.js'

function BlockedByValoPanel({ error, onClear }) {
  const [copied, setCopied] = useState(false)
  const detail = error?.detail || {}
  const decisions = Array.isArray(detail.decisions) ? detail.decisions : []
  const matchedIds = Array.isArray(detail.matched_policy_ids)
    ? detail.matched_policy_ids
    : []
  const traceId = detail.trace_id || ''
  const finalDecision = detail.final_decision || 'deny'
  const message =
    error?.message || 'Request blocked by Valo governance policy.'

  return (
    <div className="view-stack">
      <section className="panel panel-blocked">
        <div className="panel-header">
          <div>
            <h2>Blocked by Valo</h2>
            <p className="muted">
              Your prompt was rejected before it reached the model. The
              firewall returned a 403 with an audit trail; nothing was sent
              upstream.
            </p>
          </div>
          <PolicyBadge decision={finalDecision} size="lg" />
        </div>

        <p className="blocked-message">{message}</p>

        <div className="blocked-meta">
          <div className="blocked-meta-row">
            <span className="muted small">Final decision</span>
            <strong className="upper">{finalDecision}</strong>
          </div>
          {matchedIds.length > 0 && (
            <div className="blocked-meta-row">
              <span className="muted small">Matched policies</span>
              <div className="tag-list">
                {matchedIds.map((pid) => (
                  <span key={pid} className="tag-item tag-item-deny">
                    {pid}
                  </span>
                ))}
              </div>
            </div>
          )}
          {traceId && (
            <div className="blocked-meta-row">
              <span className="muted small">Trace ID</span>
              <div className="trace-line">
                <code>{traceId}</code>
                <button
                  type="button"
                  className="btn btn-secondary btn-tight"
                  onClick={async () => {
                    const ok = await copyToClipboard(traceId)
                    if (ok) {
                      setCopied(true)
                      setTimeout(() => setCopied(false), 1500)
                    }
                  }}
                >
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="blocked-actions">
          <button type="button" className="btn btn-primary" onClick={onClear}>
            Edit prompt and retry
          </button>
        </div>
      </section>

      {decisions.length > 0 && (
        <PolicyDecisionsPanel
          decisions={decisions}
          finalDecision={finalDecision}
          traceId={traceId}
          title="Why it was blocked"
          emptyHint="No policy detail returned with the block envelope."
        />
      )}

      <section className="panel panel-muted">
        <div className="panel-header">
          <h3>What you can do</h3>
        </div>
        <ul className="blocked-tips">
          <li>
            Rewrite the prompt to remove instruction-override or system-prompt
            leakage patterns.
          </li>
          <li>
            If the block is a false positive, reduce the matched policy's
            severity or add an exception under <code>/policies</code>.
          </li>
          <li>
            Share the trace id above with the SOC; the full audit record is in{' '}
            <code>/enforcement/events</code>.
          </li>
        </ul>
      </section>
    </div>
  )
}

export default function AnalysisView() {
  const queryClient = useQueryClient()
  const [prompt, setPrompt] = useState('')
  const [target, setTarget] = useState('web-ui')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [errorObj, setErrorObj] = useState(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState(null)

  const mutation = useMutation({
    mutationFn: analyzePrompt,
    onSuccess: (data) => {
      setResult(data)
      setError(null)
      setErrorObj(null)
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['enforcement'] })
    },
    onError: (err) => {
      setResult(null)
      setError(err?.message || 'Failed to run scan')
      setErrorObj(err || null)
    },
  })

  const isPolicyDenied =
    errorObj?.status === 403 ||
    errorObj?.code === 'PolicyDenied' ||
    errorObj?.detail?.final_decision === 'deny'

  const submit = (event) => {
    event.preventDefault()
    if (!prompt.trim()) {
      setError('Enter a prompt before running a scan.')
      setErrorObj(null)
      return
    }
    mutation.mutate({ prompt: prompt.trim(), target: target.trim() || 'web-ui' })
  }

  const clearError = () => {
    setError(null)
    setErrorObj(null)
  }

  const exportPdf = async () => {
    if (!result) return
    setExporting(true)
    setExportError(null)
    try {
      const resp = await downloadScanPdf({
        scanId: result?.report?.scan_id,
        prompt: result?.input_prompt || prompt,
        target: target.trim() || 'web-ui',
      })
      const { blob, filename } = await downloadFromResponse(resp, 'scan_report.pdf')
      triggerDownload(blob, filename)
    } catch (err) {
      setExportError(err?.message || 'Failed to export PDF')
    } finally {
      setExporting(false)
    }
  }

  const findings = result?.report?.findings || []
  const matchedRuleDetails = result?.matched_rule_details || []
  const detection = result?.detection

  return (
    <div className="view-stack">
      <section className="panel panel-ops">
        <div className="panel-header">
          <h2>Analysis workspace</h2>
          <span className="muted">Endpoint: POST /analyze</span>
        </div>

        <form className="ops-form-grid" onSubmit={submit}>
          <label className="field-label">
            Target ID
            <input
              type="text"
              value={target}
              onChange={(event) => setTarget(event.target.value)}
              placeholder="web-ui"
            />
          </label>
          <div className="field-actions">
            <button type="submit" className="btn btn-primary" disabled={mutation.isPending}>
              {mutation.isPending ? 'Running scan...' : 'Run scan'}
            </button>
            {result && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={exportPdf}
                disabled={exporting}
              >
                {exporting ? 'Exporting PDF...' : 'Export PDF'}
              </button>
            )}
          </div>
        </form>

        <textarea
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Paste or type prompt content to evaluate"
          rows={6}
        />

        {error && !isPolicyDenied && (
          <article className="message-card message-error in-panel">{error}</article>
        )}
        {exportError && (
          <article className="message-card message-error in-panel">{exportError}</article>
        )}
      </section>

      {isPolicyDenied && (
        <BlockedByValoPanel error={errorObj} onClear={clearError} />
      )}

      {result && (
        <section className="view-stack">
          <section className="kpi-grid">
            <article className="kpi-card">
              <p className="kpi-card-label">Combined risk score</p>
              <h3 className="kpi-card-value">{formatScore(Number(result.combined_score || 0))}</h3>
            </article>
            <article className="kpi-card">
              <p className="kpi-card-label">Scan ID</p>
              <h3 className="kpi-card-value kpi-card-value-mono">{result?.report?.scan_id || '-'}</h3>
            </article>
            <article className="kpi-card">
              <p className="kpi-card-label">Max severity found</p>
              <h3 className="kpi-card-value">{formatNumber(result?.report?.max_severity_found || 0)}</h3>
            </article>
            <article className="kpi-card">
              <p className="kpi-card-label">Total findings</p>
              <h3 className="kpi-card-value">{formatNumber(findings.length)}</h3>
            </article>
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2>Scanned input</h2>
            </div>
            <p className="analysis-prompt">{result.input_prompt || '-'}</p>
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2>Detection overview</h2>
            </div>
            <div className="analysis-meta-grid">
              <span><strong>Content type:</strong> {detection?.content_type || '-'}</span>
              <span><strong>Detected language:</strong> {detection?.detected_language || '-'}</span>
              <span><strong>Token count:</strong> {formatNumber(detection?.token_count || 0)}</span>
              <span><strong>Line count:</strong> {formatNumber(detection?.line_count || 0)}</span>
            </div>
            <div className="tag-list top-gap">
              {(detection?.flags || []).map((flag) => (
                <span className="tag-item" key={flag}>{flag}</span>
              ))}
              {(detection?.flags || []).length === 0 && <span className="muted">No flags generated.</span>}
            </div>
          </section>

          {Array.isArray(result.policy_decisions) && (
            <PolicyDecisionsPanel
              decisions={result.policy_decisions}
              finalDecision={result.final_decision || 'allow'}
              traceId={result.trace_id}
            />
          )}

          <section className="panel">
            <div className="panel-header">
              <h2>Matched rule explanations</h2>
            </div>
            <div className="detail-list top-gap">
              {matchedRuleDetails.map((rule) => (
                <article key={rule.rule_id} className="detail-card">
                  <p><strong>Rule ID:</strong> {rule.rule_id}</p>
                  <p><strong>Description:</strong> {rule.description || 'No description available.'}</p>
                  <p><strong>Severity:</strong> {rule.severity}</p>
                  <div className="tag-list top-gap-small">
                    {(rule.matched_fragments || []).map((fragment, index) => (
                      <span className="tag-item" key={`${rule.rule_id}-${index}`}>
                        {fragment.evidence}
                      </span>
                    ))}
                    {(rule.matched_fragments || []).length === 0 && (
                      <span className="muted">No matched fragments.</span>
                    )}
                  </div>
                </article>
              ))}
              {matchedRuleDetails.length === 0 && <p className="muted">No matched rules returned.</p>}
            </div>
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2>Findings</h2>
            </div>
            <div className="table-wrap top-gap">
              <table>
                <thead>
                  <tr>
                    <th>Rule ID</th>
                    <th>Category</th>
                    <th>Severity</th>
                    <th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {findings.map((finding, index) => (
                    <tr key={`${finding.rule_id}-${index}`}>
                      <td>{finding.rule_id}</td>
                      <td>{finding.category}</td>
                      <td>{finding.severity}</td>
                      <td>{clipText(finding.evidence, 140)}</td>
                    </tr>
                  ))}
                  {findings.length === 0 && (
                    <tr>
                      <td colSpan={4} className="empty-cell">
                        No findings returned for this scan.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </section>
      )}
    </div>
  )
}
