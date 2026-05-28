import { useState } from 'react'

import PolicyBadge from './PolicyBadge.jsx'
import { copyToClipboard } from '../lib/format.js'

function DecisionRow({ decision }) {
  const [expanded, setExpanded] = useState(decision.matched)
  const reasons = Array.isArray(decision.reasons) ? decision.reasons : []
  const tags = Array.isArray(decision.tags) ? decision.tags : []

  return (
    <article
      className={`policy-card policy-card-${decision.matched ? 'matched' : 'idle'}`}
      aria-expanded={expanded}
    >
      <header className="policy-card-header">
        <div className="policy-card-title">
          <strong>{decision.name || decision.policy_id}</strong>
          <span className="muted">{decision.policy_id}</span>
        </div>
        <PolicyBadge decision={decision.decision} severity={decision.severity} />
      </header>

      <p className="policy-card-message">{decision.message}</p>

      {(reasons.length > 0 || tags.length > 0) && (
        <button
          type="button"
          className="btn btn-secondary policy-card-toggle"
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? 'Hide details' : 'Show details'}
        </button>
      )}

      {expanded && (
        <div className="policy-card-body">
          {reasons.length > 0 && (
            <div className="policy-card-reasons">
              <span className="muted">Conditions</span>
              <ul>
                {reasons.map((reason, index) => (
                  <li key={`${decision.policy_id}-reason-${index}`}>{reason}</li>
                ))}
              </ul>
            </div>
          )}
          {tags.length > 0 && (
            <div className="tag-list top-gap-small">
              {tags.map((tag) => (
                <span className="tag-item" key={`${decision.policy_id}-tag-${tag}`}>
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </article>
  )
}

function TraceIdLine({ traceId }) {
  const [copied, setCopied] = useState(false)
  if (!traceId) return null
  return (
    <div className="trace-line muted small">
      Trace ID:&nbsp;<code>{traceId}</code>
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
  )
}

export default function PolicyDecisionsPanel({
  decisions = [],
  finalDecision = 'allow',
  title = 'Governance Decision',
  emptyHint = 'No governance policies configured yet.',
  traceId = null,
}) {
  const matched = decisions.filter((d) => d.matched)
  const total = decisions.length

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>{title}</h2>
        <PolicyBadge decision={finalDecision} size="lg" />
      </div>

      <p className="muted">
        {total === 0
          ? emptyHint
          : `${matched.length} of ${total} polic${total === 1 ? 'y' : 'ies'} matched. Aggregate uses precedence: deny > warn > allow.`}
      </p>

      <TraceIdLine traceId={traceId} />

      {total > 0 && (
        <div className="policy-decision-list top-gap">
          {decisions.map((decision) => (
            <DecisionRow key={decision.policy_id} decision={decision} />
          ))}
        </div>
      )}
    </section>
  )
}
