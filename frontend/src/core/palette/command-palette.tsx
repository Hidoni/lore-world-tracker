import { useNavigate, useParams, useRouter } from '@tanstack/react-router'
import { Command as Cmdk } from 'cmdk'
import { ClockIcon, SearchIcon, TerminalIcon } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import {
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { CreateEntityDialog, creatableKinds } from '@/core/entities'
import { useExtensionList } from '@/core/modules'
import { usePlaceList } from '@/core/navigation'
import { useKindRegistry } from '@/core/registry'
import { useEntities, useMutations, useQuickSearch } from '@/data'
import { useTheme } from '@/lib/theme'

import { usePalette } from './palette-store'

/** A palette entry: a command, an entity to open, or a page. */
interface Entry {
  id: string
  title: string
  detail?: string
  keywords?: readonly string[]
  icon?: ReactNode
  run: () => void
}

const matches = (entry: Entry, query: string) => {
  const q = query.trim().toLowerCase()
  return (
    q === '' ||
    [entry.title, ...(entry.keywords ?? [])].some((text) => text.toLowerCase().includes(q))
  )
}

/**
 * The command palette (`Ctrl/Cmd+K`, frontend.md §3): with nothing typed, recent entities and
 * every command; typing finds entities by name or alias (`/search/quick`) and filters commands
 * (core: new entity of a kind, go to a dimension, its timeline or a page, toggle the theme,
 * shortcuts; modules add theirs through `commands`). Enter on "Search for …" opens the search
 * page.
 */
export function CommandPalette() {
  const open = usePalette((state) => state.open)
  const setOpen = usePalette((state) => state.setOpen)
  const { vault } = useParams({ strict: false })
  const [creating, setCreating] = useState<string | null>(null)
  return (
    <>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="overflow-hidden p-0" showCloseButton={false}>
          <DialogTitle className="sr-only">Command palette</DialogTitle>
          <DialogDescription className="sr-only">
            Go to an entity or run a command.
          </DialogDescription>
          {open && vault !== undefined && (
            <Palette
              vault={vault}
              close={() => {
                setOpen(false)
              }}
              onCreate={(kind) => {
                setOpen(false)
                setCreating(kind)
              }}
            />
          )}
        </DialogContent>
      </Dialog>
      {creating !== null && vault !== undefined && (
        <CreateEntityDialog
          vault={vault}
          initialKind={creating}
          onClose={() => {
            setCreating(null)
          }}
        />
      )}
    </>
  )
}

function Palette({
  vault,
  close,
  onCreate,
}: {
  vault: string
  close: () => void
  onCreate: (kind: string) => void
}) {
  const [query, setQuery] = useState('')
  const input = useRef<HTMLInputElement>(null)
  // Reopened during the closing animation, the dialog doesn't focus its content again.
  useEffect(() => {
    input.current?.focus()
  }, [])
  const navigate = useNavigate()
  const router = useRouter()
  const registry = useKindRegistry(vault)
  const editable = useMutations() !== null
  const recent = usePlaceList('recent', vault)
  const dimensions = useEntities(vault, { kind: ['dimension'], limit: 100 })
  const quick = useQuickSearch(vault, { q: query.trim() })
  const moduleCommands = useExtensionList('commands', vault)
  const theme = useTheme()
  const q = query.trim()

  const go = (run: () => Promise<void>) => () => {
    close()
    void run()
  }
  const openEntity = (id: string) =>
    go(() => navigate({ to: '/v/$vault/e/$entity', params: { vault, entity: id } }))
  const kindIcon = (kind: string) => {
    const Icon = registry?.kind(kind)?.icon
    return Icon ? <Icon aria-hidden /> : undefined
  }

  const pages: Entry[] = (
    [
      ['/v/$vault', 'Home'],
      ['/v/$vault/search', 'Search'],
      ['/v/$vault/changes', 'Recent changes'],
      ['/v/$vault/trash', 'Trash'],
      ['/v/$vault/consistency', 'Consistency'],
      ['/v/$vault/settings', 'Settings'],
    ] as const
  ).map(([to, title]) => ({
    id: `page:${to}`,
    title: `Go to ${title.toLowerCase()}`,
    keywords: [title],
    run: go(() => navigate({ to, params: { vault } })),
  }))
  const commands: Entry[] = [
    ...(editable
      ? creatableKinds(registry?.kinds ?? []).map((kind) => ({
          id: `new:${kind.key}`,
          title: `New ${kind.label.toLowerCase()}…`,
          keywords: ['create', 'add', kind.plural],
          icon: kindIcon(kind.key),
          run: () => {
            onCreate(kind.key)
          },
        }))
      : []),
    ...(dimensions.data?.items ?? []).flatMap((dimension): Entry[] => [
      {
        id: `dimension:${dimension.id}`,
        title: `Go to ${dimension.name}`,
        detail: 'Dimension',
        keywords: ['dimension'],
        icon: kindIcon('dimension'),
        run: go(() =>
          navigate({ to: '/v/$vault/d/$dimension', params: { vault, dimension: dimension.id } }),
        ),
      },
      {
        id: `timeline:${dimension.id}`,
        title: `Open the timeline of ${dimension.name}`,
        keywords: ['timeline'],
        run: go(() =>
          navigate({
            to: '/v/$vault/d/$dimension/timeline',
            params: { vault, dimension: dimension.id },
          }),
        ),
      },
    ]),
    ...pages,
    {
      id: 'theme',
      title: theme.resolved === 'dark' ? 'Switch to the light theme' : 'Switch to the dark theme',
      keywords: ['theme', 'dark', 'light', 'appearance'],
      run: () => {
        theme.setPreference(theme.resolved === 'dark' ? 'light' : 'dark')
        close()
      },
    },
    {
      id: 'shortcuts',
      title: 'Keyboard shortcuts',
      keywords: ['keys', 'help', 'hotkeys'],
      run: () => {
        close()
        usePalette.getState().setShortcutsOpen(true)
      },
    },
    ...moduleCommands.map((command) => ({
      id: `module:${command.id}`,
      title: command.title,
      keywords: command.keywords ?? [],
      run: () => {
        close()
        void command.run({
          vault,
          navigate: (to) => {
            router.history.push(to)
          },
        })
      },
    })),
  ].filter((entry) => matches(entry, q))

  const hits = q === '' ? [] : (quick.data?.items ?? []).slice(0, 8)
  // The entries in display order: when they change (results arrive), the first is selected, so
  // typing a name and pressing Enter opens it.
  const values = [
    ...(q === '' ? recent.map((place) => `recent:${place.id}`) : []),
    ...hits.map((hit) => `entity:${hit.entity_id}`),
    ...commands.map((entry) => entry.id),
    ...(q === '' ? [] : ['search-everything']),
  ]
  const signature = values.join('|')
  const [shown, setShown] = useState({ signature: '', selected: '' })
  if (shown.signature !== signature) setShown({ signature, selected: values[0] ?? '' })
  return (
    <Cmdk
      shouldFilter={false}
      value={shown.selected}
      onValueChange={(selected) => {
        setShown((current) => ({ ...current, selected }))
      }}
      label="Command palette"
      className="flex h-full w-full flex-col overflow-hidden rounded-md bg-popover text-popover-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground"
    >
      <CommandInput
        ref={input}
        aria-label="Search entities and commands"
        placeholder="Go to an entity, or type a command…"
        value={query}
        onValueChange={setQuery}
      />
      <CommandList className="max-h-[60svh]">
        <CommandEmpty>{quick.isFetching ? 'Searching…' : 'Nothing found.'}</CommandEmpty>
        {q === '' && recent.length > 0 && (
          <CommandGroup heading="Recent">
            {recent.map((place) => (
              <CommandItem
                key={place.id}
                value={`recent:${place.id}`}
                onSelect={openEntity(place.id)}
              >
                {kindIcon(place.kind) ?? <ClockIcon aria-hidden />}
                {place.name}
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        {hits.length > 0 && (
          <CommandGroup heading="Entities">
            {hits.map((hit) => (
              <CommandItem
                key={hit.entity_id}
                value={`entity:${hit.entity_id}`}
                onSelect={openEntity(hit.entity_id)}
              >
                {kindIcon(hit.kind)}
                <span className="truncate">{hit.name}</span>
                <span className="ml-auto truncate text-xs text-muted-foreground">
                  {[hit.alias && `alias ${hit.alias}`, registry?.kind(hit.kind)?.label]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        {commands.length > 0 && (
          <CommandGroup heading="Commands">
            {commands.map((entry) => (
              <CommandItem key={entry.id} value={entry.id} onSelect={entry.run}>
                {entry.icon ?? <TerminalIcon aria-hidden />}
                <span className="truncate">{entry.title}</span>
                {entry.detail && (
                  <span className="ml-auto text-xs text-muted-foreground">{entry.detail}</span>
                )}
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        {q !== '' && (
          <CommandGroup heading="Search">
            <CommandItem
              value="search-everything"
              onSelect={go(() =>
                navigate({ to: '/v/$vault/search', params: { vault }, search: { q } }),
              )}
            >
              <SearchIcon aria-hidden />
              Search everything for “{q}”
            </CommandItem>
          </CommandGroup>
        )}
      </CommandList>
    </Cmdk>
  )
}
