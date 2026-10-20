import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  type RouterHistory,
} from '@tanstack/react-router'
import { lazy, Suspense } from 'react'

import { FindingsPage, type FindingsParams } from '@/core/consistency'
import { EntityListPage, EntityPage, TrashPage } from '@/core/entities'
import { CausalityPage, EventOutline } from '@/core/events'
import { ChangesPage } from '@/core/history'
import { ModuleGate, type ModuleDefinition } from '@/core/modules'
import { SearchPage, type SearchParams } from '@/core/search'
import {
  AuthorOnly,
  PlaceholderPage,
  ShellLayout,
  VaultHome,
  VaultPicker,
  VaultScope,
} from '@/core/shell'
import { CalendarEditor, DimensionOverview, NewCalendar } from '@/core/time'
import { moduleDefinitions } from '@/modules'

import { NotFoundPage, RouteError } from './route-error'
import { globalSearchSchema, parseSearch, stringifySearch } from './search'

// Code-based route tree (frontend.md §4). Every route exists; most render placeholders until their
// issues land. Module route factories attach under `/v/$vault/m/<id>` (modules.md §3), reachable
// only while the module is active in the vault.

/** Settings, loaded on first use (authors only; frontend.md §12). */
const SettingsPage = lazy(() =>
  import('@/core/settings/settings-page').then((loaded) => ({ default: loaded.SettingsPage })),
)

/** The timeline view, loaded on first use (frontend.md §12: heavy views load per route). */
const TimelineView = lazy(() =>
  import('@/core/timeline/timeline-view').then((loaded) => ({ default: loaded.TimelineView })),
)

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
const dimensionHomeRoute = createRoute({
  getParentRoute: () => dimensionRoute,
  path: '/',
  component: function DimensionHomeRoute() {
    const { vault, dimension } = dimensionHomeRoute.useParams()
    return <DimensionOverview key={dimension} vault={vault} dimensionId={dimension} />
  },
})
const timelineRoute = createRoute({
  getParentRoute: () => dimensionRoute,
  path: 'timeline',
  // `from`/`to`: the viewport (moments as decimal strings; it may extend outside the dimension).
  // `perf=1` shows the performance overlay. `in`: the events drilled into, comma-separated ids.
  // `scale=log`: the logarithmic axis (#153).
  validateSearch: (
    search,
  ): { from?: string; to?: string; perf?: '1'; in?: string; scale?: 'log' } => {
    const moment = (value: unknown) =>
      typeof value === 'string' && /^-?(0|[1-9][0-9]*)$/.test(value) ? value : undefined
    const from = moment(search.from)
    const to = moment(search.to)
    return {
      ...(from !== undefined && to !== undefined ? { from, to } : {}),
      ...(search.perf === '1' || search.perf === 1 ? { perf: '1' as const } : {}),
      ...(search.scale === 'log' ? { scale: 'log' as const } : {}),
      ...(typeof search.in === 'string' && /^[\w-]+(,[\w-]+)*$/.test(search.in)
        ? { in: search.in }
        : {}),
    }
  },
  component: function TimelineRoute() {
    const { vault, dimension } = timelineRoute.useParams()
    return (
      <Suspense fallback={<p className="p-6 text-sm text-muted-foreground">Loading…</p>}>
        <TimelineView key={dimension} vault={vault} dimensionId={dimension} />
      </Suspense>
    )
  },
})
const eventsRoute = createRoute({
  getParentRoute: () => dimensionRoute,
  path: 'events',
  component: function EventsRoute() {
    const { vault, dimension } = eventsRoute.useParams()
    return <EventOutline key={dimension} vault={vault} dimensionId={dimension} />
  },
})

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
const causalityRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: 'e/$entity/causality',
  component: function CausalityRoute() {
    const { vault, entity } = causalityRoute.useParams()
    return <CausalityPage key={entity} vault={vault} eventId={entity} />
  },
})
const calendarEditRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: 'calendars/$calendar/edit',
  component: function CalendarEditRoute() {
    const { vault, calendar } = calendarEditRoute.useParams()
    return (
      <AuthorOnly vault={vault}>
        <Suspense fallback={<p className="p-6 text-sm text-muted-foreground">Loading…</p>}>
          <CalendarEditor key={calendar} vault={vault} calendarId={calendar} />
        </Suspense>
      </AuthorOnly>
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
    return (
      <AuthorOnly vault={vault}>
        {dimension === undefined ? (
          <PlaceholderPage title="New calendar">
            Open it from a dimension’s overview.
          </PlaceholderPage>
        ) : (
          <Suspense fallback={<p className="p-6 text-sm text-muted-foreground">Loading…</p>}>
            <NewCalendar key={dimension} vault={vault} dimensionId={dimension} />
          </Suspense>
        )}
      </AuthorOnly>
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
      <AuthorOnly vault={vault}>
        <ChangesPage
          vault={vault}
          origins={origin?.split(',') ?? []}
          onOriginsChange={(origins) => {
            void navigate({ search: origins.length > 0 ? { origin: origins.join(',') } : {} })
          }}
        />
      </AuthorOnly>
    )
  },
})
const trashRoute = createRoute({
  getParentRoute: () => vaultRoute,
  path: 'trash',
  component: function TrashRoute() {
    const { vault } = trashRoute.useParams()
    return (
      <AuthorOnly vault={vault}>
        <TrashPage vault={vault} />
      </AuthorOnly>
    )
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
      <AuthorOnly vault={vault}>
        <FindingsPage
          vault={vault}
          params={params}
          onChange={(next) => {
            void navigate({ search: next, replace: true })
          }}
        />
      </AuthorOnly>
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
    return (
      <AuthorOnly vault={vault}>
        <Suspense fallback={<p className="p-6 text-sm text-muted-foreground">Loading…</p>}>
          <SettingsPage vault={vault} page="" />
        </Suspense>
      </AuthorOnly>
    )
  },
})
const settingsPageRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: '$',
  component: function SettingsPageRoute() {
    const { vault, _splat } = settingsPageRoute.useParams()
    return (
      <AuthorOnly vault={vault}>
        <Suspense fallback={<p className="p-6 text-sm text-muted-foreground">Loading…</p>}>
          <SettingsPage vault={vault} page={_splat ?? ''} />
        </Suspense>
      </AuthorOnly>
    )
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
    causalityRoute,
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
