import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { patchConfig } from '../api/enforcement.js'

const MODES = [
  {
    key: 'off',
    label: 'Off',
    blurb: 'Inspection disabled. The middleware passes every request through untouched.',
    tone: 'mode-card-off',
  },
  {
    key: 'monitor',
    label: 'Monitor',
    blurb: 'Decisions are computed and logged but never block. Recommended for staged rollouts.',
    tone: 'mode-card-monitor',
  },
  {
    key: 'enforce',
    label: 'Enforce',
    blurb: 'Deny verdicts return HTTP 403 PolicyDenied. Per-policy enforce flag is honoured.',
    tone: 'mode-card-enforce',
  },
]

export default function EnforcementModeCard({ config }) {
  const queryClient = useQueryClient()
  const [pending, setPending] = useState(null)
  const [error, setError] = useState(null)

  const mutation = useMutation({
    mutationFn: (mode) => patchConfig({ enforcement_mode: mode }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['enforcement'] })
      setPending(null)
      setError(null)
    },
    onError: (err) => {
      setError(err?.message || 'Failed to update mode')
      setPending(null)
    },
  })

  const currentMode = config?.enforcement_mode || 'monitor'

  return (
    <article className="panel mode-card-panel">
      <div className="panel-header">
        <h2>Enforcement mode</h2>
        <span className="muted">Global setting, applies to ingress and egress</span>
      </div>

      <div className="mode-card-grid">
        {MODES.map((option) => {
          const active = option.key === currentMode
          const isPending = pending === option.key && mutation.isPending
          return (
            <button
              type="button"
              key={option.key}
              className={`mode-card ${option.tone}${active ? ' mode-card-active' : ''}`}
              onClick={() => {
                if (active) return
                setPending(option.key)
                mutation.mutate(option.key)
              }}
              disabled={mutation.isPending}
              aria-pressed={active}
            >
              <div className="mode-card-head">
                <span className="mode-card-label">{option.label}</span>
                {active && <span className="mode-card-badge">Active</span>}
                {isPending && <span className="mode-card-badge">Switching...</span>}
              </div>
              <p className="mode-card-blurb muted">{option.blurb}</p>
            </button>
          )
        })}
      </div>

      {error && <article className="message-card message-error in-panel">{error}</article>}
    </article>
  )
}
