import { useNavigate } from '@tanstack/react-router'
import { Suspense, useEffect, useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FieldsPanel } from '@/core/fields'
import {
  CausalityPanel,
  CausesSection,
  EventTimeSection,
  eventTime,
  OccurrenceHeader,
  OccurrencesSection,
  ParticipantsSection,
  SubEventsSection,
} from '@/core/events'
import { EntityHistory } from '@/core/history'
import { RelationsPanel } from '@/core/links'
import { forget, visit } from '@/core/navigation/places'
import { useKind, type Kind } from '@/core/registry'
import { isRevisionConflict } from '@/data'
import { LazyRichTextEditor, RichTextView, isDoc, type SaveOutcome } from '@/editor'
import { useDeleteEntity, useEntity, useMutations, useRestoreEntity, type Entity } from '@/data'

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
    return doc ? <RichTextView vault={vault} doc={doc} /> : <Pending>Nothing written yet.</Pending>
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
  useEffect(() => {
    visit(vault, { id: data.id, name: data.name, kind: data.kind })
  }, [vault, data.id, data.name, data.kind])
  const editable = useMutations() !== null && data.deleted_at === null
  const main = kind?.panels.filter((panel) => panel.placement === 'main') ?? []
  const side = kind?.panels.filter((panel) => panel.placement === 'side') ?? []
  const Media = kind?.headerMedia ?? null
  const props = { vault, entityId: data.id, kind: data.kind }

  return (
    <article className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      {data.deleted_at !== null && <TrashBanner vault={vault} id={data.id} name={data.name} />}
      <div className="flex gap-4">
        {Media !== null && <Media {...props} />}
        <div className="flex-1">
          <EntityHeader vault={vault} entity={data} kind={kind} saver={saver} />
        </div>
      </div>
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>
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
              {main.map(({ id, title, component: Panel }) => (
                <Section key={id} title={title}>
                  <Panel {...props} />
                </Section>
              ))}
            </div>
            {side.length > 0 && (
              <aside aria-label="Entity panels" className="flex flex-col gap-4">
                {side.map(({ id, title, component: Panel }) => (
                  <Section key={id} title={title}>
                    <Panel {...props} />
                  </Section>
                ))}
              </aside>
            )}
          </div>
        </TabsContent>
        <TabsContent value="history">
          <EntityHistory vault={vault} entityId={data.id} />
        </TabsContent>
      </Tabs>
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
