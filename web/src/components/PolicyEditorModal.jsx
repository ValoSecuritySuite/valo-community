import { useEffect, useMemo, useState } from 'react'

import { createPolicy, updatePolicy, validatePolicy } from '../api/policies.js'

const CONDITION_OPS = [
  'eq',
  'ne',
  'gt',
  'gte',
  'lt',
  'lte',
  'in',
  'not_in',
  'contains',
  'matches',
  'exists',
  'not_exists',
]

const DECISIONS = ['allow', 'warn', 'deny']
const VALUELESS_OPS = new Set(['exists', 'not_exists'])

function newCondition() {
  return { field: '', op: 'eq', valueRaw: '' }
}

function emptyDraft() {
  return {
    id: '',
    name: '',
    description: '',
    enabled: true,
    enforce: true,
    when: [newCondition()],
    then: { decision: 'warn', severity: 4, message: '' },
    tagsRaw: '',
    version: 1,
  }
}

function policyToDraft(policy) {
  if (!policy) return emptyDraft()
  return {
    id: policy.id || '',
    name: policy.name || '',
    description: policy.description || '',
    enabled: policy.enabled !== false,
    enforce: policy.enforce !== false,
    when: (policy.when || []).map((cond) => ({
      field: cond.field || '',
      op: cond.op || 'eq',
      valueRaw:
        cond.value === undefined || cond.value === null ? '' : JSON.stringify(cond.value),
    })),
    then: {
      decision: policy.then?.decision || 'warn',
      severity: Number(policy.then?.severity ?? 4),
      message: policy.then?.message || '',
    },
    tagsRaw: (policy.tags || []).join(', '),
    version: Number(policy.version || 1),
  }
}

function parseValueRaw(raw, op) {
  if (VALUELESS_OPS.has(op)) {
    return { ok: true, value: null }
  }
  const trimmed = String(raw ?? '').trim()
  if (!trimmed) {
    return { ok: false, error: 'value is required for this operator' }
  }
  try {
    return { ok: true, value: JSON.parse(trimmed) }
  } catch {
    // Fall back to plain string if not valid JSON.
    return { ok: true, value: trimmed }
  }
}

function draftToPolicy(draft) {
  const errors = []
  if (!draft.id || !/^[a-zA-Z0-9_-]+$/.test(draft.id)) {
    errors.push('id must be a slug: letters, digits, underscores, or hyphens only')
  }
  if (!draft.name) errors.push('name is required')
  if (!draft.then.message) errors.push('decision message is required')

  const when = []
  draft.when.forEach((cond, idx) => {
    if (!cond.field) {
      errors.push(`Condition ${idx + 1}: field is required`)
      return
    }
    if (!CONDITION_OPS.includes(cond.op)) {
      errors.push(`Condition ${idx + 1}: invalid op`)
      return
    }
    const parsed = parseValueRaw(cond.valueRaw, cond.op)
    if (!parsed.ok) {
      errors.push(`Condition ${idx + 1}: ${parsed.error}`)
      return
    }
    when.push({ field: cond.field, op: cond.op, value: parsed.value })
  })

  const tags = draft.tagsRaw
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean)

  if (errors.length > 0) {
    return { ok: false, errors }
  }

  return {
    ok: true,
    policy: {
      id: draft.id,
      name: draft.name,
      description: draft.description || null,
      enabled: Boolean(draft.enabled),
      enforce: Boolean(draft.enforce),
      when,
      then: {
        decision: draft.then.decision,
        severity: Number(draft.then.severity || 0),
        message: draft.then.message,
      },
      tags,
      version: Number(draft.version || 1),
    },
  }
}

