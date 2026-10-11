import type { ModuleDefinition } from '@/core/modules'

// Module frontends (modules.md §3). Lists every module definition; the app activates the enabled
// ones after loading the vault registry. A module lives in `modules/<id>/` with an `index.ts`
// exporting `defineModule({ id, … })` and, for dependent modules, a `public.ts`.
export const moduleDefinitions: readonly ModuleDefinition[] = []
