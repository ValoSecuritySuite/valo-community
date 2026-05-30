import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useOutletContext } from 'react-router-dom'

import { getDashboard } from '../api/dashboard.js'
import { getEvents, getStats } from '../api/enforcement.js'
import {
  downloadFromResponse,
  downloadRollupPdf,
  downloadScanPdf,
} from '../api/scan.js'
import KpiCard from '../components/KpiCard.jsx'
import PolicyBadge from '../components/PolicyBadge.jsx'
import ScanDetailDrawer from '../components/ScanDetailDrawer.jsx'
import TrafficSparkline from '../components/TrafficSparkline.jsx'
import {
  clipText,
  formatDate,
  formatNumber,
  formatRelativeTime,
  formatScore,
  normalizeSeverity,
  triggerDownload,
} from '../lib/format.js'

const DISTRIBUTION_ORDER = ['low', 'medium', 'high', 'critical']
const SEVERITY_FILTERS = ['all', 'low', 'medium', 'high', 'critical']

function emptyDashboard() {
  return {
    executive_summary: { average_risk: 0, highest_risk: 0, critical_count: 0, total_scans: 0 },
    risk_distribution: { low: 0, medium: 0, high: 0, critical: 0 },
    sources: [],
    scans: [],
  }
}

export default function OverviewView() {
  const { isCommunity = false } = useOutletContext() || {}
  const portfolioEnterpriseOnly = isCommunity

  const dashboardQuery = useQuery({
    queryKey: ['dashboard'],
    queryFn: getDashboard,
  })

  const statsQuery = useQuery({
    queryKey: ['enforcement', 'stats', { window: 0 }],
    queryFn: () => getStats({ window_seconds: 0, top_n: 5 }),
    refetchInterval: 10_000,
  })

  const recentEventsQuery = useQuery({
    queryKey: ['enforcement', 'events', { limit: 8 }],
    queryFn: () => getEvents({ limit: 8 }),
    refetchInterval: 10_000,
  })

  const dashboard = dashboardQuery.data || emptyDashboard()
  const stats = statsQuery.data
  const events = recentEventsQuery.data?.events || []

  const [severityFilter, setSeverityFilter] = useState('all')
  const [sourceFilter, setSourceFilter] = useState('all')
  const [scoreSort, setScoreSort] = useState('desc')
  const [selectedScan, setSelectedScan] = useState(null)
  const [exportError, setExportError] = useState(null)
  const [exportLoading, setExportLoading] = useState(false)
  const [scanPdfLoadingId, setScanPdfLoadingId] = useState(null)

  const distributionTotal = DISTRIBUTION_ORDER.reduce(
    (sum, key) => sum + Number(dashboard.risk_distribution?.[key] || 0),
    0,
  )

  const blockRatePct = stats ? `${(stats.block_rate * 100).toFixed(1)}%` : '-'
  const topPolicy = stats?.top_policies?.[0]?.policy_id || '-'

  const sources = useMemo(() => {
    const set = new Set()
    for (const scan of dashboard.scans || []) {
      if (scan.source) set.add(scan.source)
    }
    return Array.from(set).sort()
  }, [dashboard.scans])

  const filteredScans = useMemo(() => {
    const list = (dashboard.scans || []).filter((scan) => {
      if (severityFilter !== 'all' && normalizeSeverity(scan.severity) !== severityFilter) {
        return false
      }
      if (sourceFilter !== 'all' && scan.source !== sourceFilter) {
        return false
      }
      return true
    })
    list.sort((a, b) => {
      const av = Number(a.score || 0)
      const bv = Number(b.score || 0)
      return scoreSort === 'desc' ? bv - av : av - bv
    })
    return list
  }, [dashboard.scans, severityFilter, sourceFilter, scoreSort])

  const handleExportRollupPdf = async () => {
    if (portfolioEnterpriseOnly) {
      return
    }
    setExportError(null)
    setExportLoading(true)
    try {
      const resp = await downloadRollupPdf()
      const today = new Date().toISOString().slice(0, 10).replace(/-/g, '')
      const { blob, filename } = await downloadFromResponse(
        resp,
        `valo-portfolio-rollup-${today}.pdf`,
      )
      triggerDownload(blob, filename)
    } catch (err) {
      setExportError(err.message || 'Failed to export rollup PDF')
    } finally {
      setExportLoading(false)
    }
  }

  const handleDownloadScanPdf = async (scan) => {
    if (!scan?.scan_id) return
    setExportError(null)
    setScanPdfLoadingId(scan.scan_id)
    try {
      const resp = await downloadScanPdf({ scanId: scan.scan_id })
      const { blob, filename } = await downloadFromResponse(
        resp,
        `valo-scan-${String(scan.scan_id).slice(0, 8)}.pdf`,
      )
      triggerDownload(blob, filename)
    } catch (err) {
      setExportError(err.message || 'Failed to download scan PDF')
    } finally {
      setScanPdfLoadingId(null)
    }
  }

  return (
    <div className="view-stack">
      <section className="kpi-grid">
        <KpiCard
          label="Total scans"
          value={formatNumber(dashboard.executive_summary?.total_scans)}
          hint="All-time analyses recorded"
        />
        <KpiCard
          label="Average risk"
          value={formatScore(dashboard.executive_summary?.average_risk)}
          hint="Across the portfolio"
        />
        <KpiCard
          label="Highest risk"
          value={formatScore(dashboard.executive_summary?.highest_risk)}
          hint="Worst single scan"
          tone="warn"
        />
        <KpiCard
          label="Critical findings"
          value={formatNumber(dashboard.executive_summary?.critical_count)}
          hint="Severity = critical"
          tone="critical"
        />
      </section>

      <section className="kpi-grid">
        <KpiCard
          label="Firewall events"
          value={formatNumber(stats?.total_events || 0)}
          hint="In ring buffer"
        />
        <KpiCard
          label="Blocked"
          value={formatNumber(stats?.blocked || 0)}
          hint={`Block rate ${blockRatePct}`}
          tone="critical"
        />
        <KpiCard
          label="P95 overhead"
          value={`${(stats?.p95_duration_ms || 0).toFixed(1)} ms`}
          hint="Pipeline + policy gate"
        />
        <KpiCard
          label="Top blocking policy"
          value={topPolicy}
          hint="By matched count"
          mono
        />
      </section>

      <section className="dashboard-grid">
        <article className="panel">
          <div className="panel-header">
            <h2>Risk distribution</h2>
            <span className="muted">Portfolio spread by severity</span>
          </div>
          <div className="distribution-list">
            {DISTRIBUTION_ORDER.map((level) => {
              const count = Number(dashboard.risk_distribution?.[level] || 0)
              const percent = distributionTotal === 0 ? 0 : Math.round((count / distributionTotal) * 100)
              return (
                <div key={level} className="distribution-row">
                  <div className="distribution-label">{level}</div>
                  <div className="distribution-bar-wrap" role="img" aria-label={`${level}: ${count}`}>
                    <div className={`distribution-bar severity-${level}`} style={{ width: `${percent}%` }} />
                  </div>
                  <div className="distribution-value">{count}</div>
                </div>
              )
            })}
          </div>
        </article>

        <article className="panel">
          <div className="panel-header">
            <h2>System posture</h2>
            <span className="muted">Current operating context</span>
          </div>
          <div className="stat-list">
            <div>
              <span>Unique sources</span>
              <strong>{formatNumber(sources.length)}</strong>
            </div>
            <div>
              <span>Visible scans</span>
              <strong>{formatNumber(filteredScans.length)}</strong>
            </div>
            <div>
              <span>High + critical</span>
              <strong>
                {formatNumber(
                  Number(dashboard.risk_distribution?.high || 0) +
                    Number(dashboard.risk_distribution?.critical || 0),
                )}
              </strong>
            </div>
            <div>
              <span>Firewall traffic</span>
              <strong>{formatNumber(stats?.total_events || 0)}</strong>
            </div>
          </div>
        </article>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Firewall traffic</h2>
          <span className="muted">By decision</span>
        </div>
        <TrafficSparkline stats={stats} />
      </section>

      <section className="panel">
        <div className="panel-header panel-controls">
          <h2>Recent firewall events</h2>
          <Link to="/firewall" className="btn btn-secondary">
            Open AI Firewall
          </Link>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Route</th>
                <th>Direction</th>
                <th>Decision</th>
                <th>Mode</th>
                <th>Matched policies</th>
                <th>ms</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.trace_id}>
                  <td title={formatDate(event.timestamp)}>{formatRelativeTime(event.timestamp)}</td>
                  <td><code>{event.route}</code></td>
                  <td>{event.direction}</td>
                  <td><PolicyBadge decision={event.final_decision} /></td>
                  <td><span className={`mode-chip mode-${event.mode}`}>{event.mode}</span></td>
                  <td>{event.matched_policy_ids.join(', ') || '-'}</td>
                  <td>{(event.duration_ms || 0).toFixed(1)}</td>
                </tr>
              ))}
              {events.length === 0 && (
                <tr>
                  <td colSpan={7} className="empty-cell">
                    No firewall events recorded yet. Run a scan or send a request through the proxy.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel" aria-label="Scan inventory">
        <div className="panel-header panel-controls">
          <div>
            <h2>Scan inventory</h2>
            <span className="muted">
              Click a row for category breakdown, findings, and rule explanations.
            </span>
          </div>
          <div className="controls">
            <label>
              Severity
              <select
                value={severityFilter}
                onChange={(event) => setSeverityFilter(event.target.value)}
              >
                {SEVERITY_FILTERS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Source
              <select
                value={sourceFilter}
                onChange={(event) => setSourceFilter(event.target.value)}
              >
                <option value="all">all</option>
                {sources.map((source) => (
                  <option key={source} value={source}>
                    {source}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setScoreSort((current) => (current === 'desc' ? 'asc' : 'desc'))}
            >
              Sort: {scoreSort === 'desc' ? 'High to low' : 'Low to high'}
            </button>
            <button
              type="button"
              className={`btn ${portfolioEnterpriseOnly ? 'btn-secondary' : 'btn-primary'}`}
              onClick={handleExportRollupPdf}
              disabled={exportLoading || portfolioEnterpriseOnly}
              title={
                portfolioEnterpriseOnly
                  ? 'Portfolio rollup PDF export requires Valo Enterprise'
                  : 'Export portfolio rollup PDF'
              }
            >
              {portfolioEnterpriseOnly
                ? 'Rollup PDF (Enterprise)'
                : exportLoading
                  ? 'Exporting...'
                  : 'Export rollup PDF'}
            </button>
          </div>
        </div>

        {exportError && (
          <div className="message-grid in-panel">
            <article className="message-card message-error">{exportError}</article>
          </div>
        )}

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Scan ID</th>
                <th>Source</th>
                <th>Score</th>
                <th>Severity</th>
                <th>Findings</th>
                <th>Date</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredScans.map((scan) => (
                <tr
                  key={scan.scan_id}
                  className="table-row-clickable"
                  onClick={() => setSelectedScan(scan)}
                  title="Open scan detail"
                >
                  <td><code>{clipText(scan.scan_id, 22)}</code></td>
                  <td>{scan.source}</td>
                  <td>{formatScore(scan.score)}</td>
                  <td>
                    <span className={`severity-chip severity-${normalizeSeverity(scan.severity)}`}>
                      {normalizeSeverity(scan.severity)}
                    </span>
                  </td>
                  <td>{formatNumber(scan.finding_count ?? (scan.findings || []).length)}</td>
                  <td>{formatDate(scan.date)}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-secondary btn-tight"
                      onClick={(event) => {
                        event.stopPropagation()
                        handleDownloadScanPdf(scan)
                      }}
                      disabled={scanPdfLoadingId === scan.scan_id}
                      title="Download a PDF for this scan"
                    >
                      {scanPdfLoadingId === scan.scan_id ? 'PDF...' : 'PDF'}
                    </button>
                  </td>
                </tr>
              ))}
              {filteredScans.length === 0 && (
                <tr>
                  <td colSpan={7} className="empty-cell">
                    No scans match the selected filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {selectedScan && (
        <ScanDetailDrawer
          scan={selectedScan}
          onClose={() => setSelectedScan(null)}
        />
      )}
    </div>
  )
}