export default function PolicyEditorModal({ mode = 'create', policy, onClose, onSaved }) {
  const [draft, setDraft] = useState(() => policyToDraft(policy))
  const [submitting, setSubmitting] = useState(false)
  const [errors, setErrors] = useState([])
  const [validationErrors, setValidationErrors] = useState([])

  const isEdit = mode === 'edit'

  useEffect(() => {
    setDraft(policyToDraft(policy))
    setErrors([])
    setValidationErrors([])
  }, [policy])

  const updateDraft = (patch) => setDraft((current) => ({ ...current, ...patch }))
  const updateThen = (patch) =>
    setDraft((current) => ({ ...current, then: { ...current.then, ...patch } }))

  const updateCondition = (idx, patch) =>
    setDraft((current) => ({
      ...current,
      when: current.when.map((cond, index) => (index === idx ? { ...cond, ...patch } : cond)),
    }))

  const removeCondition = (idx) =>
    setDraft((current) => ({
      ...current,
      when: current.when.filter((_, index) => index !== idx),
    }))

  const addCondition = () =>
    setDraft((current) => ({ ...current, when: [...current.when, newCondition()] }))

  const conditionRows = useMemo(() => draft.when, [draft.when])

  const handleSave = async () => {
    setErrors([])
    setValidationErrors([])
    const built = draftToPolicy(draft)
    if (!built.ok) {
      setErrors(built.errors)
      return
    }

    setSubmitting(true)
    try {
      const validation = await validatePolicy(built.policy)
      if (!validation.valid) {
        setValidationErrors(validation.errors || ['Server rejected policy schema'])
        return
      }

      const saved = isEdit
        ? await updatePolicy(built.policy.id, built.policy)
        : await createPolicy(built.policy)
      onSaved(saved)
    } catch (err) {
      setErrors([err.message || 'Failed to save policy'])
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal policy-editor-modal"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-header">
          <h2>{isEdit ? `Edit Policy: ${draft.id}` : 'New Governance Policy'}</h2>
          <div className="settings-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleSave}
              disabled={submitting}
            >
              {submitting ? 'Saving...' : isEdit ? 'Save Changes' : 'Create Policy'}
            </button>
          </div>
        </div>

        {(errors.length > 0 || validationErrors.length > 0) && (
          <section className="message-grid">
            {errors.map((message, index) => (
              <article className="message-card message-error" key={`form-err-${index}`}>
                {message}
              </article>
            ))}
            {validationErrors.map((message, index) => (
              <article className="message-card message-error" key={`server-err-${index}`}>
                {message}
              </article>
            ))}
          </section>
        )}

        <section className="modal-section">
          <h3>Identification</h3>
          <div className="settings-form-grid">
            <label className="field-label">
              ID (slug)
              <input
                type="text"
                value={draft.id}
                onChange={(event) => updateDraft({ id: event.target.value })}
                placeholder="block_high_risk"
                disabled={isEdit}
              />
            </label>
            <label className="field-label">
              Name
              <input
                type="text"
                value={draft.name}
                onChange={(event) => updateDraft({ name: event.target.value })}
                placeholder="Block high-risk prompts"
              />
            </label>
            <label className="field-label setting-card-wide">
              Description
              <textarea
                value={draft.description}
                onChange={(event) => updateDraft({ description: event.target.value })}
                rows={2}
                placeholder="Optional explanation surfaced in audit trails."
              />
            </label>
            <label className="field-label settings-toggle">
              <span>Enabled</span>
              <input
                type="checkbox"
                checked={draft.enabled}
                onChange={(event) => updateDraft({ enabled: event.target.checked })}
              />
            </label>
            <label className="field-label settings-toggle">
              <span>
                Enforce when blocking
                <span className="muted small block-note">
                  When off, this policy emits decisions but never blocks (soft rollout).
                </span>
              </span>
              <input
                type="checkbox"
                checked={draft.enforce}
                onChange={(event) => updateDraft({ enforce: event.target.checked })}
              />
            </label>
            <label className="field-label">
              Version
              <input
                type="number"
                min={1}
                value={draft.version}
                onChange={(event) => updateDraft({ version: Number(event.target.value || 1) })}
              />
            </label>
            <label className="field-label setting-card-wide">
              Tags (comma separated)
              <input
                type="text"
                value={draft.tagsRaw}
                onChange={(event) => updateDraft({ tagsRaw: event.target.value })}
                placeholder="compliance:soc2, pii"
              />
            </label>
          </div>
        </section>

        <section className="modal-section">
          <div className="panel-header">
            <h3>When (AND)</h3>
            <button type="button" className="btn btn-secondary" onClick={addCondition}>
              Add Condition
            </button>
          </div>

          <div className="condition-list">
            {conditionRows.map((cond, idx) => (
              <div className="condition-row" key={`cond-${idx}`}>
                <label className="field-label">
                  Field
                  <input
                    type="text"
                    value={cond.field}
                    onChange={(event) => updateCondition(idx, { field: event.target.value })}
                    placeholder="combined_score"
                  />
                </label>
                <label className="field-label">
                  Op
                  <select
                    value={cond.op}
                    onChange={(event) => updateCondition(idx, { op: event.target.value })}
                  >
                    {CONDITION_OPS.map((op) => (
                      <option key={op} value={op}>
                        {op}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field-label">
                  Value (JSON)
                  <input
                    type="text"
                    value={cond.valueRaw}
                    onChange={(event) => updateCondition(idx, { valueRaw: event.target.value })}
                    placeholder={VALUELESS_OPS.has(cond.op) ? '(not used)' : '80 / "secret_signal" / true'}
                    disabled={VALUELESS_OPS.has(cond.op)}
                  />
                </label>
                <button
                  type="button"
                  className="btn btn-secondary condition-remove"
                  onClick={() => removeCondition(idx)}
                  disabled={draft.when.length <= 1}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>

          <p className="muted top-gap-small">
            All conditions must match (AND). Empty when-list matches every context.
          </p>
        </section>

        <section className="modal-section">
          <h3>Then</h3>
          <div className="settings-form-grid">
            <label className="field-label">
              Decision
              <select
                value={draft.then.decision}
                onChange={(event) => updateThen({ decision: event.target.value })}
              >
                {DECISIONS.map((decision) => (
                  <option key={decision} value={decision}>
                    {decision}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-label">
              Severity (0-10)
              <input
                type="number"
                min={0}
                max={10}
                value={draft.then.severity}
                onChange={(event) => updateThen({ severity: Number(event.target.value || 0) })}
              />
            </label>
            <label className="field-label setting-card-wide">
              Message
              <textarea
                value={draft.then.message}
                onChange={(event) => updateThen({ message: event.target.value })}
                rows={2}
                placeholder="Combined score crosses the deny threshold."
              />
            </label>
          </div>
        </section>
      </div>
    </div>
  )
}
