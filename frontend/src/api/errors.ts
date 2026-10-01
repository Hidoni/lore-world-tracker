import type { components } from './schema.gen'

export type Problem = components['schemas']['Problem']
export type ProblemErrorItem = components['schemas']['ProblemErrorItem']

export const PROBLEM_MEDIA_TYPE = 'application/problem+json'

interface ApiErrorInit {
  status: number
  code: string
  title: string
  detail: string
  errors?: ProblemErrorItem[] | null
  context?: Record<string, unknown> | null
}

/**
 * A failed API request. Built from the RFC 9457 problem body (api.md §1); responses that are not
 * problems (e.g. a proxy's 502 page) get the code `http_<status>`, like unmapped server errors.
 */
export class ApiError extends Error {
  override readonly name = 'ApiError'
  readonly status: number
  /** Stable machine identifier (api.md §3), e.g. `not_found` or `revision_conflict`. */
  readonly code: string
  readonly title: string
  readonly detail: string
  /** Per-field errors (`path` is dotted, e.g. `body.name`); empty when the problem has none. */
  readonly errors: readonly ProblemErrorItem[]
  readonly context: Readonly<Record<string, unknown>>

  constructor({ status, code, title, detail, errors, context }: ApiErrorInit) {
    super(detail)
    this.status = status
    this.code = code
    this.title = title
    this.detail = detail
    this.errors = errors ?? []
    this.context = context ?? {}
  }
}

function isProblem(body: unknown): body is Problem {
  if (typeof body !== 'object' || body === null) return false
  const { status, code, title, detail } = body as Record<string, unknown>
  return (
    typeof status === 'number' &&
    typeof code === 'string' &&
    typeof title === 'string' &&
    typeof detail === 'string'
  )
}

function isProblemResponse(response: Response): boolean {
  const mediaType = response.headers.get('content-type')?.split(';')[0]?.trim().toLowerCase()
  return mediaType === PROBLEM_MEDIA_TYPE
}

/** Converts a failed response into an `ApiError` without consuming the original body. */
export async function toApiError(response: Response): Promise<ApiError> {
  if (isProblemResponse(response)) {
    const body: unknown = await response
      .clone()
      .json()
      .catch(() => null)
    if (isProblem(body)) return new ApiError(body)
  }
  const title = response.statusText || `HTTP ${response.status}`
  return new ApiError({
    status: response.status,
    code: `http_${response.status}`,
    title,
    detail: title,
  })
}
