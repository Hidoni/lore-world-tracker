import { RouterProvider } from '@tanstack/react-router'
import { act, render } from '@testing-library/react'

import { AppProviders } from '@/app/providers'
import { createQueryClient } from '@/app/query-client'
import { createAppRouter, createMemoryHistory } from '@/app/router'
import { useShell } from '@/core/shell'

/** Renders the whole app (providers, router, shell) at `path`. */
export async function renderApp(path = '/') {
  useShell.getState().reload()
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }))
  const queryClient = createQueryClient()
  queryClient.setDefaultOptions({ queries: { retry: false }, mutations: { retry: false } })
  const utils = render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  )
  await act(() => router.load())
  return { ...utils, router, queryClient }
}
