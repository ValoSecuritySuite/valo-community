import { useEffect, useState } from 'react'

import PolicyBadge from './PolicyBadge.jsx'
import { copyToClipboard, formatDate } from '../lib/format.js'

function CopyButton({ value, label = 'Copy' }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      className="btn btn-secondary btn-tight"
      onClick={async () => {
        const ok = await copyToClipboard(value)
        if (ok) {
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        }
      }}
    >
      {copied ? 'Copied' : label}
    </button>
  )
}

export default function EnforcementEventDrawer({ event, onClose }) {
  useEffect(() => {
    const onKey = (event_) => {
      if (event_.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!event) return null

  const matched = event.matched_decisions || []

  return (
    <aside className="drawer" role="dialog" aria-modal="true" aria-label="Enforcement event detail">
      <header className="drawer-header">
        <div>
          <p className="eyebrow">Trace {event.trace_id.slice(0, 8)}</p>
          <h2 className="drawer-title">
            <PolicyBadge decision={event.final_decision} size="lg" />
            <span className="drawer-route"><code>{event.route}</code></span>
          </h2>
          <p className="muted">
            {formatDate(event.timestamp)} | direction <code>{event.direction}</code> | mode{' '}
            <code>{event.mode}</code>
          </p>
        </div>
        <button type="button" className="btn btn-secondary" onClick={onClose}>
          Close
        </button>
      </header>

      <section className="drawer-meta-grid">
        <div className="drawer-meta-item">
          <span className="muted small">Trace ID</span>
          <div className="drawer-meta-row">
            <code>{event.trace_id}</code>
            <CopyButton value={event.trace_id} />
          </div>
        </div>
        <div className="drawer-meta-item">
          <span className="muted small">Blocked</span>
          <strong className={event.blocked ? 'text-deny' : 'text-allow'}>
            {event.blocked ? 'Yes (HTTP 403)' : 'No'}
          </strong>
        </div>
        <div className="drawer-meta-item">
          <span className="muted small">Would block</span>
          <strong className={event.would_block ? 'text-warn' : 'text-allow'}>
            {event.would_block ? 'Deny matched' : 'No deny match'}
          </strong>
        </div>
        <div className="drawer-meta-item">
          <span className="muted small">Pipeline + gate</span>
          <strong>{(event.duration_ms || 0).toFixed(2)} ms</strong>
        </div>
      </section>

      <section className="drawer-section">
        <h3>Matched policies ({matched.length})</h3>
        {matched.length === 0 ? (
          <p className="muted">No policies matched this request.</p>
        ) : (
          <div className="policy-decision-list">
            {matched.map((decision) => (
              <article
                key={decision.policy_id}
                className={`policy-card policy-card-matched`}
              >
                <header className="policy-card-header">
                  <div className="policy-card-title">
                    <strong>{decision.name || decision.policy_id}</strong>
                    <span className="muted">{decision.policy_id}</span>
                  </div>
                  <PolicyBadge decision={decision.decision} severity={decision.severity} />
                </header>
                <p className="policy-card-message">{decision.message}</p>
                {Array.isArray(decision.reasons) && decision.reasons.length > 0 && (
                  <div className="policy-card-reasons">
                    <span className="muted">Conditions</span>
                    <ul>
                      {decision.reasons.map((reason, index) => (
                        <li key={`${decision.policy_id}-reason-${index}`}>{reason}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {Array.isArray(decision.tags) && decision.tags.length > 0 && (
                  <div className="tag-list top-gap-small">
                    {decision.tags.map((tag) => (
                      <span className="tag-item" key={`${decision.policy_id}-tag-${tag}`}>
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
    </aside>
  )
}
