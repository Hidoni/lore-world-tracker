import {
  api as defaultClient,
  CLIENT_HEADER,
  toApiError,
  unwrap,
  type ApiClient,
  type components,
} from '@/api'

import { entityToDomain, toDomain, toWire, type Domain } from './domain'
import type { DataSource, EntityWriteResult, Mutations } from './source'

type Schemas = components['schemas']

const V = '/api/v1/vaults/{vault_id}' as const

function withEntity(result: Schemas['EntityWriteResult']): EntityWriteResult {
  return { ...result, entity: entityToDomain(toDomain(result.entity, 'EntityOut')) }
}

/**
 * A multipart POST with upload progress (`fetch` has none): XHR, same origin, the SPA's client
 * header; failures become `ApiError`s like every other request.
 */
function uploadWithProgress<T>(
  path: string,
  form: FormData,
  onProgress: (fraction: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', path)
    xhr.setRequestHeader(CLIENT_HEADER, 'web')
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total)
    }
    xhr.onerror = () => {
      reject(new Error('The upload failed: the server could not be reached.'))
    }
    xhr.onload = () => {
      const response = new Response(xhr.responseText, {
        status: xhr.status,
        headers: { 'Content-Type': xhr.getResponseHeader('Content-Type') ?? 'application/json' },
      })
      if (!response.ok) {
        void toApiError(response).then(reject)
        return
      }
      onProgress(1)
      response.json().then((body) => {
        resolve(body as T)
      }, reject)
    }
    xhr.send(form)
  })
}

