import { Link } from '@tanstack/react-router'
import { useId, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { useTimeContext } from '@/core/time'
import {
  useConsistencyRules,
  useEntity,
  useFindingPages,
  useMutations,
  useScanConsistency,
  useSuppressFinding,
  useTimelines,
  useUnsuppressFinding,
  type components,
} from '@/data'

type Finding = components['schemas']['FindingOut']
type Severity = components['schemas']['ShownSeverity']
/** A timeline of the tree `GET /dimensions/{id}/timelines` returns. */
interface TimelineNode {
  id: string
  name: string
  children: readonly TimelineNode[]
}

/** The panel's filters, kept in the URL (`/v/$vault/consistency?…`). */
export interface FindingsParams {
  /** Comma-separated severities (all when absent). */
  severity?: string
  rule?: string
  owner?: string
  entity?: string
  timeline?: string
  /** `true`: include possible findings ("show uncertain"). */
  uncertain?: boolean
  /** `true`: include suppressed findings. */
  suppressed?: boolean
}

const SEVERITIES: Severity[] = ['error', 'warning', 'info']
const SEVERITY_LABEL: Record<Severity, string> = {
  error: 'Error',
  warning: 'Warning',
  info: 'Info',
}
const SEVERITY_VARIANT: Record<Severity, 'destructive' | 'default' | 'secondary'> = {
  error: 'destructive',
  warning: 'default',
  info: 'secondary',
}
const SELECT_CLASS =
  'h-9 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
const PAGE_SIZE = 50

function isSeverity(value: string): value is Severity {
  return (SEVERITIES as string[]).includes(value)
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <Badge variant={SEVERITY_VARIANT[severity]}>{SEVERITY_LABEL[severity]}</Badge>
}

function flatten(nodes: readonly TimelineNode[]): TimelineNode[] {
  return nodes.flatMap((node) => [node, ...flatten(node.children)])
}

function Subjects({ vault, finding }: { vault: string; finding: Finding }) {
  if (finding.subjects.length === 0) return null
  return (
    <span className="flex flex-wrap gap-x-2">
      {finding.subjects.map((subject) =>
        subject.name === null ? (
          <span key={subject.id} className="text-muted-foreground">
            (deleted)
          </span>
        ) : (
          <Link
            key={subject.id}
            to="/v/$vault/e/$entity"
            params={{ vault, entity: subject.id }}
            className="text-primary underline-offset-2 hover:underline"
          >
            {subject.name}
          </Link>
        ),
      )}
    </span>
  )
}

/** Suppress with a note: the finding stays, hidden unless "show suppressed". */
function SuppressDialog({
  vault,
  finding,
  onClose,
}: {
  vault: string
  finding: Finding
  onClose: () => void
}) {
  const [note, setNote] = useState('')
  const noteId = useId()
  const suppress = useSuppressFinding(vault)
  const trimmed = note.trim()
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Suppress this finding?</DialogTitle>
          <DialogDescription>{finding.message}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={noteId} className="text-sm font-medium">
            Why is this intentional?
          </label>
          <Textarea
            id={noteId}
            value={note}
            maxLength={2000}
            onChange={(event) => {
              setNote(event.target.value)
            }}
          />
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={trimmed === '' || suppress.isPending}
            onClick={() => {
              suppress.mutate(
                { fingerprint: finding.fingerprint, note: trimmed },
                { onSuccess: onClose },
              )
            }}
          >
            Suppress
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** "Explain": the rule's description, the finding's subjects and its suppression note. */
function ExplainSheet({
  vault,
  finding,
  description,
  onClose,
}: {
  vault: string
  finding: Finding
  description: string | undefined
  onClose: () => void
}) {
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <SheetContent side="right" className="w-96 max-w-full">
        <SheetHeader>
          <SheetTitle>{finding.title}</SheetTitle>
          <SheetDescription>{finding.message}</SheetDescription>
        </SheetHeader>
        <dl className="flex flex-col gap-3 px-4 text-sm">
          <div>
            <dt className="font-medium">About the rule</dt>
            <dd className="text-muted-foreground">{description ?? 'No description.'}</dd>
          </div>
          <div>
            <dt className="font-medium">Rule</dt>
            <dd>
              <code className="text-xs">{finding.rule_id}</code> ({finding.owner})
            </dd>
          </div>
          <div>
            <dt className="font-medium">Certainty</dt>
            <dd>
              {finding.certainty === 'definite'
                ? 'Definite'
                : 'Possible: it depends on imprecise dates'}
            </dd>
          </div>
          <div>
            <dt className="font-medium">Subjects</dt>
            <dd>
              <Subjects vault={vault} finding={finding} />
            </dd>
          </div>
          {finding.suppression !== null && (
            <div>
              <dt className="font-medium">Suppressed</dt>
              <dd>{finding.suppression.note}</dd>
            </div>
          )}
        </dl>
      </SheetContent>
    </Sheet>
  )
}

function FindingRow({
  vault,
  finding,
  description,
  suppressible,
}: {
  vault: string
  finding: Finding
  description: string | undefined
  suppressible: boolean
}) {
  const [open, setOpen] = useState<'explain' | 'suppress' | null>(null)
  const unsuppress = useUnsuppressFinding(vault)
  const editable = useMutations() !== null
  const close = () => {
    setOpen(null)
  }
  return (
    <li className="flex flex-col gap-1 py-3" aria-label={finding.message}>
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={finding.severity} />
        {finding.certainty === 'possible' && <Badge variant="outline">Possible</Badge>}
        {finding.suppression !== null && <Badge variant="outline">Suppressed</Badge>}
        <span className="text-sm font-medium">{finding.title}</span>
      </div>
      <p className="text-sm">{finding.message}</p>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Subjects vault={vault} finding={finding} />
        <div className="flex-1" />
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setOpen('explain')
          }}
        >
          Explain
        </Button>
        {editable && finding.suppression === null && suppressible && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setOpen('suppress')
            }}
          >
            Suppress…
          </Button>
        )}
        {editable && finding.suppression !== null && (
          <Button
            variant="ghost"
            size="sm"
            disabled={unsuppress.isPending}
            onClick={() => {
              unsuppress.mutate(finding.fingerprint)
            }}
          >
            Unsuppress
          </Button>
        )}
      </div>
      {open === 'explain' && (
        <ExplainSheet vault={vault} finding={finding} description={description} onClose={close} />
      )}
      {open === 'suppress' && <SuppressDialog vault={vault} finding={finding} onClose={close} />}
    </li>
  )
}

