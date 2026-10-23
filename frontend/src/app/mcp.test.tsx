import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import mcp from '@/modules/mcp'
import {
  claudeCodeCommand,
  claudeDesktopConfig,
  endpointUrl,
  serverName,
} from '@/modules/mcp/settings/ai-access'
import { serveVault, type ModuleStateRow } from '@/test/fake-vault'
import { server } from '@/test/msw'
import { renderApp } from '@/test/render-app'

const state = (settings: Record<string, string>): ModuleStateRow => ({
  id: 'mcp',
  name: 'AI assistants (MCP)',
  description: 'Assistants.',
  depends_on: [],
  default_enabled: false,
  enabled: true,
  settings,
})

/** The token routes: `source` as the server reports it; returns the regenerate calls. */
function serveToken(source: 'file' | 'environment' = 'file') {
  let token = 'first-token'
  const regenerated: string[] = []
  server.use(
    http.get('*/api/v1/vaults/v1/m/mcp/token', () => HttpResponse.json({ token, source })),
    http.post('*/api/v1/vaults/v1/m/mcp/token/regenerate', () => {
      token = 'second-token'
      regenerated.push(token)
      return HttpResponse.json({ token, source })
    }),
  )
  return regenerated
}

describe('AI access settings', () => {
  it('sets the access level and writes', async () => {
    const writes = serveVault({ moduleStates: [state({ access: 'readers', writes: 'off' })] })
    serveToken()
    await renderApp('/v/v1/settings/ai-access', [mcp])
    const writesSwitch = await screen.findByRole('switch', { name: 'Let assistants make changes' })
    expect(writesSwitch).toBeDisabled() // needs access to everything
    await userEvent.selectOptions(screen.getByLabelText('Access'), 'author')
    await waitFor(() => {
      expect(writesSwitch).toBeEnabled()
    })
    expect(writes.at(-1)).toMatchObject({
      path: '/modules/mcp',
      body: { settings: { access: 'author' } },
    })
    await userEvent.click(writesSwitch)
    await waitFor(() => {
      expect(writesSwitch).toBeChecked()
    })
    expect(writes.at(-1)).toMatchObject({ body: { settings: { writes: 'on' } } })
    // Back to the readers' view turns writes off with it.
    await userEvent.selectOptions(screen.getByLabelText('Access'), 'readers')
    await waitFor(() => {
      expect(writesSwitch).not.toBeChecked()
    })
    expect(writes.at(-1)).toMatchObject({
      body: { settings: { access: 'readers', writes: 'off' } },
    })
  })

  it('shows, copies and regenerates the token, with client configurations', async () => {
    serveVault({ moduleStates: [state({ access: 'author', writes: 'on' })] })
    const regenerated = serveToken()
    const user = userEvent.setup()
    await renderApp('/v/v1/settings/ai-access', [mcp])
    const token = await screen.findByLabelText('The token')
    expect(token).not.toHaveTextContent('first-token')
    await user.click(screen.getByRole('button', { name: 'Show' }))
    expect(token).toHaveTextContent('first-token')
    await user.click(screen.getByRole('button', { name: 'Copy token' }))
    expect(await navigator.clipboard.readText()).toBe('first-token')
    const code = screen.getByLabelText('Claude Code')
    expect(code).toHaveTextContent('claude mcp add --transport http lore-atlas')
    expect(code).toHaveTextContent('/api/v1/vaults/v1/m/mcp')
    expect(code).toHaveTextContent('Authorization: Bearer first-token')
    const desktop = JSON.parse(screen.getByLabelText('Claude Desktop').textContent) as {
      mcpServers: Record<string, { args: string[]; env: Record<string, string> }>
    }
    expect(desktop.mcpServers['lore-atlas']?.env.LORE_MCP_TOKEN).toBe('first-token')
    await user.click(screen.getByRole('button', { name: 'Copy Claude Desktop' }))
    expect(await navigator.clipboard.readText()).toContain('"mcp-bridge"')

    await user.click(screen.getByRole('button', { name: 'Regenerate' }))
    const dialog = await screen.findByRole('dialog', { name: 'Regenerate the token?' })
    await user.click(within(dialog).getByRole('button', { name: 'Regenerate' }))
    await waitFor(() => {
      expect(token).toHaveTextContent('second-token')
    })
    expect(regenerated).toEqual(['second-token'])
    expect(screen.getByLabelText('Claude Code')).toHaveTextContent('Bearer second-token')
  })

  it('leaves a token set by the environment alone', async () => {
    serveVault({ moduleStates: [state({ access: 'readers', writes: 'off' })] })
    serveToken('environment')
    await renderApp('/v/v1/settings/ai-access', [mcp])
    expect(await screen.findByText(/Set by the server/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Regenerate' })).not.toBeInTheDocument()
  })
})

describe('client configurations', () => {
  it('names the server after the vault', () => {
    expect(serverName('The Sundered Realms!')).toBe('lore-the-sundered-realms')
    expect(serverName('***')).toBe('lore-vault')
    expect(endpointUrl('http://localhost:8000', 'v 1')).toBe(
      'http://localhost:8000/api/v1/vaults/v%201/m/mcp',
    )
  })

  it('builds the Claude Code command and the Claude Desktop configuration', () => {
    expect(claudeCodeCommand('lore-x', 'http://h/m/mcp', 't')).toBe(
      'claude mcp add --transport http lore-x http://h/m/mcp --header "Authorization: Bearer t"',
    )
    expect(JSON.parse(claudeDesktopConfig('lore-x', 'http://h', 'v1', 't'))).toEqual({
      mcpServers: {
        'lore-x': {
          command: 'lore',
          args: ['mcp-bridge', '--vault', 'v1', '--url', 'http://h'],
          env: { LORE_MCP_TOKEN: 't' },
        },
      },
    })
  })
})
