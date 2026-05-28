import { useMemo } from 'react'

export default function JsonContextEditor({
  value,
  onChange,
  placeholder = '{\n  "combined_score": 90,\n  "contains_email": true\n}',
  rows = 8,
  presets = [],
  label = 'Context (JSON)',
  helpText = 'Pass any keys referenced by your YAML rules or policies. Booleans, numbers, strings, lists supported.',
}) {
  const parseStatus = useMemo(() => {
    if (!value || !value.trim()) {
      return { kind: 'empty' }
    }
    try {
      const parsed = JSON.parse(value)
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return { kind: 'error', message: 'Context must be a JSON object.' }
      }
      return { kind: 'ok', parsed }
    } catch (err) {
      return { kind: 'error', message: err.message }
    }
  }, [value])

  return (
    <div className="json-editor-wrap">
      <label className="field-label">
        {label}
        <textarea
          className="json-editor"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          rows={rows}
          spellCheck={false}
          placeholder={placeholder}
        />
      </label>
      {presets.length > 0 && (
        <div className="context-presets">
          <span className="muted">Presets:</span>
          {presets.map((preset) => (
            <button
              type="button"
              key={preset.label}
              className="btn btn-secondary"
              onClick={() => onChange(JSON.stringify(preset.value, null, 2))}
            >
              {preset.label}
            </button>
          ))}
        </div>
      )}
      {parseStatus.kind === 'error' && (
        <article className="message-card message-error in-panel">
          Invalid JSON: {parseStatus.message}
        </article>
      )}
      {parseStatus.kind === 'empty' && helpText && (
        <p className="muted top-gap-small">{helpText}</p>
      )}
    </div>
  )
}
