const MODE_STYLES = {
  off: { label: 'OFF', tone: 'mode-off', helper: 'Inspection disabled' },
  monitor: { label: 'MONITOR', tone: 'mode-monitor', helper: 'Logging only' },
  enforce: { label: 'ENFORCE', tone: 'mode-enforce', helper: 'Live blocking' },
}

export default function ModePill({ mode, onClick, busy = false, enforceEnterpriseOnly = false }) {
  const config = MODE_STYLES[mode] || {
    label: 'UNKNOWN',
    tone: 'mode-unknown',
    helper: 'No connection',
  }

  const interactive = typeof onClick === 'function'
  const helper = enforceEnterpriseOnly
    ? `${config.helper}. Enforce mode requires Valo Enterprise.`
    : config.helper

  return (
    <button
      type="button"
      className={`mode-pill ${config.tone}${interactive ? '' : ' mode-pill-static'}${
        enforceEnterpriseOnly ? ' mode-pill-community' : ''
      }`}
      onClick={onClick}
      disabled={!interactive || busy}
      aria-label={`Enforcement mode is ${config.label}`}
      title={helper}
    >
      <span className="mode-pill-dot" aria-hidden="true" />
      <span className="mode-pill-label">Mode</span>
      <span className="mode-pill-value">{busy ? '...' : config.label}</span>
    </button>
  )
}
