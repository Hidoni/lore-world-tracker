import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  type RouterHistory,
} from '@tanstack/react-router'
import { Suspense } from 'react'

import { FindingsPage, type FindingsParams } from '@/core/consistency'
import { EntityListPage, EntityPage, TrashPage } from '@/core/entities'
import { ChangesPage } from '@/core/history'
import { ModuleGate, type ModuleDefinition } from '@/core/modules'
import { SearchPage, type SearchParams } from '@/core/search'
import { SettingsPage } from '@/core/settings'
import { PlaceholderPage, ShellLayout, VaultHome, VaultPicker, VaultScope } from '@/core/shell'
import { CalendarEditor, DimensionOverview, NewCalendar } from '@/core/time'
import { moduleDefinitions } from '@/modules'

import { NotFoundPage, RouteError } from './route-error'
import { globalSearchSchema, parseSearch, stringifySearch } from './search'

// Code-based route tree (frontend.md §4). Every route exists; most render placeholders until their
// issues land. Module route factories attach under `/v/$vault/m/<id>` (modules.md §3), reachable
// only while the module is active in the vault.

const rootRoute = createRootRoute({
  validateSearch: (search) => globalSearchSchema.parse(search),
  component: () => (
    <ShellLayout>
      <Outlet />
    </ShellLayout>
  ),
})

const pickerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  // `?pick=true` shows the picker instead of reopening the last vault.
  validateSearch: (search): { pick?: boolean } =>
    search.pick === true || search.pick === 'true' ? { pick: true } : {},
  component: function PickerPage() {
    const { pick } = pickerRoute.useSearch()
    return <VaultPicker pick={pick === true} />
  },
})

const vaultRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/v/$vault',
  component: function VaultRoute() {
    const { vault } = vaultRoute.useParams()
    return <VaultScope vault={vault} />
  },
})

const vaultHomeRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: '/',
  component: function VaultHomeRoute() {
    const { vault } = vaultHomeRoute.useParams()
    return <VaultHome vault={vault} />
  },
})

const dimensionRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: 'd/$dimension',
})
const dimensionPage = <TPath extends string>(path: TPath, title: string, description: string) =>
  createRoute({
    getParentRoute: () => dimensionRoute,
    path,
    component: () => <PlaceholderPage title={title}>{description}</PlaceholderPage>,
  })
const dimensionHomeRoute = createRoute({
  getParentRoute: () => dimensionRoute,
  path: '/',
  component: function DimensionHomeRoute() {
    const { vault, dimension } = dimensionHomeRoute.useParams()
    return <DimensionOverview key={dimension} vault={vault} dimensionId={dimension} />
  },
})
const timelineRoute = dimensionPage('timeline', 'Timeline', 'The timeline view arrives with M5.')
const eventsRoute = dimensionPage('events', 'Events', 'The event outline arrives with M5.')

const entityRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: 'e/$entity',
  validateSearch: (search): { tab?: string } =>
    typeof search.tab === 'string' && search.tab ? { tab: search.tab } : {},
  component: function EntityRoute() {
    const { vault, entity } = entityRoute.useParams()
    return <EntityPage key={entity} vault={vault} entityId={entity} />
  },
})
const calendarEditRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: 'calendars/$calendar/edit',
  component: function CalendarEditRoute() {
    const { vault, calendar } = calendarEditRoute.useParams()
    return (
      <Suspense fallback={<p className="p-6 text-sm text-muted-foreground">Loading…</p>}>
        <CalendarEditor key={calendar} vault={vault} calendarId={calendar} />
      </Suspense>
    )
  },
})
const calendarNewRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: 'calendars/new',
  // `?dimension=<id>`: the dimension the calendar belongs to.
  validateSearch: (search): { dimension?: string } =>
    typeof search.dimension === 'string' && search.dimension !== ''
      ? { dimension: search.dimension }
      : {},
  component: function CalendarNewRoute() {
    const { vault } = calendarNewRoute.useParams()
    const { dimension } = calendarNewRoute.useSearch()
    return dimension === undefined ? (
      <PlaceholderPage title="New calendar">Open it from a dimension’s overview.</PlaceholderPage>
    ) : (
      <Suspense fallback={<p className="p-6 text-sm text-muted-foreground">Loading…</p>}>
        <NewCalendar key={dimension} vault={vault} dimensionId={dimension} />
      </Suspense>
    )
  },
})
const searchRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: 'search',
  // Filters stay strings; empty ones are dropped.
  validateSearch: (search): SearchParams => {
    const pick = (value: unknown) => (typeof value === 'string' && value !== '' ? value : undefined)
    const params: SearchParams = {}
    const q = pick(search.q)
    const kind = pick(search.kind)
    const dimension = pick(search.dimension)
    if (q !== undefined) params.q = q
    if (kind !== undefined) params.kind = kind
    if (dimension !== undefined) params.dimension = dimension
    return params
  },
  component: function SearchRoute() {
    const { vault } = searchRoute.useParams()
    const params = searchRoute.useSearch()
    const navigate = searchRoute.useNavigate()
    return (
      <SearchPage
        key={params.q ?? ''}
        vault={vault}
        params={params}
        onChange={(next) => {
          void navigate({ search: next })
        }}
      />
    )
  },
})
const changesRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: 'changes',
  // `?origin=ui,undo`: the origins shown (all when absent).
  validateSearch: (search): { origin?: string } =>
    typeof search.origin === 'string' && search.origin !== '' ? { origin: search.origin } : {},
  component: function ChangesRoute() {
    const { vault } = changesRoute.useParams()
    const { origin } = changesRoute.useSearch()
    const navigate = changesRoute.useNavigate()
    return (
      <ChangesPage
        vault={vault}
        origins={origin?.split(',') ?? []}
        onOriginsChange={(origins) => {
          void navigate({ search: origins.length > 0 ? { origin: origins.join(',') } : {} })
        }}
      />
    )
  },
})
const trashRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: 'trash',
  component: function TrashRoute() {
    const { vault } = trashRoute.useParams()
    return <TrashPage vault={vault} />
  },
})
const kindListRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: 'k/$kind',
  component: function KindListRoute() {
    const { vault, kind } = kindListRoute.useParams()
    return <EntityListPage key={kind} vault={vault} kindKey={kind} />
  },
})
const consistencyRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: 'consistency',
  // Filters stay strings (`uncertain`, `suppressed`: `true`); empty ones are dropped.
  validateSearch: (search): FindingsParams => {
    const params: FindingsParams = {}
    for (const key of ['severity', 'rule', 'owner', 'entity', 'timeline'] as const) {
      const value = search[key]
      if (typeof value === 'string' && value !== '') params[key] = value
    }
    if (search.uncertain === true || search.uncertain === 'true') params.uncertain = true
    if (search.suppressed === true || search.suppressed === 'true') params.suppressed = true
    return params
  },
  component: function ConsistencyRoute() {
    const { vault } = consistencyRoute.useParams()
    const params = consistencyRoute.useSearch()
    const navigate = consistencyRoute.useNavigate()
    return (
      <FindingsPage
        vault={vault}
        params={params}
        onChange={(next) => {
          void navigate({ search: next, replace: true })
        }}
      />
    )
  },
})
const settingsRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: 'settings',
  component: Outlet,
})
const settingsIndexRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: '/',
  component: function SettingsIndexRoute() {
    const { vault } = settingsIndexRoute.useParams()
    return <SettingsPage vault={vault} page="" />
  },
})
const settingsPageRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: '$',
  component: function SettingsPageRoute() {
    const { vault, _splat } = settingsPageRoute.useParams()
    return <SettingsPage vault={vault} page={_splat ?? ''} />
  },
})
// Paths of modules without routes, or that don't exist.
const unknownModuleRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: 'm/$module/$',
  component: NotFoundPage,
})

/** Each module's routes under `/v/$vault/m/<id>`, behind its activation. */
function moduleRoutes(definitions: readonly ModuleDefinition[]) {
  return definitions.flatMap((definition) => {
    if (definition.routes === undefined) return []
    const parent = createRoute({
      getParentRoute: () => vaultRoute,
      path: `m/${definition.id}`,
      component: () => <ModuleGate module={definition.id} notFound={<NotFoundPage />} />,
    })
    return [parent.addChildren(definition.routes(parent))]
  })
}

function buildRouteTree(definitions: readonly ModuleDefinition[]) {
  const children = [
    vaultHomeRoute,
    dimensionRoute.addChildren([dimensionHomeRoute, timelineRoute, eventsRoute]),
    entityRoute,
    kindListRoute,
    calendarEditRoute,
    calendarNewRoute,
    searchRoute,
    changesRoute,
    trashRoute,
    consistencyRoute,
    settingsRoute.addChildren([settingsIndexRoute, settingsPageRoute]),
    unknownModuleRoute,
  ] as const
  // Module routes are added untyped (modules navigate by path): the registered router type is the
  // core tree's.
  const withModules = [...children, ...moduleRoutes(definitions)] as unknown as typeof children
  return rootRoute.addChildren([pickerRoute, vaultRoute.addChildren(withModules)])
}

/**
 * The app's router; tests pass a memory history (`createMemoryHistory`) and, to try a module, its
 * definitions (default: `@/modules`).
 */
export function createAppRouter(
  history?: RouterHistory,
  definitions: readonly ModuleDefinition[] = moduleDefinitions,
) {
  return createRouter({
    routeTree: buildRouteTree(definitions),
    history,
    parseSearch,
    stringifySearch,
    defaultErrorComponent: RouteError,
    defaultNotFoundComponent: NotFoundPage,
  })
}

export { createMemoryHistory }

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}