/** The `DataSource` over the backend's HTTP API (the generated `openapi-fetch` client). */
export function createHttpDataSource(client: ApiClient = defaultClient): DataSource {
  const path = (vault_id: string) => ({ path: { vault_id } })
  return {
    meta: () => unwrap(client.GET('/api/v1/meta')),
    vaults: () => unwrap(client.GET('/api/v1/vaults')),
    vault: (vault) => unwrap(client.GET(V, { params: path(vault) })),
    settings: (vault) => unwrap(client.GET(`${V}/settings`, { params: path(vault) })),
    registry: (vault) => unwrap(client.GET(`${V}/registry`, { params: path(vault) })),
    backups: (vault) => unwrap(client.GET(`${V}/backups`, { params: path(vault) })),
    entities: async (vault, query) =>
      toDomain(
        await unwrap(client.GET(`${V}/entities`, { params: { ...path(vault), query } })),
        'EntityPage',
      ),
    entity: async (vault, id, query) =>
      entityToDomain(
        toDomain(
          await unwrap(
            client.GET(`${V}/entities/{entity_id}`, {
              params: { path: { vault_id: vault, entity_id: id }, query },
            }),
          ),
          'EntityOut',
        ),
      ),
    children: async (vault, id, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/entities/{entity_id}/children`, {
            params: { path: { vault_id: vault, entity_id: id }, query },
          }),
        ),
        'TreePage',
      ),
    tree: async (vault, query) =>
      toDomain(
        await unwrap(client.GET(`${V}/tree`, { params: { ...path(vault), query } })),
        'TreePage',
      ),
    trash: async (vault, query) =>
      toDomain(
        await unwrap(client.GET(`${V}/trash`, { params: { ...path(vault), query } })),
        'TrashPage',
      ),
    tags: async (vault, query) =>
      toDomain(
        await unwrap(client.GET(`${V}/tags`, { params: { ...path(vault), query } })),
        'TagList',
      ),
    fieldValues: async (vault, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/entities/field-values`, { params: { ...path(vault), query } }),
        ),
        'FieldValueList',
      ),
    links: async (vault, id, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/entities/{entity_id}/links`, {
            params: { path: { vault_id: vault, entity_id: id }, query },
          }),
        ),
        'EntityLinks',
      ),
    backlinks: async (vault, id, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/entities/{entity_id}/backlinks`, {
            params: { path: { vault_id: vault, entity_id: id }, query },
          }),
        ),
        'Backlinks',
      ),
    linkTypes: async (vault) =>
      toDomain(
        await unwrap(client.GET(`${V}/link-types`, { params: path(vault) })),
        'LinkTypeList',
      ),
    changes: async (vault, query) =>
      toDomain(
        await unwrap(client.GET(`${V}/changes`, { params: { ...path(vault), query } })),
        'ChangesetPage',
      ),
    change: async (vault, id, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/changes/{changeset_id}`, {
            params: { path: { vault_id: vault, changeset_id: id }, query },
          }),
        ),
        'ChangesetDetail',
      ),
    history: async (vault, id, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/entities/{entity_id}/history`, {
            params: { path: { vault_id: vault, entity_id: id }, query },
          }),
        ),
        'ChangesetPage',
      ),
    search: async (vault, query) =>
      toDomain(
        await unwrap(client.GET(`${V}/search`, { params: { ...path(vault), query } })),
        'SearchPage',
      ),
    quickSearch: async (vault, query) =>
      toDomain(
        await unwrap(client.GET(`${V}/search/quick`, { params: { ...path(vault), query } })),
        'QuickResults',
      ),
    findings: async (vault, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/consistency/findings`, { params: { ...path(vault), query } }),
        ),
        'FindingPage',
      ),
    consistencyRules: async (vault, query) =>
      toDomain(
        await unwrap(client.GET(`${V}/consistency/rules`, { params: { ...path(vault), query } })),
        'RuleList',
      ),
    timelines: async (vault, dimension, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/dimensions/{dimension_id}/timelines`, {
            params: { path: { vault_id: vault, dimension_id: dimension }, query },
          }),
        ),
        'TimelineTree',
      ),
    calendarPresets: async (vault) =>
      toDomain(
        await unwrap(client.GET(`${V}/calendars/presets`, { params: path(vault) })),
        'PresetList',
      ),
    eventTree: async (vault, timeline, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/timelines/{timeline_id}/event-tree`, {
            params: { path: { vault_id: vault, timeline_id: timeline }, query },
          }),
        ),
        'EventTreePage',
      ),
    causality: async (vault, timeline, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/timelines/{timeline_id}/causality`, {
            params: { path: { vault_id: vault, timeline_id: timeline }, query },
          }),
        ),
        'CausalityGraphOut',
      ),
    locationTree: async (vault, query) =>
      toDomain(
        await unwrap(client.GET(`${V}/m/locations/tree`, { params: { ...path(vault), query } })),
        'LocationTree',
      ),
    locationEvents: async (vault, location, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/locations/{location_id}/events`, {
            params: { path: { vault_id: vault, location_id: location }, query },
          }),
        ),
        'LocationEvents',
      ),
    locationResidents: async (vault, location) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/locations/{location_id}/residents`, {
            params: { path: { vault_id: vault, location_id: location } },
          }),
        ),
        'EntityLinks',
      ),
    characterRelationships: async (vault, character) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/characters/{character_id}/relationships`, {
            params: { path: { vault_id: vault, character_id: character } },
          }),
        ),
        'Relationships',
      ),
    characterLife: async (vault, character, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/characters/{character_id}/life`, {
            params: { path: { vault_id: vault, character_id: character }, query },
          }),
        ),
        'Life',
      ),
    groupMembers: async (vault, group, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/groups/{group_id}/members`, {
            params: { path: { vault_id: vault, group_id: group }, query },
          }),
        ),
        'Members',
      ),
    groupLeaders: async (vault, group) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/groups/{group_id}/leaders`, {
            params: { path: { vault_id: vault, group_id: group } },
          }),
        ),
        'Leaders',
      ),
    groupTerritory: async (vault, group) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/groups/{group_id}/territory`, {
            params: { path: { vault_id: vault, group_id: group } },
          }),
        ),
        'EntityLinks',
      ),
    languageFamilyTree: async (vault, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/languages/family-tree`, { params: { ...path(vault), query } }),
        ),
        'FamilyTree',
      ),
    timelineWindow: async (vault, timeline, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/timelines/{timeline_id}/window`, {
            params: { path: { vault_id: vault, timeline_id: timeline }, query },
          }),
        ),
        'TimelineWindow',
      ),
    occurrences: async (vault, event, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/events/{event_id}/occurrences`, {
            params: { path: { vault_id: vault, event_id: event }, query },
          }),
        ),
        'OccurrencePage',
      ),
  }
}

