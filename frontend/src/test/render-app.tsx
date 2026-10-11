import { RouterProvider } from '@tanstack/react-router'
import { act, render } from '@testing-library/react'

import { AppProviders } from '@/app/providers'
import { createQueryClient } from '@/app/query-client'
import { createAppRouter, createMemoryHistory } from '@/app/router'
import type { ModuleDefinition } from '@/core/modules'
import { useShell } from '@/core/shell'

/**
 * Renders the whole app (providers, router, shell) at `path`, with `@/modules` or `modules`;
 * `readOnly` provides no `Mutations` (reader mode).
 */
export async function renderApp(
  path = '/',
  modules?: readonly ModuleDefinition[],
  options: { readOnly?: boolean } = {},
) {
  useShell.getState().reload()
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }), modules)
  const queryClient = createQueryClient()
  queryClient.setDefaultOptions({ queries: { retry: false }, mutations: { retry: false } })
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
