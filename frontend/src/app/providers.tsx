import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'

import { Toaster } from '@/components/ui/sonner'
import { requestSaveAnyway, SaveAnywayDialog } from '@/core/consistency'
import { ModuleDefinitionsProvider, type ModuleDefinition } from '@/core/modules'
import { TooltipProvider } from '@/components/ui/tooltip'
import {
  createHttpDataSource,
  createHttpMutations,
  ReaderModeProvider,
  type DataSource,
  type Mutations,
  withSaveAnyway,
} from '@/data'
import { moduleDefinitions } from '@/modules'

import { createQueryClient } from './query-client'

/**
 * The app's providers. The data layer defaults to the HTTP API; tests pass their own `dataSource`
 * and `mutations` (`null`: no writes). Reader mode (a read-only server, or the author's preview)
 * drops the `Mutations` (`ReaderModeProvider`). Writes refused by consistency rules
 * go through the save-anyway dialog. `modules` defaults to `@/modules`.
 */
export function AppProviders({
  children,
  queryClient,
  dataSource,
  mutations,
  modules = moduleDefinitions,
}: {
  children: ReactNode
  queryClient?: QueryClient
  dataSource?: DataSource
  mutations?: Mutations | null
  modules?: readonly ModuleDefinition[]
}) {
  const [client] = useState(() => queryClient ?? createQueryClient())
  const [source] = useState(() => dataSource ?? createHttpDataSource())
  const [writes] = useState(() => {
    const given = mutations === undefined ? createHttpMutations() : mutations
    // A write refused by consistency rules asks to save anyway (consistency.md §5).
    return given === null ? null : withSaveAnyway(given, requestSaveAnyway)
  })

  return (
    <QueryClientProvider client={client}>
      <ReaderModeProvider dataSource={source} mutations={writes}>
        <ModuleDefinitionsProvider definitions={modules}>
          <TooltipProvider>
            {children}
            <SaveAnywayDialog />
            <Toaster />
          </TooltipProvider>
        </ModuleDefinitionsProvider>
      </ReaderModeProvider>
    </QueryClientProvider>
  )
}