function EntityFilter({ vault, id, onClear }: { vault: string; id: string; onClear: () => void }) {
  const entity = useEntity(vault, id)
  return (
    <span className="flex items-center gap-1 text-sm">
      About <strong>{entity.data?.name ?? '…'}</strong>
      <Button variant="ghost" size="sm" onClick={onClear}>
        Show all
      </Button>
    </span>
  )
}

/**
 * The findings panel (`/v/$vault/consistency`, consistency.md §5): open findings, filtered by
 * severity, certainty, rule, owner, entity and timeline (filters in the URL), with "explain",
 * suppress with a note, and a re-scan. Rules don't offer quick fixes yet.
 */
export function FindingsPage({
  vault,
  params,
  onChange,
}: {
  vault: string
  params: FindingsParams
  onChange: (next: FindingsParams) => void
}) {
  const rules = useConsistencyRules(vault)
  const time = useTimeContext(vault)
  const timelines = useTimelines(vault, time.dimensionId)
  const scan = useScanConsistency(vault)
  const editable = useMutations() !== null
  const severities = (params.severity?.split(',') ?? []).filter(isSeverity)
  const query = {
    status: params.suppressed === true ? ('all' as const) : ('open' as const),
    ...(severities.length > 0 ? { severity: severities } : {}),
    ...(params.uncertain === true ? {} : { certainty: 'definite' as const }),
    ...(params.rule === undefined ? {} : { rule: [params.rule] }),
    ...(params.owner === undefined ? {} : { owner: params.owner }),
    ...(params.entity === undefined ? {} : { entity: params.entity }),
    ...(params.timeline === undefined ? {} : { timeline: params.timeline }),
    limit: PAGE_SIZE,
  }
  const pages = useFindingPages(vault, query)
  const findings = pages.data?.pages.flatMap((page) => page.items) ?? []
  const ruleList = rules.data?.items ?? []
  const owners = [...new Set(ruleList.map((rule) => rule.owner))].sort()
  /** Changes filters; empty ones (`''`, `false`, `undefined`) are dropped. */
  const set = (patch: Record<string, string | boolean | undefined>) => {
    const merged: Record<string, string | boolean | undefined> = { ...params, ...patch }
    const kept = Object.entries(merged).filter(
      ([, value]) => value !== undefined && value !== '' && value !== false,
    )
    onChange(Object.fromEntries(kept))
  }
  const toggleSeverity = (severity: Severity, on: boolean) => {
    // No filter means every severity.
    const shown = severities.length === 0 ? SEVERITIES : severities
    const next = SEVERITIES.filter((s) => (s === severity ? on : shown.includes(s)))
    set({
      severity: next.length === 0 || next.length === SEVERITIES.length ? undefined : next.join(','),
    })
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4 p-6">
      <div className="flex items-center gap-2">
        <h1 className="text-2xl font-semibold">Consistency</h1>
        <div className="flex-1" />
        {editable && (
          <Button
            variant="outline"
            size="sm"
            disabled={scan.isPending}
            onClick={() => {
              scan.mutate()
            }}
          >
            {scan.isPending ? 'Checking…' : 'Check the whole vault'}
          </Button>
        )}
      </div>
      <fieldset className="flex flex-wrap items-center gap-x-4 gap-y-2" aria-label="Filters">
        <legend className="sr-only">Filters</legend>
        {SEVERITIES.map((severity) => (
          <label key={severity} className="flex items-center gap-1.5 text-sm">
            <input
              type="checkbox"
              checked={severities.length === 0 || severities.includes(severity)}
              onChange={(event) => {
                toggleSeverity(severity, event.target.checked)
              }}
            />
            {SEVERITY_LABEL[severity]}
          </label>
        ))}
        <select
          aria-label="Rule"
          className={SELECT_CLASS}
          value={params.rule ?? ''}
          onChange={(event) => {
            set({ rule: event.target.value })
          }}
        >
          <option value="">Every rule</option>
          {ruleList.map((rule) => (
            <option key={rule.id} value={rule.id}>
              {rule.title}
            </option>
          ))}
        </select>
        <select
          aria-label="Owner"
          className={SELECT_CLASS}
          value={params.owner ?? ''}
          onChange={(event) => {
            set({ owner: event.target.value })
          }}
        >
          <option value="">Every owner</option>
          {owners.map((owner) => (
            <option key={owner} value={owner}>
              {owner}
            </option>
          ))}
        </select>
        {(timelines.data?.items.length ?? 0) > 0 && (
          <select
            aria-label="Timeline"
            className={SELECT_CLASS}
            value={params.timeline ?? ''}
            onChange={(event) => {
              set({ timeline: event.target.value })
            }}
          >
            <option value="">Every timeline</option>
            {flatten(timelines.data?.items ?? []).map((timeline) => (
              <option key={timeline.id} value={timeline.id}>
                {timeline.name}
              </option>
            ))}
          </select>
        )}
        <label className="flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            checked={params.uncertain === true}
            onChange={(event) => {
              set({ uncertain: event.target.checked })
            }}
          />
          Show uncertain
        </label>
        <label className="flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            checked={params.suppressed === true}
            onChange={(event) => {
              set({ suppressed: event.target.checked })
            }}
          />
          Show suppressed
        </label>
        {params.entity !== undefined && (
          <EntityFilter
            vault={vault}
            id={params.entity}
            onClear={() => {
              set({ entity: undefined })
            }}
          />
        )}
      </fieldset>
      {pages.isPending ? (
        <p className="text-sm text-muted-foreground">Loading findings…</p>
      ) : findings.length === 0 ? (
        <p className="text-sm text-muted-foreground">No findings. Everything is consistent.</p>
      ) : (
        <ul aria-label="Findings" className="divide-y">
          {findings.map((finding) => {
            const rule = ruleList.find((candidate) => candidate.id === finding.rule_id)
            return (
              <FindingRow
                key={finding.fingerprint}
                vault={vault}
                finding={finding}
                description={rule?.description}
                suppressible={rule?.configurable ?? true}
              />
            )
          })}
        </ul>
      )}
      {pages.hasNextPage && (
        <Button
          variant="outline"
          className="self-start"
          disabled={pages.isFetchingNextPage}
          onClick={() => {
            void pages.fetchNextPage()
          }}
        >
          Show more findings
        </Button>
      )}
    </div>
  )
}
