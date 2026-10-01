import { createRootRoute, createRoute, createRouter, Outlet } from '@tanstack/react-router'

import { HomePage } from '@/core/shell/home-page'
import { ShellLayout } from '@/core/shell/shell-layout'

// Code-based route tree (frontend.md §4): core routes are declared here, and module route
// factories will be attached under the vault route once module activation exists.

const rootRoute = createRootRoute({
  component: () => (
    <ShellLayout>
      <Outlet />
    </ShellLayout>
  ),
  notFoundComponent: () => <p className="p-8">Page not found.</p>,
})

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: HomePage,
})

export const routeTree = rootRoute.addChildren([indexRoute])

export function createAppRouter() {
  return createRouter({ routeTree })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}
