import { createContext, useContext, type ReactNode } from 'react'

import type { DataSource, Mutations } from './source'

interface DataContextValue {
  dataSource: DataSource
  mutations: Mutations | null
}

const DataContext = createContext<DataContextValue | null>(null)

/**
 * Provides the `DataSource` and, outside reader and static contexts, the `Mutations`
 * (frontend.md §13: editing UI renders only when `useMutations()` isn't `null`).
 */
export function DataProvider({
  dataSource,
  mutations,
  children,
}: {
  dataSource: DataSource
  mutations: Mutations | null
  children: ReactNode
}) {
  return <DataContext value={{ dataSource, mutations }}>{children}</DataContext>
}

function useDataContext(): DataContextValue {
  const value = useContext(DataContext)
  if (value === null) throw new Error('No DataProvider: wrap the app in <DataProvider>')
  return value
}

export function useDataSource(): DataSource {
  return useDataContext().dataSource
}

/** The author's writes; `null` in reader and static contexts. */
export function useMutations(): Mutations | null {
  return useDataContext().mutations
}

/** For mutation hooks: the `Mutations`, or an error when this context can't write. */
export function useRequiredMutations(): Mutations {
  const mutations = useMutations()
  if (mutations === null) {
    return new Proxy({} as Mutations, {
      get: () => () => Promise.reject(new Error('This view is read-only.')),
    })
  }
  return mutations
}
