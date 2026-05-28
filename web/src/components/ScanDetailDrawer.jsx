import { useState } from 'react'

import { generateReport } from '../api/reports.js'
import { downloadFromResponse, downloadScanPdf } from '../api/scan.js'
import {
  formatDate,
  formatScore,
  normalizeSeverity,
  triggerDownload,
} from '../lib/format.js'

export default function ScanDetailDrawer({ scan, onClose }) {
  const [downloading, setDownloading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)

  if (!scan) return null

  const categoryEntries = Object.entries(scan.category_breakdown || {})
  const findings = Array.isArray(scan.findings) ? scan.findings : []
  const ruleExplanations = Array.isArray(scan.rule_explanations)
    ? scan.rule_explanations
    : []

  const handleDownloadScanPdf = async () => {
    if (!scan.scan_id) {
      setError('This scan has no scan_id; cannot generate a PDF.')
      return
    }
    setError(null)
    setInfo(null)
    setDownloading(true)
    try {
      const resp = await downloadScanPdf({ scanId: scan.scan_id })
      const { blob, filename } = await downloadFromResponse(
        resp,
        `valo-scan-${String(scan.scan_id).slice(0, 8)}.pdf`,
      )
      triggerDownload(blob, filename)
    } catch (err) {
      setError(err.message || 'Failed to download scan PDF')
    } finally {
      setDownloading(false)
    }
  }

  const handleSaveToReports = async () => {
    if (!scan.scan_id) {
      setError('This scan has no scan_id; cannot persist a report.')
      return
    }
    setError(null)
    setInfo(null)
    setSaving(true)
    try {
      const result = await generateReport({
        kind: 'scan_pdf',
        scan_id: scan.scan_id,
      })
      setInfo(
        `Saved to /reports as ${result?.report?.filename || 'scan_pdf'}.`,
      )
    } catch (err) {
      setError(err.message || 'Failed to save report')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="modal-backdrop"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="modal"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Scan detail"
      >
        <div className="modal-header">
          <h2>Scan detail</h2>
          <div className="settings-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleDownloadScanPdf}
              disabled={downloading || !scan.scan_id}
              title="Download a PDF for this scan via /report/pdf/scan/{scan_id}"
            >
              {downloading ? 'Downloading...' : 'Download PDF'}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleSaveToReports}
              disabled={saving || !scan.scan_id}
              title="Persist a scan_pdf report into /reports for later download"
            >
              {saving ? 'Saving...' : 'Save to reports'}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={onClose}
            >
              Close
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

        <div className="modal-meta">
          <span>
            <strong>Scan ID:</strong> <code>{scan.scan_id}</code>
          </span>
          <span>
            <strong>Source:</strong> {scan.source || '-'}
          </span>
          <span>
            <strong>Score:</strong> {formatScore(Number(scan.score || 0))}
          </span>
          <span>
            <strong>Severity:</strong>{' '}
            <span
              className={`severity-chip severity-${normalizeSeverity(scan.severity)}`}
            >
              {normalizeSeverity(scan.severity)}
            </span>
          </span>
          <span>
            <strong>Date:</strong> {formatDate(scan.date)}
          </span>
          <span>
            <strong>Findings:</strong>{' '}
            {Number(scan.finding_count ?? findings.length ?? 0)}
          </span>
        </div>

        <section className="modal-section">
          <h3>Category breakdown</h3>
          <div className="tag-list">
            {categoryEntries.map(([category, count]) => (
              <span key={category} className="tag-item">
                {category}: {count}
              </span>
            ))}
            {categoryEntries.length === 0 && (
              <span className="muted">No categories available.</span>
            )}
          </div>
        </section>

        <section className="modal-section">
          <h3>Full findings</h3>
          <div className="detail-list">
            {findings.map((finding, index) => (
              <article
                key={`${finding.rule_id || 'finding'}-${index}`}
                className="detail-card"
              >
                <p>
                  <strong>Rule:</strong>{' '}
                  <code>{finding.rule_id || '-'}</code>
                </p>
                <p>
                  <strong>Category:</strong> {finding.category || '-'}
                </p>
                <p>
                  <strong>Severity:</strong>{' '}
                  <span
                    className={`severity-chip severity-${normalizeSeverity(finding.severity)}`}
                  >
                    {normalizeSeverity(finding.severity)}
                  </span>
                </p>
                <p>
                  <strong>Evidence:</strong>{' '}
                  {finding.evidence || finding.message || '-'}
                </p>
              </article>
            ))}
            {findings.length === 0 && (
              <p className="muted">No findings recorded for this scan.</p>
            )}
          </div>
        </section>

        <section className="modal-section">
          <h3>Rule explanations</h3>
          <div className="detail-list">
            {ruleExplanations.map((rule, index) => (
              <article
                key={`${rule.rule_id || 'rule'}-${index}`}
                className="detail-card"
              >
                <p>
                  <strong>Rule:</strong> <code>{rule.rule_id || '-'}</code>
                </p>
                <p>
                  <strong>Severity:</strong>{' '}
                  <span
                    className={`severity-chip severity-${normalizeSeverity(rule.severity)}`}
                  >
                    {normalizeSeverity(rule.severity)}
                  </span>
                </p>
                <p>
                  <strong>Description:</strong>{' '}
                  {rule.description || 'No description available.'}
                </p>
                <p>
                  <strong>Evidence fragments:</strong>{' '}
                  {(rule.evidence_fragments || []).length > 0
                    ? rule.evidence_fragments.join(' | ')
                    : 'None'}
                </p>
              </article>
            ))}
            {ruleExplanations.length === 0 && (
              <p className="muted">No rule explanations available.</p>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
