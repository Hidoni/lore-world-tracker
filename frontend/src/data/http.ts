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
  method: 'POST' | 'PUT' = 'POST',
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open(method, path)
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
    publishStatus: (vault) => unwrap(client.GET(`${V}/publish`, { params: path(vault) })),
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
    entityState: async (vault, id, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/entities/{entity_id}/state`, {
            params: { path: { vault_id: vault, entity_id: id }, query },
          }),
        ),
        'EntityStateOut',
      ),
    facts: async (vault, id, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/entities/{entity_id}/facts`, {
            params: { path: { vault_id: vault, entity_id: id }, query },
          }),
        ),
        'FactList',
      ),
    causedFacts: async (vault, event) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/facts`, { params: { ...path(vault), query: { source_event: event } } }),
        ),
        'FactList',
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
    unlinkedMentions: async (vault, id, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/entities/{entity_id}/unlinked-mentions`, {
            params: { path: { vault_id: vault, entity_id: id }, query },
          }),
        ),
        'UnlinkedMentions',
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
    locationResidents: async (vault, location, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/locations/{location_id}/residents`, {
            params: { path: { vault_id: vault, location_id: location }, query },
          }),
        ),
        'EntityLinks',
      ),
    mediaItems: async (vault, query) =>
      toDomain(
        await unwrap(client.GET(`${V}/m/media/items`, { params: { ...path(vault), query } })),
        'MediaItemList',
      ),
    mediaItem: async (vault, media) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/media/items/{media_id}`, {
            params: { path: { vault_id: vault, media_id: media } },
          }),
        ),
        'MediaItemOut',
      ),
    gallery: async (vault, entity) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/media/entities/{entity_id}/gallery`, {
            params: { path: { vault_id: vault, entity_id: entity } },
          }),
        ),
        'GalleryOut',
      ),
    customFields: async (vault, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/custom_fields/fields`, { params: { ...path(vault), query } }),
        ),
        'CustomFieldList',
      ),
    customKinds: async (vault) =>
      toDomain(
        await unwrap(client.GET(`${V}/m/custom_fields/kinds`, { params: path(vault) })),
        'CustomKindList',
      ),
    maps: async (vault, query) =>
      toDomain(
        await unwrap(client.GET(`${V}/m/maps/maps`, { params: { ...path(vault), query } })),
        'MapList',
      ),
    mapDetail: async (vault, map, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/maps/maps/{map_id}`, {
            params: { path: { vault_id: vault, map_id: map }, query },
          }),
        ),
        'MapDetail',
      ),
    entityPins: async (vault, entity) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/maps/entities/{entity_id}/pins`, {
            params: { path: { vault_id: vault, entity_id: entity } },
          }),
        ),
        'EntityPins',
      ),
    characterRelationships: async (vault, character, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/characters/{character_id}/relationships`, {
            params: { path: { vault_id: vault, character_id: character }, query },
          }),
        ),
        'Relationships',
      ),
    characterFamilyTree: async (vault, character, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/characters/{character_id}/family-tree`, {
            params: { path: { vault_id: vault, character_id: character }, query },
          }),
        ),
        'Genealogy',
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
    groupLeaders: async (vault, group, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/groups/{group_id}/leaders`, {
            params: { path: { vault_id: vault, group_id: group }, query },
          }),
        ),
        'Leaders',
      ),
    groupOrgChart: async (vault, group, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/groups/{group_id}/org-chart`, {
            params: { path: { vault_id: vault, group_id: group }, query },
          }),
        ),
        'OrgChart',
      ),
    groupTerritory: async (vault, group, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/groups/{group_id}/territory`, {
            params: { path: { vault_id: vault, group_id: group }, query },
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
    speciesMembers: async (vault, species, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/species/{species_id}/members`, {
            params: { path: { vault_id: vault, species_id: species }, query },
          }),
        ),
        'EntityLinks',
      ),
    lexicon: async (vault, language, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/languages/{language_id}/lexicon`, {
            params: { path: { vault_id: vault, language_id: language }, query },
          }),
        ),
        'LexiconPage',
      ),
    lexiconEntry: async (vault, entry) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/languages/lexicon/{entry_id}`, {
            params: { path: { vault_id: vault, entry_id: entry } },
          }),
        ),
        'LexiconEntryOut',
      ),
    branchDiff: async (vault, timeline, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/branches/timelines/{timeline_id}/diff`, {
            params: { path: { vault_id: vault, timeline_id: timeline }, query },
          }),
        ),
        'BranchDiff',
      ),
    timelineNote: async (vault, entity, timeline) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/branches/notes/{entity_id}/{timeline_id}`, {
            params: { path: { vault_id: vault, entity_id: entity, timeline_id: timeline } },
          }),
        ),
        'NoteOut',
      ),
    correspondences: async (vault, query) =>
      toDomain(
        await unwrap(client.GET(`${V}/m/correspondences`, { params: { ...path(vault), query } })),
        'CorrespondenceList',
      ),
    correspondence: async (vault, id) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/correspondences/{correspondence_id}`, {
            params: { path: { vault_id: vault, correspondence_id: id } },
          }),
        ),
        'CorrespondenceOut',
      ),
    mapMoment: async (vault, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/correspondences/map`, { params: { ...path(vault), query } }),
        ),
        'MapOut',
      ),
    worldline: async (vault, entity, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/worldlines/entities/{entity_id}/segments`, {
            params: { path: { vault_id: vault, entity_id: entity }, query },
          }),
        ),
        'Worldline',
      ),
    presence: async (vault, entity, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/worldlines/entities/{entity_id}/presence`, {
            params: { path: { vault_id: vault, entity_id: entity }, query },
          }),
        ),
        'Presence',
      ),
    personalTimeline: async (vault, entity, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/worldlines/entities/{entity_id}/personal-timeline`, {
            params: { path: { vault_id: vault, entity_id: entity }, query },
          }),
        ),
        'PersonalTimeline',
      ),
    graph: async (vault, query) =>
      toDomain(
        await unwrap(client.GET(`${V}/m/graph/graph`, { params: { ...path(vault), query } })),
        'Graph',
      ),
    speciesDescentTree: async (vault, query) =>
      toDomain(
        await unwrap(
          client.GET(`${V}/m/species/descent-tree`, { params: { ...path(vault), query } }),
        ),
        'DescentTree',
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
    publishVault: (vault) => unwrap(client.POST(`${V}/publish`, { params: path(vault) })),
    exportStaticSite: (vault) =>
      unwrap(client.POST(`${V}/publish/static`, { params: path(vault) })),
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
    createFact: async (vault, entity, body) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/entities/{entity_id}/facts`, {
            params: { path: { vault_id: vault, entity_id: entity } },
            body,
          }),
        ),
        'FactWriteResult',
      ),
    updateFact: async (vault, id, body) =>
      toDomain(
        await unwrap(
          client.PATCH(`${V}/facts/{fact_id}`, {
            params: { path: { vault_id: vault, fact_id: id } },
            body,
          }),
        ),
        'FactWriteResult',
      ),
    deleteFact: async (vault, id) =>
      toDomain(
        await unwrap(
          client.DELETE(`${V}/facts/{fact_id}`, {
            params: { path: { vault_id: vault, fact_id: id } },
            body: null,
          }),
        ),
        'FactWriteResult',
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
    uploadMedia: async (vault, file, form = {}, onProgress = () => undefined) => {
      const body = new FormData()
      if (form.filename !== undefined) body.append('file', file, form.filename)
      else body.append('file', file)
      if (form.alt) body.append('alt', form.alt)
      if (form.caption) body.append('caption', form.caption)
      return toDomain(
        await uploadWithProgress<Schemas['MediaUploadResult']>(
          `/api/v1/vaults/${encodeURIComponent(vault)}/m/media/items`,
          body,
          onProgress,
        ),
        'MediaUploadResult',
      )
    },
    updateMedia: async (vault, media, body) =>
      toDomain(
        await unwrap(
          client.PATCH(`${V}/m/media/items/{media_id}`, {
            params: { path: { vault_id: vault, media_id: media } },
            body,
          }),
        ),
        'MediaItemOut',
      ),
    trashMedia: async (vault, media) =>
      toDomain(
        await unwrap(
          client.DELETE(`${V}/m/media/items/{media_id}`, {
            params: { path: { vault_id: vault, media_id: media } },
          }),
        ),
        'MediaItemOut',
      ),
    restoreMedia: async (vault, media) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/m/media/items/{media_id}/restore`, {
            params: { path: { vault_id: vault, media_id: media } },
          }),
        ),
        'MediaItemOut',
      ),
    replaceMediaFile: async (vault, media, file, revision, onProgress = () => undefined) => {
      const body = new FormData()
      body.append('file', file)
      body.append('revision', String(revision))
      return toDomain(
        await uploadWithProgress<Schemas['MediaItemOut']>(
          `/api/v1/vaults/${encodeURIComponent(vault)}/m/media/items/${encodeURIComponent(media)}/file`,
          body,
          onProgress,
          'PUT',
        ),
        'MediaItemOut',
      )
    },
    addToGallery: async (vault, entity, body) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/m/media/entities/{entity_id}/gallery`, {
            params: { path: { vault_id: vault, entity_id: entity } },
            body,
          }),
        ),
        'GalleryItemOut',
      ),
    updateGalleryItem: async (vault, item, body) =>
      toDomain(
        await unwrap(
          client.PATCH(`${V}/m/media/gallery/{item_id}`, {
            params: { path: { vault_id: vault, item_id: item } },
            body,
          }),
        ),
        'GalleryItemOut',
      ),
    removeFromGallery: async (vault, item) => {
      const { error, response } = await client.DELETE(`${V}/m/media/gallery/{item_id}`, {
        params: { path: { vault_id: vault, item_id: item } },
      })
      if (error !== undefined || !response.ok) throw await toApiError(response)
    },
    createCustomField: async (vault, body) =>
      toDomain(
        await unwrap(client.POST(`${V}/m/custom_fields/fields`, { params: path(vault), body })),
        'CustomFieldWriteResult',
      ),
    updateCustomField: async (vault, field, body) =>
      toDomain(
        await unwrap(
          client.PATCH(`${V}/m/custom_fields/fields/{field_id}`, {
            params: { path: { vault_id: vault, field_id: field } },
            body,
          }),
        ),
        'CustomFieldWriteResult',
      ),
    deleteCustomField: async (vault, field, deleteValues) =>
      toDomain(
        await unwrap(
          client.DELETE(`${V}/m/custom_fields/fields/{field_id}`, {
            params: {
              path: { vault_id: vault, field_id: field },
              query: { delete_values: deleteValues },
            },
          }),
        ),
        'CustomFieldDeleteResult',
      ),
    reorderCustomFields: async (vault, body) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/m/custom_fields/fields/reorder`, { params: path(vault), body }),
        ),
        'CustomFieldList',
      ),
    createCustomKind: async (vault, body) =>
      toDomain(
        await unwrap(client.POST(`${V}/m/custom_fields/kinds`, { params: path(vault), body })),
        'CustomKindWriteResult',
      ),
    updateCustomKind: async (vault, kind, body) =>
      toDomain(
        await unwrap(
          client.PATCH(`${V}/m/custom_fields/kinds/{kind_key}`, {
            params: { path: { vault_id: vault, kind_key: kind } },
            body,
          }),
        ),
        'CustomKindWriteResult',
      ),
    deleteCustomKind: async (vault, kind) =>
      toDomain(
        await unwrap(
          client.DELETE(`${V}/m/custom_fields/kinds/{kind_key}`, {
            params: { path: { vault_id: vault, kind_key: kind } },
          }),
        ),
        'CustomKindDeleteResult',
      ),
    convertKind: async (vault, body) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/m/custom_fields/convert-kind`, { params: path(vault), body }),
        ),
        'ConvertKindResult',
      ),
    createMap: async (vault, body) =>
      toDomain(
        await unwrap(client.POST(`${V}/m/maps/maps`, { params: path(vault), body })),
        'MapWriteResult',
      ),
    updateMap: async (vault, map, body) =>
      toDomain(
        await unwrap(
          client.PATCH(`${V}/m/maps/maps/{map_id}`, {
            params: { path: { vault_id: vault, map_id: map } },
            body,
          }),
        ),
        'MapWriteResult',
      ),
    deleteMap: async (vault, map) =>
      toDomain(
        await unwrap(
          client.DELETE(`${V}/m/maps/maps/{map_id}`, {
            params: { path: { vault_id: vault, map_id: map } },
          }),
        ),
        'MapWriteResult',
      ),
    createPin: async (vault, map, body) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/m/maps/maps/{map_id}/pins`, {
            params: { path: { vault_id: vault, map_id: map } },
            body,
          }),
        ),
        'PinWriteResult',
      ),
    updatePin: async (vault, pin, body) =>
      toDomain(
        await unwrap(
          client.PATCH(`${V}/m/maps/pins/{pin_id}`, {
            params: { path: { vault_id: vault, pin_id: pin } },
            body,
          }),
        ),
        'PinWriteResult',
      ),
    deletePin: async (vault, pin) =>
      toDomain(
        await unwrap(
          client.DELETE(`${V}/m/maps/pins/{pin_id}`, {
            params: { path: { vault_id: vault, pin_id: pin } },
          }),
        ),
        'PinWriteResult',
      ),
    createRegion: async (vault, map, body) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/m/maps/maps/{map_id}/regions`, {
            params: { path: { vault_id: vault, map_id: map } },
            body,
          }),
        ),
        'RegionWriteResult',
      ),
    updateRegion: async (vault, region, body) =>
      toDomain(
        await unwrap(
          client.PATCH(`${V}/m/maps/regions/{region_id}`, {
            params: { path: { vault_id: vault, region_id: region } },
            body,
          }),
        ),
        'RegionWriteResult',
      ),
    deleteRegion: async (vault, region) =>
      toDomain(
        await unwrap(
          client.DELETE(`${V}/m/maps/regions/{region_id}`, {
            params: { path: { vault_id: vault, region_id: region } },
          }),
        ),
        'RegionWriteResult',
      ),
    createLexiconEntry: async (vault, language, body) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/m/languages/{language_id}/lexicon`, {
            params: { path: { vault_id: vault, language_id: language } },
            body,
          }),
        ),
        'LexiconWriteResult',
      ),
    updateLexiconEntry: async (vault, entry, body) =>
      toDomain(
        await unwrap(
          client.PATCH(`${V}/m/languages/lexicon/{entry_id}`, {
            params: { path: { vault_id: vault, entry_id: entry } },
            body,
          }),
        ),
        'LexiconWriteResult',
      ),
    createBranch: async (vault, body) =>
      withEntity(
        await unwrap(client.POST(`${V}/m/branches/timelines`, { params: path(vault), body })),
      ),
    saveOverride: async (vault, body) =>
      toDomain(
        await unwrap(client.POST(`${V}/m/branches/overrides`, { params: path(vault), body })),
        'OverrideOut',
      ),
    revertOverride: async (vault, recordType, override) =>
      toDomain(
        await unwrap(
          client.DELETE(`${V}/m/branches/overrides/{record_type}/{override_id}`, {
            params: {
              path: { vault_id: vault, record_type: recordType, override_id: override },
            },
          }),
        ),
        'OverrideOut',
      ),
    putTimelineNote: async (vault, entity, timeline, body) =>
      toDomain(
        await unwrap(
          client.PUT(`${V}/m/branches/notes/{entity_id}/{timeline_id}`, {
            params: { path: { vault_id: vault, entity_id: entity, timeline_id: timeline } },
            body,
          }),
        ),
        'NoteOut',
      ),
    proposeBranchChange: async (vault, timeline, body) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/m/branches/timelines/{timeline_id}/proposals`, {
            params: { path: { vault_id: vault, timeline_id: timeline } },
            body,
          }),
        ),
        'BranchProposalOut',
      ),
    applyBranchProposal: async (vault, timeline, proposal, body) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/m/branches/timelines/{timeline_id}/proposals/{proposal_id}/apply`, {
            params: { path: { vault_id: vault, timeline_id: timeline, proposal_id: proposal } },
            body,
          }),
        ),
        'BranchApplied',
      ),
    createCorrespondence: async (vault, body) =>
      toDomain(
        await unwrap(client.POST(`${V}/m/correspondences`, { params: path(vault), body })),
        'CorrespondenceWriteResult',
      ),
    updateCorrespondence: async (vault, id, body) =>
      toDomain(
        await unwrap(
          client.PATCH(`${V}/m/correspondences/{correspondence_id}`, {
            params: { path: { vault_id: vault, correspondence_id: id } },
            body,
          }),
        ),
        'CorrespondenceWriteResult',
      ),
    deleteCorrespondence: async (vault, id) =>
      toDomain(
        await unwrap(
          client.DELETE(`${V}/m/correspondences/{correspondence_id}`, {
            params: { path: { vault_id: vault, correspondence_id: id } },
          }),
        ),
        'CorrespondenceWriteResult',
      ),
    replaceSegments: async (vault, entity, body) =>
      toDomain(
        await unwrap(
          client.PUT(`${V}/m/worldlines/entities/{entity_id}/segments`, {
            params: { path: { vault_id: vault, entity_id: entity } },
            body,
          }),
        ),
        'WorldlineWriteResult',
      ),
    timeTravel: async (vault, entity, body) =>
      toDomain(
        await unwrap(
          client.POST(`${V}/m/worldlines/entities/{entity_id}/time-travel`, {
            params: { path: { vault_id: vault, entity_id: entity } },
            body,
          }),
        ),
        'TimeTravelResult',
      ),
    deleteLexiconEntry: async (vault, entry) =>
      toDomain(
        await unwrap(
          client.DELETE(`${V}/m/languages/lexicon/{entry_id}`, {
            params: { path: { vault_id: vault, entry_id: entry } },
          }),
        ),
        'LexiconWriteResult',
      ),
    importLexicon: async (vault, language, body, dryRun) =>
      unwrap(
        client.POST(`${V}/m/languages/{language_id}/lexicon/import`, {
          params: { path: { vault_id: vault, language_id: language }, query: { dry_run: dryRun } },
          body,
        }),
      ),
  }
}

export type { Domain }
