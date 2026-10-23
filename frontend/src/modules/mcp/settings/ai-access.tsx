import { useState } from 'react'
import { toast } from 'sonner'

import { Section, SELECT_CLASS } from '@/components/settings-section'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  useMcpToken,
  useMutations,
  useRegenerateMcpToken,
  useRegistry,
  useSetModule,
  useVault,
} from '@/data'

interface McpSettings {
  access: 'readers' | 'author'
  writes: 'off' | 'on'
}

const DEFAULTS: McpSettings = { access: 'readers', writes: 'off' }

/** The vault's MCP endpoint on this server. */
export function endpointUrl(origin: string, vault: string): string {
  return `${origin}/api/v1/vaults/${encodeURIComponent(vault)}/m/mcp`
}

/** A server name for client configurations: the vault's name, lowercase, dashes for the rest. */
export function serverName(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return `lore-${slug || 'vault'}`
}

/** `claude mcp add` for Claude Code (HTTP, with the token as a header). */
export function claudeCodeCommand(name: string, url: string, token: string): string {
  return `claude mcp add --transport http ${name} ${url} --header "Authorization: Bearer ${token}"`
}

/** Claude Desktop's `claude_desktop_config.json`: the stdio bridge (`lore mcp-bridge`). */
export function claudeDesktopConfig(
  name: string,
  origin: string,
  vault: string,
  token: string,
): string {
  const server = {
    command: 'lore',
    args: ['mcp-bridge', '--vault', vault, '--url', origin],
    env: { LORE_MCP_TOKEN: token },
  }
  return JSON.stringify({ mcpServers: { [name]: server } }, null, 2)
}

async function copy(text: string, what: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(`${what} copied`)
  } catch {
    toast.error('Couldn’t copy to the clipboard')
  }
}

function Snippet({ id, label, text }: { id: string; label: string; text: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <span id={id} className="text-sm font-medium">
          {label}
        </span>
        <Button
          size="sm"
          variant="outline"
          aria-label={`Copy ${label}`}
          onClick={() => {
            void copy(text, label)
          }}
        >
          Copy
        </Button>
      </div>
      <pre
        aria-labelledby={id}
        className="overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs whitespace-pre"
      >
        {text}
      </pre>
    </div>
  )
}

/**
 * Settings → AI access (docs/modules/mcp.md): what assistants may see and do, the server's token,
 * and ready-made client configurations for Claude Code and Claude Desktop.
 */
