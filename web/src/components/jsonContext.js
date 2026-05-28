export function parseContext(value) {
  if (!value || !value.trim()) {
    return { ok: true, value: {} }
  }
  try {
    const parsed = JSON.parse(value)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { ok: false, error: 'Context must be a JSON object.' }
    }
    return { ok: true, value: parsed }
  } catch (err) {
    return { ok: false, error: err.message }
  }
}
