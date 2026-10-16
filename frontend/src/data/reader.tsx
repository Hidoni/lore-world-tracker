import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useState, type ReactNode } from 'react'

import { setPreviewingAsReader } from '@/api'

import { DataProvider } from './context'
import { keys } from './keys'
import type { DataSource, Mutations } from './source'

export interface ReaderMode {
  /** The server is read-only (`meta.read_only`): everyone is a reader. */
  readOnly: boolean
  /** The author previews the vault as a reader (`as_reader=true` on every read). */
  previewing: boolean
  /** Reading: no `Mutations`, so no editing UI; spoilers fold (frontend.md §13). */
  active: boolean
  setPreviewing: (on: boolean) => void
}

const STORAGE_KEY = 'lore.previewAsReader'

function storedPreview(): boolean {
  try {
    return globalThis.sessionStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

function storePreview(on: boolean): void {
  try {
    if (on) globalThis.sessionStorage.setItem(STORAGE_KEY, '1')
    else globalThis.sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // Storage may be unavailable (private mode): the preview just doesn't survive a reload.
  }
}

const ReaderModeContext = createContext<ReaderMode>({
  readOnly: false,
  previewing: false,
  active: false,
  setPreviewing: () => undefined,
})

/**
 * Reader mode (frontend.md §13): on a read-only server (`meta.read_only`) or while the author
 * previews as a reader, the app gets no `Mutations`. Turning the preview on or off resets every cached query, which then reloads as the
 * new mode sees it.
 */
export function ReaderModeProvider({
  dataSource,
  mutations,
  children,
}: {
  dataSource: DataSource
  mutations: Mutations | null
  children: ReactNode
}) {
  const client = useQueryClient()
  const meta = useQuery({ queryKey: keys.meta(), queryFn: () => dataSource.meta(), retry: false })
  const [previewing, setPreviewState] = useState(() => {
    const on = storedPreview()
    setPreviewingAsReader(on)
    return on
  })
  const readOnly = meta.data?.read_only === true
  const setPreviewing = (on: boolean): void => {
    storePreview(on)
    setPreviewingAsReader(on)
    setPreviewState(on)
    void client.resetQueries({ predicate: (query) => query.queryKey[0] !== 'meta' })
  }
  const active = readOnly || previewing || mutations === null
  // Nothing renders before the server says whether it is read-only, so editing UI never flashes
  // on a read-only server and no page mounts twice (author, then reader).
  if (meta.isPending) return null
  return (
    <ReaderModeContext value={{ readOnly, previewing, active, setPreviewing }}>
      <DataProvider dataSource={dataSource} mutations={active ? null : mutations}>
        {children}
      </DataProvider>
    </ReaderModeContext>
  )
}

/** Whether the app is in reader mode, and the author's preview toggle. */
export function useReaderMode(): ReaderMode {
  return useContext(ReaderModeContext)
}
