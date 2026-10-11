import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api'

import { RouteError } from './route-error'

describe('RouteError', () => {
  it('shows the failing route’s error and retries it', async () => {
    let broken = true
    const root = createRootRoute()
    const page = createRoute({
      getParentRoute: () => root,
      path: '/',
      component: function Broken() {
        if (broken) {
          throw new ApiError({
            status: 409,
            code: 'conflict',
            title: 'Conflict',
            detail: 'The vault is busy.',
          })
        }
        return <p>Recovered</p>
      },
    })
    const router = createRouter({
      routeTree: root.addChildren([page]),
      history: createMemoryHistory({ initialEntries: ['/'] }),
      defaultErrorComponent: RouteError,
    })
    render(<RouterProvider router={router} />)
    await act(() => router.load())

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Conflict')
    expect(alert).toHaveTextContent('The vault is busy.')
    expect(alert).toHaveTextContent('409 · conflict')
    broken = false
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Recovered')).toBeInTheDocument()
  })
})
