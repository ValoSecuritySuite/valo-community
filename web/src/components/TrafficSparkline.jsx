function Bar({ label, count, total, tone }) {
  const percent = total === 0 ? 0 : Math.max(2, Math.round((count / total) * 100))
  return (
    <div className="sparkline-row">
      <div className="sparkline-label">
        <span className={`sparkline-dot decision-${tone}`} aria-hidden="true" />
        <span>{label}</span>
      </div>
      <div className="sparkline-bar-wrap">
        <div className={`sparkline-bar decision-${tone}-bg`} style={{ width: `${percent}%` }} />
      </div>
      <div className="sparkline-value">{count}</div>
    </div>
  )
}

export default function TrafficSparkline({ stats }) {
  const total = stats?.total_events || 0
  const buckets = [
    { key: 'allow', label: 'Allowed', count: stats?.by_decision?.allow || 0, tone: 'allow' },
    { key: 'warn', label: 'Warn', count: stats?.by_decision?.warn || 0, tone: 'warn' },
    { key: 'deny', label: 'Deny', count: stats?.by_decision?.deny || 0, tone: 'deny' },
  ]

  if (total === 0) {
    return (
      <p className="muted">
        No firewall traffic recorded yet. Once requests flow through the middleware or proxy,
        decisions will appear here.
      </p>
    )
  }

  return (
    <div className="sparkline-list">
      {buckets.map((bucket) => (
        <Bar key={bucket.key} {...bucket} total={total} />
      ))}
      <div className="sparkline-meta muted">
        Direction:&nbsp;
        {Object.entries(stats?.by_direction || {})
          .map(([key, value]) => `${key}=${value}`)
          .join(', ') || '-'}
      </div>
    </div>
  )
}
