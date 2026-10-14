import type { ModuleDefinition } from '@/core/modules'

import branches from './branches'
import characters from './characters'
import correspondences from './correspondences'
import graph from './graph'
import groups from './groups'
import languages from './languages'
import locations from './locations'
import misc from './misc'
import species from './species'

// Module frontends (modules.md §3). Lists every module definition; the app activates the enabled
// ones after loading the vault registry. A module lives in `modules/<id>/` with an `index.ts`
// exporting `defineModule({ id, … })` and, for dependent modules, a `public.ts`.
export const moduleDefinitions: readonly ModuleDefinition[] = [
  misc,
  locations,
  species,
  characters,
  groups,
  languages,
  graph,
  branches,
  correspondences,
]
