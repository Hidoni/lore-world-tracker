import type { components } from '@/data'

type LinkType = components['schemas']['LinkTypeOut']

/**
 * The relation fields of a kind (custom_fields.md, Concepts): custom link types whose sources are
 * listed kinds including it, shown like fields on its entities' pages.
 */
export function relationTypesOf(types: readonly LinkType[], kind: string): LinkType[] {
  return types.filter(
    (type) =>
      type.user_defined && Array.isArray(type.source_kinds) && type.source_kinds.includes(kind),
  )
}
