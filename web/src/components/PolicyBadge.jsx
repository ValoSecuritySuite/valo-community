const DECISION_LABELS = {
  allow: 'Allow',
  warn: 'Warn',
  deny: 'Deny',
}

export default function PolicyBadge({ decision, severity, size = 'sm', children }) {
  const normalized = String(decision || 'allow').toLowerCase()
  const label = DECISION_LABELS[normalized] || normalized
  const className = [
    'decision-badge',
    `decision-${normalized}`,
    size === 'lg' ? 'decision-badge-lg' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <span className={className}>
      <span className="decision-dot" aria-hidden="true" />
      <span className="decision-label">{label}</span>
      {Number.isFinite(Number(severity)) && (
        <span className="decision-severity">sev {Number(severity)}</span>
      )}
      {children}
    </span>
  )
}
