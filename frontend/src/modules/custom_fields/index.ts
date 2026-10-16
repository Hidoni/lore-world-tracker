import { createElement } from 'react'

import { defineModule, lazyComponent } from '@/core/modules'

import { RelationFieldsPanel, useRelationFieldsShown } from './panels/relation-fields-panel'

// The custom_fields module (docs/modules/custom_fields.md): authors' own fields and kinds. Custom
// kinds and fields come with the server registry, so sidebar sections, create menus, search
// facets, graph colors and the generic field renderers pick them up with no code here.
// The settings pages load when opened or when the vault is idle (frontend.md §12). Until then a
// page shows its own fallback: suspending inside the router's transition would keep the page
// navigated from on screen.
const loading = createElement('p', { className: 'text-sm text-muted-foreground' }, 'Loading…')
const KindsSettings = lazyComponent(
  async () => (await import('./settings/kinds-settings')).KindsSettings,
  loading,
)
const FieldsSettings = lazyComponent(
  async () => (await import('./settings/fields-settings')).FieldsSettings,
  loading,
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
