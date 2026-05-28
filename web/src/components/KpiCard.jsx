export default function KpiCard({ label, value, hint, tone, mono }) {
  const toneClass = tone ? `kpi-card-${tone}` : ''
  const valueClass = mono ? 'kpi-card-value kpi-card-value-mono' : 'kpi-card-value'
  return (
    <article className={`kpi-card ${toneClass}`}>
      <p className="kpi-card-label">{label}</p>
      <h3 className={valueClass}>{value}</h3>
      {hint && <p className="kpi-card-hint muted">{hint}</p>}
    </article>
  )
}
