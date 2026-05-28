import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useOutletContext } from 'react-router-dom'

import { getEvents, getStats } from '../api/enforcement.js'
import EnforcementEventDrawer from '../components/EnforcementEventDrawer.jsx'
import EnforcementModeCard from '../components/EnforcementModeCard.jsx'
import KpiCard from '../components/KpiCard.jsx'
import PolicyBadge from '../components/PolicyBadge.jsx'
import ProxyConfigCard from '../components/ProxyConfigCard.jsx'
import {
  formatDate,
  formatNumber,
  formatRelativeTime,
} from '../lib/format.js'

const DECISION_FILTERS = [
  { value: '', label: 'All decisions' },
  { value: 'allow', label: 'Allow' },
  { value: 'warn', label: 'Warn' },
  { value: 'deny', label: 'Deny' },
]

const DIRECTION_FILTERS = [
  { value: '', label: 'All directions' },
  { value: 'ingress', label: 'Ingress' },
  { value: 'egress', label: 'Egress' },
]

const BLOCKED_FILTERS = [
  { value: '', label: 'Blocked + allowed' },
  { value: 'true', label: 'Blocked only' },
  { value: 'false', label: 'Not blocked' },
]

export default function FirewallView() {
  const { config } = useOutletContext()
  const [selectedEvent, setSelectedEvent] = useState(null)
  const [filters, setFilters] = useState({
    decision: '',
    direction: '',
    blocked: '',
    trace_id: '',
  })
  const [pollEnabled, setPollEnabled] = useState(true)

  const queryFilters = useMemo(() => {
    const out = { limit: 100 }
    if (filters.decision) out.decision = filters.decision
    if (filters.direction) out.direction = filters.direction
    if (filters.blocked) out.blocked = filters.blocked
    if (filters.trace_id.trim()) out.trace_id = filters.trace_id.trim()
    return out
  }, [filters])

  const eventsQuery = useQuery({
    queryKey: ['enforcement', 'events', queryFilters],
    queryFn: () => getEvents(queryFilters),
    refetchInterval: pollEnabled ? 3_000 : false,
    placeholderData: (previous) => previous,
  })

  const statsQuery = useQuery({
    queryKey: ['enforcement', 'stats', { window: 0 }],
    queryFn: () => getStats({ window_seconds: 0, top_n: 5 }),
    refetchInterval: pollEnabled ? 5_000 : false,
  })

  const events = eventsQuery.data?.events || []
  const total = eventsQuery.data?.total || 0
  const capacity = eventsQuery.data?.capacity || config?.event_buffer_capacity || 0
  const stats = statsQuery.data

  const blockRatePct = stats ? `${(stats.block_rate * 100).toFixed(1)}%` : '-'
  const topPolicy = stats?.top_policies?.[0]
  const eventsError = eventsQuery.isError ? eventsQuery.error?.message : null

  return (
    <div className="view-stack">
      <section className="kpi-grid">
        <KpiCard
          label="Events in buffer"
          value={`${formatNumber(stats?.total_events || 0)} / ${formatNumber(capacity)}`}
          hint="In-memory ring buffer"
        />
        <KpiCard
          label="Blocked"
          value={formatNumber(stats?.blocked || 0)}
          hint={`Block rate ${blockRatePct}`}
          tone="critical"
        />
        <KpiCard
          label="Would block"
          value={formatNumber(stats?.would_block || 0)}
          hint="Deny matched (any mode)"
          tone="warn"
        />
        <KpiCard
          label="P95 overhead"
          value={`${(stats?.p95_duration_ms || 0).toFixed(1)} ms`}
          hint={`P50 ${(stats?.p50_duration_ms || 0).toFixed(1)} ms`}
        />
      </section>

      <section className="firewall-grid">
        <EnforcementModeCard config={config} />
        <ProxyConfigCard config={config} />
      </section>

      <section className="firewall-grid-secondary">
        <article className="panel">
          <div className="panel-header">
            <h2>Top blocking policies</h2>
            <span className="muted">By matched count</span>
          </div>
          {(stats?.top_policies || []).length === 0 ? (
            <p className="muted">No policy matches recorded yet.</p>
          ) : (
            <ul className="top-policy-list">
              {stats.top_policies.map((policy) => (
                <li key={policy.policy_id} className="top-policy-row">
                  <code>{policy.policy_id}</code>
                  <span className="muted">{formatNumber(policy.matches)} matches</span>
                </li>
              ))}
            </ul>
          )}
          {topPolicy && (
            <p className="muted small top-gap">
              Most active: <code>{topPolicy.policy_id}</code>
            </p>
          )}
        </article>

        <article className="panel">
          <div className="panel-header">
            <h2>Top routes</h2>
            <span className="muted">By request volume</span>
          </div>
          {(stats?.top_routes || []).length === 0 ? (
            <p className="muted">No traffic recorded yet.</p>
          ) : (
            <ul className="top-policy-list">
              {stats.top_routes.map((route) => (
                <li key={route.route} className="top-policy-row">
                  <code>{route.route}</code>
                  <span className="muted">{formatNumber(route.requests)} reqs</span>
                </li>
              ))}
            </ul>
          )}
        </article>
      </section>

      <section className="panel">
        <div className="panel-header panel-controls">
          <h2>Live traffic</h2>
          <div className="controls">
            <label>
              Decision
              <select
                value={filters.decision}
                onChange={(event) => setFilters((current) => ({ ...current, decision: event.target.value }))}
              >
                {DECISION_FILTERS.map((option) => (
                  <option key={option.value || 'all-decisions'} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Direction
              <select
                value={filters.direction}
                onChange={(event) => setFilters((current) => ({ ...current, direction: event.target.value }))}
              >
                {DIRECTION_FILTERS.map((option) => (
                  <option key={option.value || 'all-directions'} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Blocked
              <select
                value={filters.blocked}
                onChange={(event) => setFilters((current) => ({ ...current, blocked: event.target.value }))}
              >
                {BLOCKED_FILTERS.map((option) => (
                  <option key={option.value || 'all-blocked'} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Trace
              <input
                type="text"
                value={filters.trace_id}
                onChange={(event) => setFilters((current) => ({ ...current, trace_id: event.target.value }))}
                placeholder="trace id"
                className="trace-input"
              />
            </label>
            <button
              type="button"
              className={`btn btn-secondary${pollEnabled ? ' btn-active' : ''}`}
              onClick={() => setPollEnabled((current) => !current)}
            >
              {pollEnabled ? 'Pause auto-refresh' : 'Resume auto-refresh'}
            </button>
          </div>
        </div>

        <p className="muted small">
          Showing {events.length} of {total} matching events. Auto-refresh every 3 seconds when enabled.
        </p>

        {eventsError && (
          <article className="message-card message-error in-panel">{eventsError}</article>
        )}

        <div className="table-wrap">
          <table className="firewall-traffic-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Route</th>
                <th>Direction</th>
                <th>Decision</th>
                <th>Blocked</th>
                <th>Mode</th>
                <th>Matched</th>
                <th>ms</th>
                <th>Trace</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr
                  key={event.trace_id + event.timestamp}
                  className={`table-row-clickable ${event.blocked ? 'row-blocked' : ''}`}
                  onClick={() => setSelectedEvent(event)}
                  title="Click for full detail"
                >
                  <td title={formatDate(event.timestamp)}>{formatRelativeTime(event.timestamp)}</td>
                  <td><code>{event.route}</code></td>
                  <td>{event.direction}</td>
                  <td><PolicyBadge decision={event.final_decision} /></td>
                  <td>
                    {event.blocked ? (
                      <span className="severity-chip severity-critical">blocked</span>
                    ) : event.would_block ? (
                      <span className="severity-chip severity-high">would block</span>
                    ) : (
                      <span className="muted">-</span>
                    )}
                  </td>
                  <td><span className={`mode-chip mode-${event.mode}`}>{event.mode}</span></td>
                  <td>{event.matched_policy_ids.join(', ') || '-'}</td>
                  <td>{(event.duration_ms || 0).toFixed(1)}</td>
                  <td><code>{event.trace_id.slice(0, 8)}</code></td>
                </tr>
              ))}
              {events.length === 0 && (
                <tr>
                  <td colSpan={9} className="empty-cell">
                    No events match the current filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {selectedEvent && (
        <EnforcementEventDrawer event={selectedEvent} onClose={() => setSelectedEvent(null)} />
      )}
    </div>
  )
}
