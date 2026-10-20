import { defineModule } from '@/core/modules'

import { FontFieldEditor, FontFieldValue } from './font-field'
import { FONT } from './fonts'
import { SamplePanel, useSampleShown } from './sample-panel'
import { ScriptText } from './script-text'

/**
 * The scripts module (docs/modules/scripts.md): writing systems' fonts (`scripts.font`, a font
 * file of the media library), loaded with `@font-face`; lexicon headwords and other words of a
 * language show in its script's font (`textRenderers.language`), and a writing system's page
 * shows its sample in it.
 */
export default defineModule({
  id: 'scripts',
  dependsOn: ['languages', 'media'],
  entityPanels: [
    {
      id: 'scripts.sample',
      kinds: ['writing_system'],
      title: 'Script sample',
      component: SamplePanel,
      placement: 'main',
      order: 4,
      useShown: useSampleShown,
    },
  ],
  fieldRenderers: { [FONT]: FontFieldValue },
  fieldEditors: { [FONT]: FontFieldEditor },
  textRenderers: { language: ScriptText },
})
