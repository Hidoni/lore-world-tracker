import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'

import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import {
  createHttpDataSource,
  createHttpMutations,
  DataProvider,
  type DataSource,
  type Mutations,
} from '@/data'

import { createQueryClient } from './query-client'

/**
 * The app's providers. The data layer defaults to the HTTP API; reader mode (#138) and tests pass
 * their own `dataSource` and `mutations` (`null`: no writes).
 */
export function AppProviders({
  children,
  queryClient,
  dataSource,
  mutations,
}: {
  children: ReactNode
  queryClient?: QueryClient
  dataSource?: DataSource
  mutations?: Mutations | null
}) {
  const [client] = useState(() => queryClient ?? createQueryClient())
  const [source] = useState(() => dataSource ?? createHttpDataSource())
  const [writes] = useState(() => (mutations === undefined ? createHttpMutations() : mutations))

  return (
    <QueryClientProvider client={client}>
      <DataProvider dataSource={source} mutations={writes}>
        <TooltipProvider>
          {children}
          <Toaster />
        </TooltipProvider>
      </DataProvider>
    </QueryClientProvider>
  )
}
