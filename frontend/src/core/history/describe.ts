import { docToText } from '@/core/fields'
import type { KindRegistry } from '@/core/registry'
import type { components } from '@/data'

type Change = components['schemas']['ChangeOut']
type Row = Readonly<Record<string, unknown>>

/** One readable line of a change: what changed, with the old and new values when they help. */
export interface DiffLine {
  label: string
  before?: string
  after?: string
}

/** What the descriptions look names up in. */
export interface DescribeContext {
  registry: KindRegistry | undefined
  /** Entity names by id (the changeset's entities). */
  names: ReadonlyMap<string, string>
  /** Link type labels by key (built-in and custom types: `/link-types`). */
  linkTypes?: ReadonlyMap<string, string>
  /** The entity whose history this is: link lines name the other end. */
  entityId?: string
}

// Bookkeeping columns: never shown.
const HIDDEN = new Set([
  'id',
  'kind',
  'revision',
  'created_at',
  'updated_at',
  'slug',
  'body_schema_version',
  'name_key',
  'sort_key',
  'sort_name',
  'time_status',
  'valid_from_t',
  'valid_to_t',
])
const MAX = 80

/** A value as short text (`—` for nothing). */
export function short(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  const text =
    typeof value === 'string'
      ? value
      : typeof value === 'number' || typeof value === 'boolean'
        ? String(value)
        : JSON.stringify(value)
  return text.length > MAX ? `${text.slice(0, MAX - 1)}…` : text
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const words = (doc: unknown) => docToText(doc).split(/\s+/).filter(Boolean).length
const object = (value: unknown): Row =>
  typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Row) : {}

function fieldLabel(context: DescribeContext, kind: unknown, key: string): string {
  const field =
    typeof kind === 'string'
      ? context.registry?.kind(kind)?.fields.find((candidate) => candidate.key === key)
      : undefined
  return field?.label ?? key
}

const nameOf = (context: DescribeContext, id: unknown) =>
  typeof id === 'string' ? (context.names.get(id) ?? 'an entity') : '—'

function entityLines(change: Change, context: DescribeContext): DiffLine[] {
  const before = object(change.before)
  const after = object(change.after)
  const kind = after.kind ?? before.kind
  const kindLabel =
    typeof kind === 'string'
      ? (context.registry?.kind(kind)?.label.toLowerCase() ?? kind)
      : 'entity'
  if (change.op === 'insert') return [{ label: `Created ${kindLabel} “${short(after.name)}”` }]
  if (change.op === 'delete') return [{ label: `Deleted “${short(before.name)}” permanently` }]
  const lines: DiffLine[] = []
  for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
    if (HIDDEN.has(key) || same(before[key], after[key])) continue
    const old = before[key]
    const now = after[key]
    switch (key) {
      case 'deleted_at':
        lines.push({ label: now ? 'Moved to the trash' : 'Restored from the trash' })
        break
      case 'body': {
        const label = old === null ? 'Body written' : now === null ? 'Body cleared' : 'Body edited'
        lines.push({ label, before: `${words(old)} words`, after: `${words(now)} words` })
        break
      }
      case 'fields':
      case 'field_visibility': {
        const was = object(old)
        const is = object(now)
        for (const field of new Set([...Object.keys(was), ...Object.keys(is)])) {
          if (same(was[field], is[field])) continue
          const label = fieldLabel(context, kind, field)
          lines.push({
            label: key === 'fields' ? label : `${label} visibility`,
            before: short(was[field] ?? (key === 'fields' ? null : 'default')),
            after: short(is[field] ?? (key === 'fields' ? null : 'default')),
          })
        }
        break
      }
      case 'parent_id':
        lines.push({ label: 'Parent', before: nameOf(context, old), after: nameOf(context, now) })
        break
      case 'dimension_id':
        lines.push({
          label: 'Dimension',
          before: old === null ? 'multiversal' : nameOf(context, old),
          after: now === null ? 'multiversal' : nameOf(context, now),
        })
        break
      case 'name':
      case 'summary':
      case 'visibility':
      case 'icon':
      case 'color':
        lines.push({
          label: key.charAt(0).toUpperCase() + key.slice(1),
          before: short(old),
          after: short(now),
        })
        break
      default:
        lines.push({ label: `${key.replaceAll('_', ' ')} changed` })
    }
  }
  return lines
}

