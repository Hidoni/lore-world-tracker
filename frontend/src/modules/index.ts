import type { ModuleDefinition } from '@/core/modules'

import characters from './characters'
import groups from './groups'
import languages from './languages'
import locations from './locations'
import misc from './misc'

// Module frontends (modules.md §3). Lists every module definition; the app activates the enabled
// ones after loading the vault registry. A module lives in `modules/<id>/` with an `index.ts`
// exporting `defineModule({ id, … })` and, for dependent modules, a `public.ts`.
export const moduleDefinitions: readonly ModuleDefinition[] = [
  misc,
  locations,
  characters,
  groups,
  languages,
]
