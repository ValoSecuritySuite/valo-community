import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { downloadExport, getSummary, getTrends } from '../api/executive.js'
import KpiCard from '../components/KpiCard.jsx'
import { formatDate, formatNumber, formatScore } from '../lib/format.js'

const WINDOW_OPTIONS = [
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: '90d', label: 'Last 90 days' },
]

const TREND_METRICS = ['requests', 'blocked', 'playbooks_fired', 'risk_score_sum']

function emptySummary(window) {
  return {
    window,
    generated_at: new Date().toISOString(),
    window_start: new Date().toISOString(),
    window_end: new Date().toISOString(),
    exposure: {
      total_requests: 0,
      blocked: 0,
      would_block: 0,
      block_rate: 0,
      by_decision: {},
      by_direction: {},
      top_blocking_policy_id: null,
      top_blocking_policy_count: 0,
    },
    risk: {
      average_risk_score: 0,
      p95_risk_score: 0,
      critical_findings: 0,
      severity_distribution: {},
    },
    automation: {
      events_total: 0,
      playbooks_fired: 0,
      actions_executed: 0,
      actions_by_type: {},
      mean_time_to_action_ms: 0,
    },
    coverage: {
      policies_total: 0,
      policies_enabled: 0,
      policies_enforce_mode: 0,
      playbooks_total: 0,
      playbooks_enabled: 0,
      playbooks_live: 0,
    },
    compliance: [],
    top_offenders: [],
  }
}

function SvgLineChart({ title, points, height = 120, strokeColor = '#0057B8' }) {
  if (!points || points.length === 0) {
    return (
      <article className="panel executive-chart">
        <div className="panel-header">
          <h3>{title}</h3>
          <span className="muted">No data in this window yet.</span>
        </div>
      </article>
    )
  }

  const width = 360
  const padding = { top: 14, right: 14, bottom: 24, left: 40 }
  const innerWidth = width - padding.left - padding.right
  const innerHeight = height - padding.top - padding.bottom

  const values = points.map((p) => Number(p.value) || 0)
  const maxValue = Math.max(...values, 1)
  const minValue = 0
  const range = maxValue - minValue || 1
  const xStep = points.length > 1 ? innerWidth / (points.length - 1) : 0

  const path = points
    .map((point, idx) => {
      const x = padding.left + idx * xStep
      const y = padding.top + innerHeight - ((Number(point.value) || 0) - minValue) * (innerHeight / range)
      return `${idx === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`
    })
    .join(' ')

  const lastPoint = points[points.length - 1]

  return (
    <article className="panel executive-chart">
      <div className="panel-header">
        <h3>{title}</h3>
        <span className="muted">peak {formatNumber(maxValue)}</span>
      </div>
      <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
        <line
          x1={padding.left}
          y1={padding.top + innerHeight}
          x2={width - padding.right}
          y2={padding.top + innerHeight}
          stroke="#dbe1ea"
          strokeWidth="1"
        />
        <text x={padding.left - 6} y={padding.top + 8} textAnchor="end" fontSize="10" fill="#6b7280">
          {formatNumber(maxValue)}
        </text>
        <text x={padding.left - 6} y={padding.top + innerHeight} textAnchor="end" fontSize="10" fill="#6b7280">
          0
        </text>
        <path d={path} fill="none" stroke={strokeColor} strokeWidth="2" />
      </svg>
      <p className="muted small">
        latest {formatNumber(lastPoint.value)} at {formatDate(lastPoint.bucket_start)}
      </p>
    </article>
  )
}