/** The `Mutations` over the backend's HTTP API. */
export function createHttpMutations(client: ApiClient = defaultClient): Mutations {
  const path = (vault_id: string) => ({ path: { vault_id } })
  const entityPath = (vault_id: string, entity_id: string) => ({ path: { vault_id, entity_id } })
  return {
    createVault: (name) => unwrap(client.POST('/api/v1/vaults', { body: { name } })),
    renameVault: (vault, name) => unwrap(client.PATCH(V, { params: path(vault), body: { name } })),
    deleteVault: async (vault) => {
      await client.DELETE(V, { params: path(vault) })
    },
    migrateVault: (vault) => unwrap(client.POST(`${V}/migrate`, { params: path(vault) })),
    restoreBackup: (file, onProgress) => {
      const form = new FormData()
      form.append('file', file)
      if (onProgress) return uploadWithProgress('/api/v1/vaults/restore', form, onProgress)
      return unwrap(
        client.POST('/api/v1/vaults/restore', {
          body: form as unknown as { file: string },
          bodySerializer: (body: unknown) => body as FormData,
        }),
      )
    },
    createBackup: (vault, body) =>
      unwrap(client.POST(`${V}/backups`, { params: path(vault), body })),
    updateSettings: (vault, body) =>
      unwrap(client.PATCH(`${V}/settings`, { params: path(vault), body })),
    setModule: (vault, module, body) =>
      unwrap(
        client.PATCH(`${V}/modules/{module_id}`, {
          params: { path: { vault_id: vault, module_id: module } },
          body,
        }),
      ),
    createEntity: async (vault, body) =>
      withEntity(await unwrap(client.POST(`${V}/entities`, { params: path(vault), body }))),
    updateEntity: async (vault, id, body) =>
      withEntity(
        await unwrap(
          client.PATCH(`${V}/entities/{entity_id}`, { params: entityPath(vault, id), body }),
        ),
      ),
    deleteEntity: async (vault, id, options = {}) =>
      toDomain(
        await unwrap(
          client.DELETE(`${V}/entities/{entity_id}`, {
            params: { ...entityPath(vault, id), query: { purge: options.purge } },
            body: options.suppress ?? null,
          }),
        ),
        'EntityDeleteResult',
      ),
    restoreEntity: async (vault, id, suppress) =>
      withEntity(
        await unwrap(
          client.POST(`${V}/entities/{entity_id}/restore`, {
            params: entityPath(vault, id),
            body: suppress ?? null,
          }),
        ),
      ),
    createLink: async (vault, body) =>
      toDomain(
        await unwrap(client.POST(`${V}/links`, { params: path(vault), body })),
        'LinkWriteResult',
      ),
    updateLink: async (vault, id, body) =>
      toDomain(
        await unwrap(
          client.PATCH(`${V}/links/{link_id}`, {
            params: { path: { vault_id: vault, link_id: id } },
            body,
          }),
        ),
        'LinkWriteResult',
      ),
    deleteLink: async (vault, id, suppress) =>
      toDomain(
        await unwrap(
          client.DELETE(`${V}/links/{link_id}`, {
            params: { path: { vault_id: vault, link_id: id } },
            body: suppress ?? null,
          }),
        ),
        'LinkDeleteResult',
      ),
    createLinkType: async (vault, body) =>
      toDomain(
        await unwrap(client.POST(`${V}/link-types`, { params: path(vault), body })),
        'LinkTypeOut',
      ),
    updateLinkType: async (vault, key, body) =>
      toDomain(
        await unwrap(
          client.PATCH(`${V}/link-types/{key}`, {
            params: { path: { vault_id: vault, key } },
            body,
          }),
        ),
        'LinkTypeOut',
      ),
    deleteLinkType: async (vault, key) =>
      toDomain(
        await unwrap(
          client.DELETE(`${V}/link-types/{key}`, { params: { path: { vault_id: vault, key } } }),
        ),
        'LinkTypeDeleted',
      ),
    revertChange: async (vault, id, suppress) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/changes/{changeset_id}/revert`, {
            params: { path: { vault_id: vault, changeset_id: id } },
            body: suppress ?? null,
          }),
        ),
        'RevertResult',
      ),
    scanConsistency: async (vault) =>
      toDomain(
        await unwrap(client.POST(`${V}/consistency/scan`, { params: path(vault) })),
        'ScanResult',
      ),
    updateConsistencyRule: async (vault, rule, body) =>
      toDomain(
        await unwrap(
          client.PATCH(`${V}/consistency/rules/{rule_id}`, {
            params: { path: { vault_id: vault, rule_id: rule } },
            body,
          }),
        ),
        'RuleInfo',
      ),
    suppressFinding: async (vault, body) =>
      toDomain(
        await unwrap(client.POST(`${V}/consistency/suppressions`, { params: path(vault), body })),
        'FindingOut',
      ),
    unsuppressFinding: async (vault, fingerprint) => {
      await client.DELETE(`${V}/consistency/suppressions/{fingerprint}`, {
        params: { path: { vault_id: vault, fingerprint } },
      })
    },
    createDimension: async (vault, body) =>
      toDomain(
        await unwrap(client.POST(`${V}/dimensions`, { params: path(vault), body })),
        'DimensionCreated',
      ),
    previewCalendar: async (vault, body) =>
      toDomain(
        await unwrap(client.POST(`${V}/calendars/preview`, { params: path(vault), body })),
        'Preview',
      ),
    proposeCalendarChange: async (vault, calendar, body) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/calendars/{calendar_id}/proposals`, {
            params: { path: { vault_id: vault, calendar_id: calendar } },
            body,
          }),
        ),
        'CalendarProposalOut',
      ),
    applyCalendarProposal: async (vault, calendar, proposal, body) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/calendars/{calendar_id}/proposals/{proposal_id}/apply`, {
            params: { path: { vault_id: vault, calendar_id: calendar, proposal_id: proposal } },
            body,
          }),
        ),
        'CalendarApplyOut',
      ),
    resolveTime: async (vault, body) =>
      toDomain(
        await unwrap(client.POST(`${V}/time/resolve`, { params: path(vault), body })),
        'ResolveOut',
      ),
    convertTime: async (vault, body) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/time/convert`, {
            params: path(vault),
            body: toWire(body) as unknown as Schemas['ConvertIn'],
          }),
        ),
        'ConvertOut',
      ),
    materializeOccurrence: async (vault, event, key) =>
      withEntity(
        await unwrap(
          client.POST(`${V}/events/{event_id}/occurrences/{key}`, {
            params: { path: { vault_id: vault, event_id: event, key } },
            body: null,
          }),
        ),
      ),
    deleteOccurrence: async (vault, event, key, options = {}) =>
      toDomain(
        await unwrap(
          client.DELETE(`${V}/events/{event_id}/occurrences/{key}`, {
            params: {
              path: { vault_id: vault, event_id: event, key },
              query: { trash_sub_events: options.trashSubEvents },
            },
            body: null,
          }),
        ),
        'EntityDeleteResult',
      ),
    proposeRecurrenceChange: async (vault, event, body) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/events/{event_id}/recurrence/proposals`, {
            params: { path: { vault_id: vault, event_id: event } },
            body,
          }),
        ),
        'RecurrenceProposalOut',
      ),
    applyRecurrenceProposal: async (vault, event, proposal, body) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/events/{event_id}/recurrence/proposals/{proposal_id}/apply`, {
            params: { path: { vault_id: vault, event_id: event, proposal_id: proposal } },
            body,
          }),
        ),
        'RecurrenceApplyOut',
      ),
  }
}

export type { Domain }
