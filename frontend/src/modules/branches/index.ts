import { defineModule } from '@/core/modules'

/**
 * The branches module (docs/modules/branches.md): "what if" timelines. Branching itself is core
 * (the timeline switcher, badges on inherited records, overrides); this definition marks the
 * module active so the UI offers creating and editing branches.
 */
export default defineModule({
  id: 'branches',
})
