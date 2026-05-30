import { Link } from 'react-router-dom'

const FEATURE_COPY = {
  executive: {
    title: 'Executive Dashboard',
    description:
      'Portfolio-wide KPIs, trend windows, and compliance rollups across your AI firewall estate.',
  },
  reports: {
    title: 'Automated Reports',
    description:
      'Scheduled executive PDFs, CSV exports, and branded portfolio rollups delivered on a cadence.',
  },
  ingestion: {
    title: 'Scan Ingestion',
    description:
      'Normalize external scanner output and tool wrappers into the Valo portfolio for unified reporting.',
  },
  outcomes: {
    title: 'Outcome Labeling',
    description:
      'Close the loop on playbook and policy decisions with analyst labels that feed automation metrics.',
  },
  learning: {
    title: 'Learning Proposals',
    description:
      'Review refiner-generated policy and playbook changes before they are applied to production.',
  },
  default: {
    title: 'Valo Enterprise',
    description:
      'This capability is not included in Community Edition. Upgrade to Valo Enterprise to enable it.',
  },
}

export default function EnterpriseUpsell({ feature = 'default' }) {
  const copy = FEATURE_COPY[feature] || FEATURE_COPY.default

  return (
    <section className="enterprise-upsell panel" aria-labelledby="enterprise-upsell-title">
      <p className="eyebrow">Valo Enterprise</p>
      <h2 id="enterprise-upsell-title">{copy.title}</h2>
      <p className="subtitle">{copy.description}</p>

      <div className="enterprise-upsell-badges">
        <span className="edition-badge edition-badge-enterprise">Enterprise only</span>
        <span className="edition-badge edition-badge-muted">Not in Community Edition</span>
      </div>

      <p className="muted small enterprise-upsell-note">
        Community Edition includes deterministic analysis, YAML policies, monitor-mode firewall,
        and per-scan PDF export. Enterprise adds enforce mode, portfolio analytics, executive
        dashboards, ingestion, playbooks, and the learning loop.
      </p>

      <div className="enterprise-upsell-actions">
        <Link to="/" className="btn btn-secondary">
          Back to Overview
        </Link>
        <a
          href="https://github.com/valo-ai/valo-community#enterprise-capabilities"
          className="btn btn-primary"
          target="_blank"
          rel="noreferrer"
        >
          Learn about Enterprise
        </a>
      </div>
    </section>
  )
}