export default function ExecutiveView() {
  const [window, setWindow] = useState('7d')
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState(null)

  const summaryQuery = useQuery({
    queryKey: ['executive', 'summary', { window }],
    queryFn: () => getSummary({ window }),
    refetchInterval: 60_000,
    retry: false,
  })

  const trendsQuery = useQuery({
    queryKey: ['executive', 'trends', { window, metrics: TREND_METRICS.join(',') }],
    queryFn: () => getTrends({ window, metrics: TREND_METRICS.join(',') }),
    refetchInterval: 60_000,
    retry: false,
  })

  const summary = summaryQuery.data || emptySummary(window)
  const trends = trendsQuery.data?.series || []
  const trendByMetric = useMemo(() => {
    const out = {}
    trends.forEach((series) => {
      out[series.metric] = series.points || []
    })
    return out
  }, [trends])

  const isDisabled = summaryQuery.error?.status === 503 || trendsQuery.error?.status === 503

  async function handleExport(format) {
    setExporting(true)
    setExportError(null)
    try {
      await downloadExport({ window, format })
    } catch (err) {
      setExportError(err.message || 'Export failed')
    } finally {
      setExporting(false)
    }
  }

  if (isDisabled) {
    return (
      <div className="view-stack">
        <section className="panel">
          <div className="panel-header">
            <h2>Executive Dashboard is disabled</h2>
          </div>
          <p className="muted">
            Set <code>APP_EXECUTIVE_METRICS_ENABLED=true</code> on the backend and restart to enable
            durable rollups, board KPIs, and PDF/CSV exports.
          </p>
        </section>
      </div>
    )
  }

  const exposure = summary.exposure
  const risk = summary.risk
  const automation = summary.automation
  const coverage = summary.coverage

  return (
    <div className="view-stack">
      <section className="panel executive-toolbar">
        <div className="executive-toolbar-left">
          <label htmlFor="executive-window" className="muted small">
            Window
          </label>
          <select
            id="executive-window"
            value={window}
            onChange={(event) => setWindow(event.target.value)}
            className="executive-select"
          >
            {WINDOW_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          {summaryQuery.isFetching && <span className="muted small">refreshing...</span>}
        </div>
        <div className="executive-toolbar-actions">
          <button
            type="button"
            className="btn btn-secondary"
            disabled={exporting}
            onClick={() => handleExport('csv')}
          >
            Export CSV
          </button>
          <button
            type="button"
            className="btn"
            disabled={exporting}
            onClick={() => handleExport('pdf')}
          >
            {exporting ? 'Preparing...' : 'Export PDF'}
          </button>
        </div>
      </section>

      {exportError && (
        <section className="panel">
          <p className="muted">Export failed: {exportError}</p>
        </section>
      )}

      <section className="panel">
        <div className="panel-header">
          <h2>Exposure</h2>
          <span className="muted">LLM call volume + block posture</span>
        </div>
        <div className="kpi-grid">
          <KpiCard
            label="Total LLM calls"
            value={formatNumber(exposure.total_requests)}
            hint={`Window: ${summary.window}`}
          />
          <KpiCard
            label="Blocked"
            value={formatNumber(exposure.blocked)}
            hint={`Would-block: ${formatNumber(exposure.would_block)}`}
            tone="warn"
          />
          <KpiCard
            label="Block rate"
            value={`${(Number(exposure.block_rate || 0) * 100).toFixed(2)}%`}
            hint="blocked / total_requests"
          />
          <KpiCard
            label="Top blocking policy"
            value={exposure.top_blocking_policy_id || '-'}
            hint={
              exposure.top_blocking_policy_id
                ? `${formatNumber(exposure.top_blocking_policy_count)} blocks`
                : 'no blocks recorded'
            }
            mono
          />
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Risk</h2>
          <span className="muted">From pipeline scans</span>
        </div>
        <div className="kpi-grid">
          <KpiCard
            label="Average risk score"
            value={formatScore(risk.average_risk_score)}
            hint="Across pipeline scans in window"
          />
          <KpiCard
            label="P95 risk score"
            value={formatScore(risk.p95_risk_score)}
            hint="Approximate, severity-derived"
          />
          <KpiCard
            label="Critical findings"
            value={formatNumber(risk.critical_findings)}
            hint="risk_score >= 80"
            tone="critical"
          />
          <KpiCard
            label="Severity distribution"
            value={Object.values(risk.severity_distribution || {}).reduce(
              (acc, v) => acc + Number(v || 0),
              0,
            )}
            hint={
              Object.entries(risk.severity_distribution || {})
                .map(([sev, count]) => `${sev}=${count}`)
                .join(', ') || 'no scans yet'
            }
          />
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Automation</h2>
          <span className="muted">Playbook engine activity</span>
        </div>
        <div className="kpi-grid">
          <KpiCard
            label="Events processed"
            value={formatNumber(automation.events_total)}
            hint="Through the playbook engine"
          />
          <KpiCard
            label="Playbooks fired"
            value={formatNumber(automation.playbooks_fired)}
            hint="Sum of matched playbook ids"
          />
          <KpiCard
            label="Actions executed"
            value={formatNumber(automation.actions_executed)}
            hint={
              Object.entries(automation.actions_by_type || {})
                .map(([action, count]) => `${action}=${count}`)
                .join(', ') || 'no actions yet'
            }
          />
          <KpiCard
            label="Mean time-to-action"
            value={`${formatNumber(Math.round(automation.mean_time_to_action_ms))} ms`}
            hint="Trace duration average"
          />
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Coverage</h2>
          <span className="muted">Authored policies + playbooks</span>
        </div>
        <div className="kpi-grid">
          <KpiCard
            label="Policies"
            value={formatNumber(coverage.policies_total)}
            hint={`${coverage.policies_enabled} enabled, ${coverage.policies_enforce_mode} in enforce mode`}
          />
          <KpiCard
            label="Playbooks"
            value={formatNumber(coverage.playbooks_total)}
            hint={`${coverage.playbooks_enabled} enabled, ${coverage.playbooks_live} live`}
          />
          <KpiCard
            label="Compliance tags"
            value={formatNumber(summary.compliance?.length || 0)}
            hint="Distinct tags across policies + playbooks"
          />
          <KpiCard
            label="Top offenders tracked"
            value={formatNumber(summary.top_offenders?.length || 0)}
            hint="Subjects with deny activity in window"
          />
        </div>
      </section>

      <section className="executive-chart-grid">
        <SvgLineChart title="Requests over time" points={trendByMetric.requests || []} />
        <SvgLineChart
          title="Blocked over time"
          points={trendByMetric.blocked || []}
          strokeColor="#c93a3a"
        />
        <SvgLineChart
          title="Playbooks fired over time"
          points={trendByMetric.playbooks_fired || []}
          strokeColor="#7a3ec9"
        />
        <SvgLineChart
          title="Risk score sum over time"
          points={trendByMetric.risk_score_sum || []}
          strokeColor="#c98e3a"
        />
      </section>

      <section className="executive-grid-two">
        <article className="panel">
          <div className="panel-header">
            <h2>Compliance posture</h2>
            <span className="muted">By tag</span>
          </div>
          {summary.compliance.length === 0 ? (
            <p className="muted">No tagged policies or playbooks yet.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Tag</th>
                    <th>Policies</th>
                    <th>Playbooks</th>
                    <th>Matched</th>
                    <th>Blocked</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.compliance.map((row) => (
                    <tr key={row.tag}>
                      <td><code>{row.tag}</code></td>
                      <td>{formatNumber(row.policies)}</td>
                      <td>{formatNumber(row.playbooks)}</td>
                      <td>{formatNumber(row.matched_events)}</td>
                      <td>{formatNumber(row.blocked_events)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>

        <article className="panel">
          <div className="panel-header">
            <h2>Top offenders</h2>
            <span className="muted">By deny count</span>
          </div>
          {summary.top_offenders.length === 0 ? (
            <p className="muted">No deny activity in this window.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Subject</th>
                    <th>Type</th>
                    <th>Denies</th>
                    <th>Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.top_offenders.map((row) => (
                    <tr key={`${row.subject_type}:${row.subject_id}`}>
                      <td><code>{row.subject_id}</code></td>
                      <td>{row.subject_type}</td>
                      <td>{formatNumber(row.deny_count)}</td>
                      <td>{row.last_seen ? formatDate(row.last_seen) : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
      </section>
    </div>
  )
}
