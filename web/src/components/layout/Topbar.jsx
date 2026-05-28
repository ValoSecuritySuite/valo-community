import { useLocation } from 'react-router-dom'

import ModePill from './ModePill.jsx'

const ROUTE_TITLES = {
  '/': { eyebrow: 'Operations', title: 'Overview', subtitle: 'Risk posture and recent firewall activity at a glance.' },
  '/firewall': {
    eyebrow: 'Operations',
    title: 'AI Firewall',
    subtitle: 'Live traffic, mode controls, and proxy configuration for inline policy enforcement.',
  },
  '/playground': {
    eyebrow: 'Operations',
    title: 'Playground',
    subtitle: 'Dry-run prompts through the firewall without contacting any LLM upstream.',
  },
  '/policies': {
    eyebrow: 'Authoring',
    title: 'Governance Policies',
    subtitle: 'YAML-backed policies that drive allow / warn / deny decisions.',
  },
  '/rules': {
    eyebrow: 'Authoring',
    title: 'Detection Rules',
    subtitle: 'Inspect context rules and text-scan detectors used by the analysis pipeline.',
  },
  '/analysis': {
    eyebrow: 'Investigate',
    title: 'Analysis Workspace',
    subtitle: 'Run a prompt through the full pipeline and inspect every stage.',
  },
  '/ingestion': {
    eyebrow: 'Investigate',
    title: 'Ingestion',
    subtitle: 'Normalize external scan output into the Valo portfolio.',
  },
  '/settings': {
    eyebrow: 'Configure',
    title: 'Settings',
    subtitle: 'Runtime configuration for log level, rate limits, and the rules cache.',
  },
  '/executive': {
    eyebrow: 'Executive',
    title: 'Executive Dashboard',
    subtitle: 'Risk, exposure, and automation KPIs over your selected window.',
  },
  '/outcomes': {
    eyebrow: 'Learn',
    title: 'Outcomes',
    subtitle: 'Persisted playbook outcomes ready for analyst labeling.',
  },
  '/learning': {
    eyebrow: 'Learn',
    title: 'Proposals',
    subtitle: 'Refiner-generated rule changes awaiting review.',
  },
  '/reports': {
    eyebrow: 'Executive',
    title: 'Reports',
    subtitle: 'Weekly persisted reports plus on-demand executive and rollup exports.',
  },
}

export default function Topbar({
  mode,
  modeBusy,
  onChangeMode,
  backendLabel,
  onRefresh,
  refreshing,
}) {
  const { pathname } = useLocation()
  const meta = ROUTE_TITLES[pathname] || {
    eyebrow: 'Console',
    title: 'Valo',
    subtitle: '',
  }

  return (
    <header className="app-topbar">
      <div className="app-topbar-headings">
        <p className="eyebrow">{meta.eyebrow}</p>
        <h1>{meta.title}</h1>
        {meta.subtitle && <p className="subtitle">{meta.subtitle}</p>}
      </div>

      <div className="app-topbar-actions">
        <ModePill mode={mode} busy={modeBusy} onClick={onChangeMode} />
        <span className="status-pill">{backendLabel}</span>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={onRefresh}
          disabled={refreshing}
        >
          {refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>
    </header>
  )
}
