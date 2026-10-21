import { lazyComponent } from '@/core/modules'
import type { Kind } from '@/core/registry'

/** Kinds a user creates through this dialog: system kinds (dimensions, calendars…) have wizards. */
export function creatableKinds(kinds: readonly Kind[]): Kind[] {
  return kinds.filter((kind) => !kind.capabilities.is_system)
}

/**
 * Create an entity of any kind (`create-entity-form.tsx`), loaded when first opened: its form
 * (react-hook-form, zod, the field editors) stays out of the shell (frontend.md §12).
 */
export const CreateEntityDialog = lazyComponent(
  async () => (await import('./create-entity-form')).CreateEntityDialog,
)
