import type { KindRegistry } from '@/core/registry'

const article = (noun: string) => `${/^[aeiou]/i.test(noun) ? 'an' : 'a'} ${noun}`
const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)

/** What reparenting needs to know about an entity in the tree. */
export interface TreeEntity {
  id: string
  name: string
  kind: string
  dimension_id: string | null
  parent_id: string | null
}

export type ReparentCheck = { ok: true } | { ok: false; reason: string }

/**
 * Whether `dragged` may move under `target` (`null`: to the roots), mirroring the server's rules
 * (`data-model.md` §3.4): the target's kind must be an allowed parent, no cycles (`targetPath`: the
 * target's ancestor ids, root first), and both in the same dimension unless one is multiversal.
 * The server checks again; this keeps invalid drops from being offered.
 */
export function canReparent(
  registry: KindRegistry,
  dragged: TreeEntity,
  target: TreeEntity | null,
  targetPath: readonly string[] = [],
): ReparentCheck {
  if (target === null) {
    return dragged.parent_id === null ? { ok: false, reason: 'Already at the top' } : { ok: true }
  }
  if (target.id === dragged.id) return { ok: false, reason: 'Can’t move an entity into itself' }
  if (dragged.parent_id === target.id) return { ok: false, reason: `Already in ${target.name}` }
  if (targetPath.includes(dragged.id)) {
    return { ok: false, reason: `${target.name} is inside ${dragged.name}` }
  }
  const kind = registry.kind(dragged.kind)
  const targetKind = registry.kind(target.kind)
  if (!kind?.allowedParents.includes(target.kind)) {
    const what = kind?.label.toLowerCase() ?? dragged.kind
    const where = targetKind?.label.toLowerCase() ?? target.kind
    return { ok: false, reason: `${capitalize(article(what))} can’t be inside ${article(where)}` }
  }
  if (
    dragged.dimension_id !== null &&
    target.dimension_id !== null &&
    dragged.dimension_id !== target.dimension_id
  ) {
    return { ok: false, reason: `${target.name} is in another dimension` }
  }
  return { ok: true }
}

/** The kinds that may be created under an entity of `parentKind` (allowed parents, creatable). */
export function childKinds(registry: KindRegistry, parentKind: string) {
  return registry.kinds.filter(
    (kind) => !kind.capabilities.is_system && kind.allowedParents.includes(parentKind),
  )
}
