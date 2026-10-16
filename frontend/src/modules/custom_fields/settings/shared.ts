import { ApiError } from '@/data'

/** A refused write in words: the problem's detail (or its first field error). */
export function problemText(error: unknown): string {
  if (error instanceof ApiError) return error.errors[0]?.message ?? error.detail
  return error instanceof Error ? error.message : 'Failed.'
}

/** A label as a key slug (`Wielder of` → `wielder_of`): lowercase letters, digits, `_`. */
export function slugify(label: string): string {
  const slug = label
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/^[0-9_]+/, '')
  return slug.slice(0, 60)
}

export const SLUG = /^[a-z][a-z0-9_]{0,59}$/

export type VisibilityChoice = '' | 'public' | 'spoiler' | 'private'

export const VISIBILITIES: { value: Exclude<VisibilityChoice, ''>; label: string }[] = [
  { value: 'public', label: 'Public' },
  { value: 'spoiler', label: 'Spoiler' },
  { value: 'private', label: 'Private' },
]
