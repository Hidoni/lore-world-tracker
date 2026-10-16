import { Link } from '@tanstack/react-router'
import { GitBranchIcon, PencilIcon, PlusIcon, Undo2Icon, XIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useKindRegistry } from '@/core/registry'
import {
  POSSIBLE_NOTE,
  recordPlace,
  RecordBranchBadge,
  useBranching,
  useEntityAsOf,
  type RecordPlace,
} from '@/core/time'
import { useDeleteLink, useLinks, useRevertOverride, type EntityLink } from '@/data'
import { Spoiler } from '@/core/reader'
import { cn } from '@/lib/utils'

import { LinkDialog, type LinkDialogMode } from './link-dialog'
import { OverrideLinkDialog } from './override-link-dialog'

interface Group {
  key: string
  label: string
  items: EntityLink[]
}

/** Links grouped by type and direction, labelled from the entity's side, in the server's order. */
export function groupLinks(items: readonly EntityLink[]): Group[] {
  const groups = new Map<string, Group>()
  for (const item of items) {
    const key = `${item.link.link_type}:${item.direction}`
    let group = groups.get(key)
    if (group === undefined) {
      group = { key, label: item.label, items: [] }
      groups.set(key, group)
    }
    group.items.push(item)
  }
  return [...groups.values()]
}

/** `data` as short text when no module renders it: `rank: Captain · sworn: yes`. */
function dataSummary(data: Readonly<Record<string, unknown>>): string {
  return Object.entries(data)
    .filter(([, value]) => value !== null && value !== '')
    .map(([key, value]) => {
      const text =
        typeof value === 'boolean'
          ? value
            ? 'yes'
            : 'no'
          : typeof value === 'string'
            ? value
            : JSON.stringify(value)
      return `${key}: ${text}`
    })
    .join(' · ')
}

/**
 * The relations panel (frontend.md §7): the entity's links grouped by type with forward/inverse
 * labels (symmetric links once), roles, data (a module's `linkTypeRenderers` or a summary) and
 * visibility, with add, edit and remove for authors. In a branch, inherited links are badged: the
 * shared past is read-only and links still valid at the branch point are edited in this timeline
 * (an override, which Revert removes; the overridden link itself is left out).
 */
