import type { AnyRoute } from '@tanstack/react-router'
import type { ComponentType } from 'react'

import type { IconName } from '@/core/registry/icons'

/** Props every entity panel, header media and search-hit renderer gets. */
export interface EntityViewProps {
  vault: string
  entityId: string
  kind: string
}

/** A kind's UI (frontend.md §7). The server registry gives its label, fields and default icon. */
export interface KindUiConfig {
  /** Overrides the server's icon name (from the curated `iconMap`). */
  icon?: IconName
  color?: string
  /** Columns of entity lists of this kind (field keys). */
  listColumns?: readonly string[]
  /** Initial values of the create dialog. */
  createDefaults?: Readonly<Record<string, unknown>>
  /** A text field the sidebar section groups its top level by (misc: `category`). */
  groupBy?: string
  /** Icons per value of a field (locations: per `location_type`), in the sidebar and lists. */
  iconBy?: { field: string; icons: Readonly<Record<string, IconName>> }
}

export interface NavSection {
  id: string
  title: string
  order?: number
  component: ComponentType<{ vault: string }>
}

export interface EntityPanel {
  id: string
  /** The kinds it shows on (`'*'`: every kind). */
  kinds: readonly string[] | '*'
  title: string
  component: ComponentType<EntityViewProps>
  placement: 'main' | 'side'
  order?: number
}

/** A module's rendering of one link's details (role and `data`) in the relations panel. */
export interface LinkRowProps {
  vault: string
  linkId: string
  linkType: string
  role: string | null
  data: Readonly<Record<string, unknown>>
}

export interface FieldRendererProps {
  vault: string
  fieldKey: string
  value: unknown
}

export interface TimelineLayer {
  id: string
  title: string
  component: ComponentType<{ vault: string; timeline: string }>
}

/** Sigma/graph styles by kind and link type (the graph module reads them, M8). */
export interface GraphStyles {
  nodes?: Readonly<Record<string, { color?: string; size?: number }>>
  edges?: Readonly<Record<string, { color?: string; size?: number; dashed?: boolean }>>
}

export interface CommandContext {
  vault: string | undefined
  navigate: (to: string) => void
}

export interface Command {
  id: string
  title: string
  keywords?: readonly string[]
  run: (context: CommandContext) => void | Promise<void>
}

export interface SettingsPage {
  id: string
  title: string
  component: ComponentType<{ vault: string }>
}

/**
 * A TipTap extension (`Extension`, `Node` or `Mark`), typed loosely so core doesn't depend on
 * TipTap's types. The editor adds it; it can list slash-menu entries in its option `slashItems`
 * (`SlashItem[]` from `@/editor`).
 */
export interface EditorExtension {
  readonly name: string
}

export interface SearchHitProps {
  vault: string
  hit: Readonly<Record<string, unknown>>
}

/**
 * A module's routes, attached under `/v/$vault/m/<id>` and only reachable while the module is
 * active. `parent` is that route: return routes with `getParentRoute: () => parent`, and load
 * their components lazily (`lazyRouteComponent`).
 */
export type RouteFactory = (parent: AnyRoute) => AnyRoute[]

/**
 * A frontend module (modules.md §3, ADR-0005). Every member is an extension point; a module that
 * only has kinds needs `{ id, kinds }` at most.
 */
export interface ModuleDefinition {
  /** The backend module's id: activation follows its `enabled` flag in `GET /registry`. */
  id: string
  /** Modules whose `public.ts` this one imports (checked by `test/architecture.test.ts`). */
  dependsOn?: readonly string[]
  kinds?: Readonly<Record<string, KindUiConfig>>
  routes?: RouteFactory
  navSections?: readonly NavSection[]
  entityPanels?: readonly EntityPanel[]
  linkTypeRenderers?: Readonly<Record<string, ComponentType<LinkRowProps>>>
  fieldTypeRenderers?: Readonly<Record<string, ComponentType<FieldRendererProps>>>
  timelineLayers?: readonly TimelineLayer[]
  graphStyles?: GraphStyles
  editorExtensions?: readonly EditorExtension[]
  commands?: readonly Command[]
  settingsPages?: readonly SettingsPage[]
  searchResultRenderers?: Readonly<Record<string, ComponentType<SearchHitProps>>>
  /** Media shown in the entity header (e.g. a portrait), per kind. */
  entityHeaderMedia?: Readonly<Record<string, ComponentType<EntityViewProps>>>
}

const MODULE_ID = /^[a-z][a-z0-9_]*$/

/** Declares a frontend module. */
export function defineModule<const T extends ModuleDefinition>(definition: T): T {
  if (!MODULE_ID.test(definition.id)) {
    throw new Error(`invalid module id ${JSON.stringify(definition.id)}`)
  }
  return definition
}
