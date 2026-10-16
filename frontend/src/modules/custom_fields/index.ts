import { defineModule } from '@/core/modules'

import { RelationFieldsPanel, useRelationFieldsShown } from './panels/relation-fields-panel'
import { FieldsSettings } from './settings/fields-settings'
import { KindsSettings } from './settings/kinds-settings'

// The custom_fields module (docs/modules/custom_fields.md): authors' own fields and kinds. Custom
// kinds and fields come with the server registry, so sidebar sections, create menus, search
// facets, graph colors and the generic field renderers pick them up with no code here.
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
