import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  type RouterHistory,
} from '@tanstack/react-router'

import { PlaceholderPage, ShellLayout, VaultPicker, VaultScope } from '@/core/shell'

import { NotFoundPage, RouteError } from './route-error'
import { globalSearchSchema, parseSearch, stringifySearch } from './search'

// Code-based route tree (frontend.md §4). Every route exists; most render placeholders until their
// issues land. Module route factories attach under `/v/$vault/m/$module` once module activation
// exists (#60).

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
  component: () => (
    <PlaceholderPage title="Entity">The entity page arrives with #61.</PlaceholderPage>
  ),
})
const calendarEditRoute = page(
  'calendars/$calendar/edit',
  'Calendar editor',
  'The calendar editor arrives with M5.',
)
const searchRoute = page('search', 'Search', 'Search results arrive with #67.')
const changesRoute = page('changes', 'Recent changes', 'The change feed arrives with #68.')
const trashRoute = page('trash', 'Trash', 'The trash arrives with #65.')
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
const moduleRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: 'm/$module/$',
  component: function ModuleRoute() {
    const { module } = moduleRoute.useParams()
    return (
      <PlaceholderPage title={`Module: ${module}`}>Module pages arrive with #60.</PlaceholderPage>
    )
  },
})

export const routeTree = rootRoute.addChildren([
  pickerRoute,
  vaultRoute.addChildren([
    vaultHomeRoute,
    dimensionRoute.addChildren([dimensionHomeRoute, timelineRoute, eventsRoute]),
    entityRoute,
    calendarEditRoute,
    searchRoute,
    changesRoute,
    trashRoute,
    consistencyRoute,
    settingsRoute.addChildren([settingsIndexRoute, settingsPageRoute]),
    moduleRoute,
  ]),
])

/** The app's router; tests pass a memory history (`createMemoryHistory`). */
export function createAppRouter(history?: RouterHistory) {
  return createRouter({
    routeTree,
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
