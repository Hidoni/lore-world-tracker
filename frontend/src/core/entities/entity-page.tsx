import { useNavigate } from '@tanstack/react-router'
import { Suspense, useEffect, useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FieldsPanel } from '@/core/fields'
import {
  CausalityPanel,
  CausesSection,
  ChangesCausedSection,
  EventTimeSection,
  eventTime,
  OccurrenceHeader,
  OccurrencesSection,
  ParticipantsSection,
  SubEventsSection,
} from '@/core/events'
import { EntityHistory } from '@/core/history'
import { RelationsPanel } from '@/core/links'
import type { EntityPanel, EntityViewProps } from '@/core/modules'
import { forget, visit } from '@/core/navigation/places'
import { SpoilerGate } from '@/core/reader'
import { useKind, type Kind } from '@/core/registry'
import { isRevisionConflict } from '@/data'
import { LazyRichTextEditor, RichTextView, isDoc, type SaveOutcome } from '@/editor'
import {
  useDeleteEntity,
  useEntity,
  useMutations,
  useReaderMode,
  useRestoreEntity,
  type Entity,
} from '@/data'

import { ExistenceNote, useEntityTime } from './as-of'
import { Lifespan } from './lifespan'
import { EntityHeader } from './entity-header'
import { useEntitySaver, type EntityChange, type SaveResult } from './save'
import { PurgeDialog } from './trash-dialogs'

const EVENT = 'event'
/** Link types the event sections show instead of the relations panel. */
const EVENT_LINK_TYPES = ['core.causes', 'core.participant']

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="flex flex-col gap-2 rounded-md border p-4">
      <h2 className="font-medium">{title}</h2>
      {children}
    </section>
  )
}

const ALWAYS = () => true

/** How far outside the viewport a module panel starts rendering (and reading). */
const NEAR_MARGIN = '200px 0px'

/**
 * After this long on a page, its panels render wherever they are, so keyboard and screen-reader
 * users (who don't scroll) reach them all.
 */
const IDLE_MS = 1500

/**
 * A callback ref and whether its element has come within `NEAR_MARGIN` of the viewport or the page
 * has been open `IDLE_MS` (it stays true once it has). Without `IntersectionObserver` (tests)
 * everything is near.
 */
function useNear(): [(element: HTMLElement | null) => void, boolean] {
  const [element, setElement] = useState<HTMLElement | null>(null)
  const [near, setNear] = useState(() => typeof IntersectionObserver === 'undefined')
  useEffect(() => {
    if (near || element === null) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setNear(true)
      },
      { rootMargin: NEAR_MARGIN },
    )
    observer.observe(element)
    const timer = setTimeout(() => {
      setNear(true)
    }, IDLE_MS)
    return () => {
      observer.disconnect()
      clearTimeout(timer)
    }
  }, [near, element])
  return [setElement, near]
}

/**
 * A module's entity panel in its section, unless its `useShown` hides it on this page. Panels
 * render (and read) once they come near the viewport or the page has been open a moment, so the
 * page is interactive before the panels below the fold have loaded (frontend.md §12). Until then a panel that always shows holds
 * its heading, one with `useShown` an empty block.
 */
function PanelSection({ panel, props }: { panel: EntityPanel; props: EntityViewProps }) {
  const [ref, near] = useNear()
  if (near) return <ShownPanel panel={panel} props={props} />
  return (
    <div ref={ref} className="min-h-16">
      {panel.useShown === undefined && <Section title={panel.title}>{null}</Section>}
    </div>
  )
}

function ShownPanel({ panel, props }: { panel: EntityPanel; props: EntityViewProps }) {
  const shown = (panel.useShown ?? ALWAYS)(props)
  if (!shown) return null
  const Panel = panel.component
  return (
    <Section title={panel.title}>
      <Panel {...props} />
    </Section>
  )
}

function Pending({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>
}

function TrashBanner({ vault, id, name }: { vault: string; id: string; name: string }) {
  const editable = useMutations() !== null
  const restore = useRestoreEntity(vault)
  const purge = useDeleteEntity(vault)
  const navigate = useNavigate()
  const [purging, setPurging] = useState(false)
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm"
    >
      <span className="flex-1">This entity is in the trash.</span>
      {editable && (
        <>
          <Button
            size="sm"
            disabled={restore.isPending}
            onClick={() => {
              restore.mutate(id)
            }}
          >
            Restore
          </Button>
          <Button
            size="sm"
            variant="destructive"
            onClick={() => {
              setPurging(true)
            }}
          >
            Delete permanently
          </Button>
        </>
      )}
      {purging && (
        <PurgeDialog
          name={name}
          busy={purge.isPending}
          onClose={() => {
            setPurging(false)
          }}
          onConfirm={() => {
            purge.mutate(
              { id, purge: true },
              {
                onSuccess: () => {
                  forget(vault, id)
                  void navigate({ to: '/v/$vault', params: { vault }, replace: true })
                },
              },
            )
          }}
        />
      )}
    </div>
  )
}

