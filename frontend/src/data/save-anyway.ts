import { ApiError, type components } from '@/api'

import type { Mutations } from './source'

type SuppressItem = components['schemas']['SuppressItem']

/** A finding that blocked a write (`422 consistency_error`, `context.findings`). */
export interface BlockingFinding {
  fingerprint: string
  rule_id: string
  message: string
  certainty: string
  /** Entity ids. */
  subjects: string[]
  /** `false` for hard rules: the write can't be saved anyway. */
  suppressible: boolean
}

/**
 * Asks the author whether to save anyway: resolves to their note, or `null` to give up. When a
 * finding isn't suppressible (a hard rule) it only shows why the write was refused (`null`).
 */
export type SaveAnywayPrompt = (
  vault: string,
  findings: BlockingFinding[],
) => Promise<string | null>

export function isConsistencyError(error: unknown): error is ApiError {
  return error instanceof ApiError && error.code === 'consistency_error'
}

/** The findings a `422 consistency_error` lists. */
export function blockingFindings(error: ApiError): BlockingFinding[] {
  const found = error.context.findings
  if (!Array.isArray(found)) return []
  return found.flatMap((item: unknown): BlockingFinding[] => {
    if (item === null || typeof item !== 'object') return []
    const record = item as Record<string, unknown>
    const text = (key: string) => (typeof record[key] === 'string' ? record[key] : '')
    return [
      {
        fingerprint: text('fingerprint'),
        rule_id: text('rule_id'),
        message: text('message'),
        certainty: text('certainty'),
        subjects: Array.isArray(record.subjects)
          ? record.subjects.filter((id): id is string => typeof id === 'string')
          : [],
        suppressible: record.suppressible === true,
      },
    ]
  })
}

/**
 * Suppressions for a resend: by rule, since a create's findings name an id that is new on every
 * attempt (consistency.md §3).
 */
function suppressions(findings: readonly BlockingFinding[], note: string): SuppressItem[] {
  return [...new Set(findings.map((finding) => finding.rule_id))].map((rule_id) => ({
    rule_id,
    note,
  }))
}

/**
 * `Mutations` whose writes handle `422 consistency_error` (consistency.md §5): `prompt` shows the
 * blocking findings and, when all are suppressible, asks for a note; the write is then resent with
 * `suppress`. Otherwise (or when the author gives up) the error goes to the caller.
 */
export function withSaveAnyway(mutations: Mutations, prompt: SaveAnywayPrompt): Mutations {
  async function guarded<T>(
    vault: string,
    send: (suppress?: SuppressItem[]) => Promise<T>,
  ): Promise<T> {
    try {
      return await send()
    } catch (error) {
      if (!isConsistencyError(error)) throw error
      const findings = blockingFindings(error)
      if (findings.length === 0) throw error
      const note = await prompt(vault, findings)
      if (note === null || findings.some((finding) => !finding.suppressible)) throw error
      return send(suppressions(findings, note))
    }
  }
  return {
    ...mutations,
    createEntity: (vault, body) =>
      guarded(vault, (suppress) =>
        mutations.createEntity(vault, suppress ? { ...body, suppress } : body),
      ),
    updateEntity: (vault, id, body) =>
      guarded(vault, (suppress) =>
        mutations.updateEntity(vault, id, suppress ? { ...body, suppress } : body),
      ),
    deleteEntity: (vault, id, options) =>
      guarded(vault, (suppress) =>
        mutations.deleteEntity(
          vault,
          id,
          suppress ? { ...options, suppress: { suppress } } : options,
        ),
      ),
    restoreEntity: (vault, id, given) =>
      guarded(vault, (suppress) =>
        mutations.restoreEntity(vault, id, suppress ? { suppress } : given),
      ),
    createLink: (vault, body) =>
      guarded(vault, (suppress) =>
        mutations.createLink(vault, suppress ? { ...body, suppress } : body),
      ),
    updateLink: (vault, id, body) =>
      guarded(vault, (suppress) =>
        mutations.updateLink(vault, id, suppress ? { ...body, suppress } : body),
      ),
    deleteLink: (vault, id, given) =>
      guarded(vault, (suppress) =>
        mutations.deleteLink(vault, id, suppress ? { suppress } : given),
      ),
  }
}
