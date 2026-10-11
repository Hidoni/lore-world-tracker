import { ApiError } from '@/api'

export { ApiError }

/** `409 revision_conflict`: someone saved first; the conflict dialog (#62) handles it. */
export function isRevisionConflict(error: unknown): error is ApiError {
  return error instanceof ApiError && error.code === 'revision_conflict'
}

/**
 * An API error's per-field messages, for forms: `{ "name": "…", "ext.start": "…" }` (the request
 * part `body.` is dropped from paths). Empty for other errors.
 */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {}
  const found: Record<string, string> = {}
  for (const item of error.errors) {
    const path = item.path.replace(/^body\.?/, '')
    found[path] ??= item.message
  }
  return found
}