/** The body (frontend.md §6): the editor for authors, the renderer for readers and the trash. */
function Body({
  vault,
  entity,
  editable,
  save,
}: {
  vault: string
  entity: Entity
  editable: boolean
  save: (change: EntityChange) => Promise<SaveResult>
}) {
  const doc = isDoc(entity.body) ? entity.body : null
  if (!editable) {
    // A comfortable line length for reading.
    return doc ? (
      <div className="max-w-prose text-base leading-relaxed">
        <RichTextView vault={vault} doc={doc} />
      </div>
    ) : (
      <Pending>Nothing written yet.</Pending>
    )
  }
  return (
    <Suspense fallback={<Pending>Loading the editor…</Pending>}>
      <LazyRichTextEditor
        vault={vault}
        initial={doc}
        defaultKind={entity.kind}
        save={async (body): Promise<SaveOutcome> => {
          const result = await save({ body })
          if (result.ok) return 'saved'
          return isRevisionConflict(result.error) ? 'conflict' : 'failed'
        }}
      />
    </Suspense>
  )
}

function EntityView({
  vault,
  entity: data,
  kind,
}: {
  vault: string
  entity: Entity
  kind: Kind | undefined
}) {
  const saver = useEntitySaver(vault, data)
  const time = useEntityTime(vault, data)
  useEffect(() => {
    visit(vault, { id: data.id, name: data.name, kind: data.kind })
  }, [vault, data.id, data.name, data.kind])
  const editable = useMutations() !== null && data.deleted_at === null
  // Readers get no history (it is the author's record of edits).
  const reading = useReaderMode().active
  const main = kind?.panels.filter((panel) => panel.placement === 'main') ?? []
  const side = kind?.panels.filter((panel) => panel.placement === 'side') ?? []
  const media = kind?.headerMedia ?? []
  const props = { vault, entityId: data.id, kind: data.kind }

  return (
    <article className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      {data.deleted_at !== null && <TrashBanner vault={vault} id={data.id} name={data.name} />}
      <div className="flex gap-4">
        {media.map((Media, index) => (
          <Media key={index} {...props} />
        ))}
        <div className="flex-1">
          <EntityHeader vault={vault} entity={data} kind={kind} saver={saver} />
        </div>
      </div>
      <ExistenceNote vault={vault} entity={data} time={time} />
      <Lifespan vault={vault} entity={data} kind={kind} />
      <SpoilerGate spoiler={data.visibility === 'spoiler'} name={data.name}>
        <Tabs defaultValue="overview">
          {!reading && (
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="history">History</TabsTrigger>
            </TabsList>
          )}
          <TabsContent value="overview">
            <div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
              <div className="flex flex-col gap-4">
                {data.summary && <p className="text-muted-foreground">{data.summary}</p>}
                <Section title="Fields">
                  <FieldsPanel
                    key={saver.generation}
                    vault={vault}
                    entity={data}
                    fields={kind?.fields ?? []}
                    editable={editable}
                    save={saver.save}
                    asOf={time.fields}
                  />
                </Section>
                {kind?.capabilities.has_body !== false && (
                  <Section title="Body">
                    <Body
                      key={saver.generation}
                      vault={vault}
                      entity={data}
                      editable={editable}
                      save={saver.save}
                    />
                  </Section>
                )}
                {data.kind === EVENT && (
                  <>
                    <OccurrenceHeader vault={vault} entity={data} />
                    <Section title="Time">
                      <EventTimeSection vault={vault} entity={data} editable={editable} />
                    </Section>
                    {eventTime(data).recurrence !== null && (
                      <Section title="Occurrences">
                        <OccurrencesSection vault={vault} entity={data} editable={editable} />
                      </Section>
                    )}
                    <Section title="Sub-events">
                      <SubEventsSection vault={vault} entity={data} editable={editable} />
                    </Section>
                    <Section title="Causes and effects">
                      <CausesSection vault={vault} entity={data} editable={editable} />
                      <CausalityPanel vault={vault} eventId={data.id} compact />
                    </Section>
                    <Section title="Participants">
                      <ParticipantsSection vault={vault} entity={data} editable={editable} />
                    </Section>
                    <Section title="Changes caused">
                      <ChangesCausedSection vault={vault} eventId={data.id} />
                    </Section>
                  </>
                )}
                <Section title="Relations">
                  <RelationsPanel
                    vault={vault}
                    entity={data}
                    editable={editable}
                    exclude={data.kind === EVENT ? EVENT_LINK_TYPES : []}
                  />
                </Section>
                {main.map((panel) => (
                  <PanelSection key={panel.id} panel={panel} props={props} />
                ))}
              </div>
              {side.length > 0 && (
                <aside aria-label="Entity panels" className="flex flex-col gap-4">
                  {side.map((panel) => (
                    <PanelSection key={panel.id} panel={panel} props={props} />
                  ))}
                </aside>
              )}
            </div>
          </TabsContent>
          {!reading && (
            <TabsContent value="history">
              <EntityHistory vault={vault} entityId={data.id} />
            </TabsContent>
          )}
        </Tabs>
      </SpoilerGate>
      {saver.dialog}
    </article>
  )
}

/**
 * The entity page for any kind (frontend.md §7): the registry decides its icon, label, badges
 * and fields; module panels (`entityPanels`) slot in; events get their time, sub-events, causes and
 * participants sections (#78).
 */
export function EntityPage({ vault, entityId }: { vault: string; entityId: string }) {
  const entity = useEntity(vault, entityId)
  const kind = useKind(entity.data?.kind ?? '', vault)

  if (entity.isPending) return <p className="p-8 text-muted-foreground">Loading…</p>
  if (entity.isError) {
    return (
      <p role="alert" className="p-8 text-destructive">
        Couldn’t load this entity: {entity.error.message}
      </p>
    )
  }
  return <EntityView vault={vault} entity={entity.data} kind={kind} />
}
