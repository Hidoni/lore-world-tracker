import type { components } from '@/data'

export type LinkTypeOut = components['schemas']['LinkTypeOut']

/** A link type as offered from one entity: forward, or reversed (the entity is the target). */
export interface LinkOption {
  /** `<type key>` or `<type key>:reverse`. */
  id: string
  type: LinkTypeOut
  /** The entity is the link's target (the inverse label reads from its side). */
  reversed: boolean
  label: string
}

const fits = (kinds: LinkTypeOut['source_kinds'], kind: string) =>
  kinds === '*' || kinds.includes(kind)

/**
 * The link types an entity of kind `here` can use with an entity of kind `there` (`null`: not
 * chosen yet), each in the directions the type's source/target kinds allow (`data-model.md` §6.2).
 * Archived types take no new links; symmetric types have one direction.
 */
export function linkOptions(
  types: readonly LinkTypeOut[],
  here: string,
  there: string | null,
): LinkOption[] {
  const options: LinkOption[] = []
  for (const type of types) {
    if (type.archived) continue
    if (fits(type.source_kinds, here) && (there === null || fits(type.target_kinds, there))) {
      options.push({ id: type.key, type, reversed: false, label: type.label })
    }
    if (
      !type.symmetric &&
      fits(type.target_kinds, here) &&
      (there === null || fits(type.source_kinds, there))
    ) {
      options.push({
        id: `${type.key}:reverse`,
        type,
        reversed: true,
        label: type.inverse_label ?? `${type.label} (reverse)`,
      })
    }
  }
  return options.sort((a, b) => a.label.localeCompare(b.label))
}