export function AiAccessSettings({ vault }: { vault: string }) {
  const editable = useMutations() !== null
  const registry = useRegistry(vault)
  const setModule = useSetModule(vault)
  const state = registry.data?.modules.find((module) => module.id === 'mcp')
  const settings = { ...DEFAULTS, ...(state?.settings as Partial<McpSettings> | null) }
  const busy = !editable || setModule.isPending || registry.isPending

  const save = (changes: Partial<McpSettings>, done: string) => {
    setModule.mutate(
      { module: 'mcp', settings: changes },
      {
        onSuccess: () => toast.success(done),
        onError: (error) => toast.error(error.message),
      },
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <Section
        title="AI access"
        description="Assistants that speak the Model Context Protocol (Claude Desktop, Claude Code) can read this vault, and with your permission change it. Everything they get is what the access below allows."
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="mcp-access">Access</Label>
          <select
            id="mcp-access"
            className={SELECT_CLASS}
            disabled={busy}
            value={settings.access}
            onChange={(event) => {
              const access = event.target.value as McpSettings['access']
              // Writes need author access: going back to the readers' view turns them off.
              save(access === 'readers' ? { access, writes: 'off' } : { access }, 'AI access saved')
            }}
          >
            <option value="readers">What readers see (no private content)</option>
            <option value="author">Everything, private content included</option>
          </select>
        </div>
        <div className="flex items-start gap-3">
          <Switch
            id="mcp-writes"
            checked={settings.writes === 'on'}
            disabled={busy || settings.access !== 'author'}
            onCheckedChange={(checked) => {
              save({ writes: checked ? 'on' : 'off' }, checked ? 'Writes on' : 'Writes off')
            }}
            aria-describedby="mcp-writes-description"
          />
          <div className="flex flex-col">
            <label htmlFor="mcp-writes" className="font-medium">
              Let assistants make changes
            </label>
            <p id="mcp-writes-description" className="text-sm text-muted-foreground">
              Create and edit entities, links, facts and events. Every change shows in Recent
              changes as “AI assistant” and can be undone; nothing is deleted.
              {settings.access !== 'author' && ' Needs access to everything.'}
            </p>
          </div>
        </div>
      </Section>
      {editable ? (
        <TokenSection vault={vault} />
      ) : (
        <Section title="Connecting">
          <p className="text-sm text-muted-foreground">
            The token and client configurations are shown to the author on a writable server.
          </p>
        </Section>
      )}
    </div>
  )
}

function TokenSection({ vault }: { vault: string }) {
  const token = useMcpToken(vault)
  const regenerate = useRegenerateMcpToken(vault)
  const name = serverName(useVault(vault).data?.name ?? '')
  const [shown, setShown] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const origin = globalThis.location.origin
  const url = endpointUrl(origin, vault)
  const value = token.data?.token ?? null
  const fromEnvironment = token.data?.source === 'environment'

  return (
    <>
      <Section
        title="Token"
        description="Assistants send it with every request. It opens every vault of this server to them (as each vault’s AI access allows): keep it private."
      >
        {token.isPending && <p className="text-sm text-muted-foreground">Loading…</p>}
        {token.isError && <p className="text-sm text-destructive">The token couldn’t be loaded.</p>}
        {token.isSuccess && value === null && (
          <p className="text-sm text-destructive">
            The server can’t read or create its token (the data directory’s secrets folder).
          </p>
        )}
        {value !== null && (
          <div className="flex flex-wrap items-center gap-2">
            <code
              aria-label="The token"
              className="rounded-md bg-muted px-2 py-1 font-mono text-xs"
            >
              {shown ? value : '•'.repeat(24)}
            </code>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setShown(!shown)
              }}
            >
              {shown ? 'Hide' : 'Show'}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                void copy(value, 'Token')
              }}
            >
              Copy token
            </Button>
            {!fromEnvironment && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setConfirming(true)
                }}
              >
                Regenerate
              </Button>
            )}
          </div>
        )}
        {fromEnvironment && (
          <p className="text-xs text-muted-foreground">
            Set by the server’s <code>LORE_MCP_TOKEN</code>: change it there.
          </p>
        )}
      </Section>
      {value !== null && (
        <Section
          title="Client configurations"
          description={
            <>
              The vault’s endpoint is <code className="break-all">{url}</code>. The configurations
              below hold the token.
            </>
          }
        >
          <Snippet
            id="mcp-claude-code"
            label="Claude Code"
            text={claudeCodeCommand(name, url, value)}
          />
          <Snippet
            id="mcp-claude-desktop"
            label="Claude Desktop"
            text={claudeDesktopConfig(name, origin, vault, value)}
          />
          <p className="text-xs text-muted-foreground">
            Claude Desktop starts <code>lore mcp-bridge</code>, which needs Lore installed on the
            same computer (with Docker: <code>docker exec -i</code> the container, see the AI
            assistants guide).
          </p>
        </Section>
      )}
      {confirming && (
        <Dialog
          open
          onOpenChange={(open) => {
            if (!open) setConfirming(false)
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Regenerate the token?</DialogTitle>
              <DialogDescription>
                Assistants configured with the current token stop working until you give them the
                new one.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setConfirming(false)
                }}
              >
                Cancel
              </Button>
              <Button
                disabled={regenerate.isPending}
                onClick={() => {
                  regenerate.mutate(undefined, {
                    onSuccess: () => {
                      setConfirming(false)
                      toast.success('New token made')
                    },
                    onError: (error) => {
                      setConfirming(false)
                      toast.error(error.message)
                    },
                  })
                }}
              >
                Regenerate
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