export function RelationsPanel({
  vault,
  entity,
  editable,
  exclude = [],
}: {
  vault: string
  entity: { id: string; name: string; kind: string }
  editable: boolean
  /** Link types another section of the page shows (an event's causes and participants). */
  exclude?: readonly string[]
}) {
  const asOf = useEntityAsOf(vault, entity.id)
  const links = useLinks(vault, entity.id, asOf ?? {})
  const registry = useKindRegistry(vault)
  const remove = useDeleteLink(vault)
  const revert = useRevertOverride(vault)
  const branching = useBranching(vault)
  const branch = branching.inBranch ? branching.timelineId : null
  const [dialog, setDialog] = useState<LinkDialogMode | null>(null)
  const [overriding, setOverriding] = useState<EntityLink | null>(null)
  const items = (links.data?.items ?? []).filter((item) => !exclude.includes(item.link.link_type))
  // Without a time cursor every timeline's links come back: the branch's version of a link
  // replaces it (and other lineages' overrides don't show).
  const overridden = new Set(
    items
      .filter((item) => item.link.timeline_id === branch && item.link.overrides_id != null)
      .map((item) => item.link.overrides_id),
  )
  const groups = groupLinks(
    branch === null
      ? items
      : items.filter(
          (item) =>
            !overridden.has(item.link.id) &&
            (item.link.overrides_id == null ||
              branching.lineage.some((entry) => entry.timeline.id === item.link.timeline_id)),
        ),
  )
  const placeOf = (item: EntityLink): RecordPlace | null =>
    branch === null || item.link.timeline_id === null
      ? null
      : recordPlace(branching.lineage, {
          timelineId: item.link.timeline_id,
          start: item.link.valid_from_t,
          end: item.link.valid_to_t,
          overridesId: item.link.overrides_id ?? null,
        })

  return (
    <div className="flex flex-col gap-3">
      {links.isPending && <p className="text-sm text-muted-foreground">Loading…</p>}
      {!links.isPending && groups.length === 0 && (
        <p className="text-sm text-muted-foreground">No links yet.</p>
      )}
      {groups.map((group) => (
        <section key={group.key} aria-label={group.label} className="flex flex-col gap-1">
          <h3 className="text-xs font-medium text-muted-foreground uppercase">{group.label}</h3>
          <ul className="flex flex-col">
            {group.items.map((item) => {
              const { link, other, label, certainty } = item
              const place = placeOf(item)
              const kind = registry?.kind(other.kind)
              const Icon = kind?.icon
              const Renderer = registry?.linkType(link.link_type)?.renderer ?? null
              const summary = dataSummary(link.data)
              return (
                <li
                  key={link.id}
                  className={cn(
                    'group flex flex-wrap items-center gap-2 rounded-md px-1 py-1 text-sm hover:bg-accent/50',
                    certainty === 'possible' && 'text-muted-foreground italic',
                  )}
                  title={certainty === 'possible' ? POSSIBLE_NOTE : undefined}
                  data-certainty={certainty ?? undefined}
                >
                  {Icon && (
                    <Icon aria-hidden className="size-4 shrink-0" style={{ color: kind.color }} />
                  )}
                  <Spoiler spoiler={link.visibility === 'spoiler'} label={label}>
                    <Link
                      to="/v/$vault/e/$entity"
                      params={{ vault, entity: other.id }}
                      className="font-medium hover:underline"
                    >
                      {other.name}
                    </Link>
                    {link.role && <span className="text-muted-foreground">as {link.role}</span>}
                    {Renderer ? (
                      <Renderer
                        vault={vault}
                        linkId={link.id}
                        linkType={link.link_type}
                        role={link.role}
                        data={link.data}
                      />
                    ) : (
                      summary !== '' && (
                        <span className="text-xs text-muted-foreground">{summary}</span>
                      )
                    )}
                  </Spoiler>
                  <RecordBranchBadge place={place} branchName={branching.name(branch)} />
                  {link.visibility !== 'public' && (
                    <Badge variant="secondary">
                      {link.visibility === 'spoiler' ? 'Spoiler' : 'Private'}
                    </Badge>
                  )}
                  {editable && (place === null || place.kind === 'own') && (
                    <span className="ml-auto flex gap-0.5 opacity-60 group-focus-within:opacity-100 group-hover:opacity-100">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-7"
                        aria-label={`Edit link to ${other.name}`}
                        onClick={() => {
                          setDialog({ mode: 'edit', link, label, other })
                        }}
                      >
                        <PencilIcon className="size-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-7"
                        aria-label={`Remove link to ${other.name}`}
                        disabled={remove.isPending}
                        onClick={() => {
                          remove.mutate(link.id, {
                            onSuccess: () => {
                              toast(`Removed the link to ${other.name}`)
                            },
                          })
                        }}
                      >
                        <XIcon className="size-3.5" />
                      </Button>
                    </span>
                  )}
                  {editable &&
                    place !== null &&
                    (place.kind === 'spanning' || place.kind === 'override') && (
                      <span className="ml-auto flex gap-0.5">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7"
                          aria-label={`Edit the link to ${other.name} in this timeline`}
                          onClick={() => {
                            setOverriding(item)
                          }}
                        >
                          <GitBranchIcon className="size-3.5" aria-hidden /> Edit in this timeline
                        </Button>
                        {place.kind === 'override' && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-7"
                            aria-label={`Revert the link to ${other.name}`}
                            disabled={revert.isPending}
                            onClick={() => {
                              revert.mutate({ recordType: 'link', id: link.id })
                            }}
                          >
                            <Undo2Icon className="size-3.5" />
                          </Button>
                        )}
                      </span>
                    )}
                </li>
              )
            })}
          </ul>
        </section>
      ))}
      {editable && (
        <Button
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => {
            setDialog({ mode: 'add' })
          }}
        >
          <PlusIcon /> Add link
        </Button>
      )}
      {overriding !== null && branch !== null && (
        <OverrideLinkDialog
          vault={vault}
          item={overriding}
          timelineId={branch}
          branchName={branching.name(branch)}
          onClose={() => {
            setOverriding(null)
          }}
        />
      )}
      {dialog && (
        <LinkDialog
          vault={vault}
          entity={entity}
          onClose={() => {
            setDialog(null)
          }}
          {...dialog}
        />
      )}
    </div>
  )
}
