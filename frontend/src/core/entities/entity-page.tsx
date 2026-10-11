import { useNavigate } from '@tanstack/react-router'
import { useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useKind } from '@/core/registry'
import { useDeleteEntity, useEntity, useMutations, useRestoreEntity } from '@/data'

import { EntityHeader } from './entity-header'
import { PurgeDialog } from './trash-dialogs'

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

/**
 * The entity page for any kind (frontend.md §7): the registry decides its icon, label and
 * badges; module panels (`entityPanels`) slot in. Fields, body, relations, time and history fill
 * their sections with #62, #63, #66, M5 and #68.
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
  const data = entity.data
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
          <EntityHeader vault={vault} entity={data} kind={kind} />
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
                <Pending>
                  {kind === undefined || kind.fields.length === 0
                    ? 'This kind has no fields.'
                    : `${kind.fields.length} field${kind.fields.length === 1 ? '' : 's'}: editors arrive with #62.`}
                </Pending>
              </Section>
              {kind?.capabilities.has_body !== false && (
                <Section title="Body">
                  <Pending>The rich-text body arrives with #63.</Pending>
                </Section>
              )}
              <Section title="Relations">
                <Pending>Links and backlinks arrive with #66.</Pending>
              </Section>
              {kind?.capabilities.is_time_bound === true && (
                <Section title="Time">
                  <Pending>Dates in every calendar arrive with M5.</Pending>
                </Section>
              )}
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
          <Pending>The entity’s history arrives with #68.</Pending>
        </TabsContent>
      </Tabs>
    </article>
  )
}