function linkLines(change: Change, context: DescribeContext): DiffLine[] {
  const before = object(change.before)
  const after = object(change.after)
  const row = change.op === 'delete' ? before : after
  const key = String(row.link_type)
  const label =
    context.linkTypes?.get(key) ?? context.registry?.linkType(key)?.label ?? short(row.link_type)
  const ends = [row.source_id, row.target_id]
  const other = ends.find((id) => id !== context.entityId) ?? ends[1]
  const what = `${label} ${nameOf(context, other)}`
  if (change.op === 'insert') return [{ label: `Linked: ${what}` }]
  if (change.op === 'delete' || (after.deleted_at && !before.deleted_at)) {
    return [{ label: `Link removed: ${what}` }]
  }
  if (before.deleted_at && !after.deleted_at) return [{ label: `Link restored: ${what}` }]
  const lines: DiffLine[] = []
  for (const key of ['role', 'data', 'visibility', 'valid_from_spec', 'valid_to_spec']) {
    if (!same(before[key], after[key])) {
      lines.push({
        label: `Link ${what}: ${key.replace('_spec', '').replace('_', ' ')}`,
        before: short(before[key]),
        after: short(after[key]),
      })
    }
  }
  return lines.length > 0 ? lines : [{ label: `Link changed: ${what}` }]
}

function aliasLines(change: Change): DiffLine[] {
  const before = object(change.before)
  const after = object(change.after)
  if (change.op === 'insert') return [{ label: `Alias added: ${short(after.alias)}` }]
  if (change.op === 'delete') return [{ label: `Alias removed: ${short(before.alias)}` }]
  return [{ label: 'Alias', before: short(before.alias), after: short(after.alias) }]
}

/**
 * Readable lines for a changeset's row changes (data-model.md §7), only the entity's own with
 * `context.entityId`: entity members and fields
 * with old → new values, body edits as word counts, aliases, tags and links; other tables (module
 * rows, time) as a generic line.
 */
export function describeChanges(changes: readonly Change[], context: DescribeContext): DiffLine[] {
  // Tags created in the same changeset name the tag assignments.
  const tagNames = new Map(
    changes
      .filter((change) => change.table_name === 'tags')
      .map((change) => [change.row_id, short(object(change.after ?? change.before).name)]),
  )
  // On an entity's history: its own changes (a changeset may also touch others).
  const own =
    context.entityId === undefined
      ? changes
      : changes.filter((change) => change.entity_ids.includes(context.entityId ?? ''))
  return own.flatMap((change): DiffLine[] => {
    switch (change.table_name) {
      case 'entities':
        return entityLines(change, context)
      case 'links':
        return linkLines(change, context)
      case 'entity_aliases':
        return aliasLines(change)
      case 'tags':
        return change.op === 'update'
          ? [
              {
                label: 'Tag renamed',
                before: short(object(change.before).name),
                after: short(object(change.after).name),
              },
            ]
          : []
      case 'entity_tags': {
        const row = object(change.op === 'delete' ? change.before : change.after)
        const tag = tagNames.get(String(row.tag_id))
        const name = tag ? ` ${tag}` : ''
        return [{ label: change.op === 'delete' ? `Untagged${name}` : `Tagged${name}` }]
      }
      default: {
        const verb = { insert: 'added', update: 'changed', delete: 'removed' }[change.op]
        return [{ label: `${change.table_name.replaceAll('_', ' ')}: row ${verb}` }]
      }
    }
  })
}
