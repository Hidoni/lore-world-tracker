import { lazy } from 'react'

import { defineModule } from '@/core/modules'

import { RelationFieldsPanel, useRelationFieldsShown } from './panels/relation-fields-panel'

// The custom_fields module (docs/modules/custom_fields.md): authors' own fields and kinds. Custom
// kinds and fields come with the server registry, so sidebar sections, create menus, search
// facets, graph colors and the generic field renderers pick them up with no code here.
// The settings pages load when opened (frontend.md §12).
const KindsSettings = lazy(() =>
  import('./settings/kinds-settings').then((loaded) => ({ default: loaded.KindsSettings })),
)
const FieldsSettings = lazy(() =>
  import('./settings/fields-settings').then((loaded) => ({ default: loaded.FieldsSettings })),
)

export default defineModule({
  id: 'custom_fields',
  settingsPages: [
    { id: 'kinds', title: 'Kinds', component: KindsSettings },
    { id: 'fields', title: 'Fields', component: FieldsSettings },
  ],
  entityPanels: [
    {
      id: 'custom_fields.relations',
      kinds: '*',
      title: 'Relation fields',
      component: RelationFieldsPanel,
      placement: 'main',
      order: 5,
      useShown: useRelationFieldsShown,
    },
  ],
})
