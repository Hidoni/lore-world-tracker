import { createElement } from 'react'

import { defineModule, lazyComponent } from '@/core/modules'

// The mcp module (docs/modules/mcp.md): AI assistants over the Model Context Protocol. The server
// serves the endpoint; the app has one settings page, loaded when opened.
const loading = createElement('p', { className: 'text-sm text-muted-foreground' }, 'Loading…')
const AiAccessSettings = lazyComponent(
  async () => (await import('./settings/ai-access')).AiAccessSettings,
  loading,
)

export default defineModule({
  id: 'mcp',
  settingsPages: [{ id: 'ai-access', title: 'AI access', component: AiAccessSettings }],
})
