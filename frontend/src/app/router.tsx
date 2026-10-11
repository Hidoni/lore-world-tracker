import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  type RouterHistory,
} from '@tanstack/react-router'

import { EntityListPage, EntityPage, TrashPage } from '@/core/entities'
import { ChangesPage } from '@/core/history'
import { ModuleGate, type ModuleDefinition } from '@/core/modules'
import { SearchPage, type SearchParams } from '@/core/search'
import { PlaceholderPage, ShellLayout, VaultPicker, VaultScope } from '@/core/shell'
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

function page<TPath extends string>(path: TPath, title: string, description?: string) {
  return createRoute({
    getParentRoute: () => vaultRoute,
    path,
    component: () => <PlaceholderPage title={title}>{description}</PlaceholderPage>,
  })
}

const vaultHomeRoute = page('/', 'Vault home', 'Dimensions, recent changes and pinned entities.')

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
const dimensionHomeRoute = dimensionPage(
  '/',
  'Dimension',
  'Time spec, calendars, timelines and statistics.',
)
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
const calendarEditRoute = page(
  'calendars/$calendar/edit',
  'Calendar editor',
  'The calendar editor arrives with M5.',
)
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
const consistencyRoute = page('consistency', 'Consistency', 'Findings arrive with M6.')
const settingsRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: 'settings',
  component: Outlet,
})
const settingsIndexRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: '/',
  component: () => (
    <PlaceholderPage title="Settings">Vault settings arrive with #69.</PlaceholderPage>
  ),
})
const settingsPageRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: '$',
  component: () => (
    <PlaceholderPage title="Settings">Vault settings arrive with #69.</PlaceholderPage>
  ),
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
