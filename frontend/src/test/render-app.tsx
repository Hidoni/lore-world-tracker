import type { QueryClient } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { act, cleanup, render } from '@testing-library/react'

import { AppProviders } from '@/app/providers'
import { createHttpDataSource, keys } from '@/data'
import { createQueryClient } from '@/app/query-client'
import { createAppRouter, createMemoryHistory } from '@/app/router'
import { useSaveAnyway } from '@/core/consistency'
import type { ModuleDefinition } from '@/core/modules'
import { usePlaces } from '@/core/navigation/places'
import { usePalette } from '@/core/palette'
import { useShell } from '@/core/shell'
import { useWorkspace } from '@/core/workspace'

/** The app renders once the server says whether it is read-only (`ReaderModeProvider`). */
export async function prefetchMeta(queryClient: QueryClient): Promise<void> {
  const source = createHttpDataSource()
  await queryClient
    .query({ queryKey: keys.meta(), queryFn: () => source.meta() })
    .catch(() => undefined)
}

/**
 * Renders the whole app (providers, router, shell) at `path`, with `@/modules` or `modules`, in
 * place of an app rendered before; `readOnly` provides no `Mutations` (reader mode).
 */
export async function renderApp(
  path = '/',
  modules?: readonly ModuleDefinition[],
  options: { readOnly?: boolean } = {},
) {
  // One app at a time: an app left mounted would follow the next one's workspace.
  cleanup()
  useShell.getState().reload()
  usePlaces.getState().reload()
  useWorkspace.getState().reload()
  usePalette.setState({ open: false, shortcutsOpen: false })
  useSaveAnyway.setState({ pending: null })
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }), modules)
  const queryClient = createQueryClient()
  queryClient.setDefaultOptions({ queries: { retry: false }, mutations: { retry: false } })
  await prefetchMeta(queryClient)
  const utils = render(
    <AppProviders
      queryClient={queryClient}
      {...(modules ? { modules } : {})}
      {...(options.readOnly ? { mutations: null } : {})}
    >
      <RouterProvider router={router} />
    </AppProviders>,
  )
  await act(() => router.load())
  return { ...utils, router, queryClient }
}
