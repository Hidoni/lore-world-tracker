import { create } from 'zustand'

import { readStored, writeStored } from '@/lib/storage'

/** An entity remembered in the sidebar (pinned or recently visited). */
export interface Place {
  id: string
  name: string
  kind: string
}

export const RECENT_LIMIT = 10
export type PlaceList = 'pinned' | 'recent'

const storageKey = (list: PlaceList, vault: string) => `lore.${list}.${vault}`

function load(list: PlaceList, vault: string): Place[] {
  const text = readStored(storageKey(list, vault))
  if (text === null) return []
  try {
    const value: unknown = JSON.parse(text)
    if (!Array.isArray(value)) return []
    return value.filter(
      (item): item is Place =>
        typeof item === 'object' &&
        item !== null &&
        typeof (item as Place).id === 'string' &&
        typeof (item as Place).name === 'string' &&
        typeof (item as Place).kind === 'string',
    )
  } catch {
    return []
  }
}

// Lists read from storage, so a list that wasn't changed yet is the same array on every read.
const loaded = new Map<string, Place[]>()

function stored(list: PlaceList, vault: string): Place[] {
  const key = `${list}:${vault}`
  let places = loaded.get(key)
  if (places === undefined) {
    places = load(list, vault)
    loaded.set(key, places)
  }
  return places
}

interface PlacesState {
  /** `<list>:<vault>` → places changed in this session. */
  lists: Record<string, Place[]>
  get: (list: PlaceList, vault: string) => Place[]
  set: (list: PlaceList, vault: string, places: Place[]) => void
  /** Forgets what was read (tests; storage changed). */
  reload: () => void
}

/**
 * Pinned and recent entities per vault (frontend.md §3), kept in `localStorage`
 * (`lore.pinned.<vault>`, `lore.recent.<vault>`).
 */
export const usePlaces = create<PlacesState>((set, get) => ({
  lists: {},
  get: (list, vault) => get().lists[`${list}:${vault}`] ?? stored(list, vault),
  set: (list, vault, places) => {
    writeStored(storageKey(list, vault), JSON.stringify(places))
    set((state) => ({ lists: { ...state.lists, [`${list}:${vault}`]: places } }))
  },
  reload: () => {
    loaded.clear()
    set({ lists: {} })
  },
}))

/** The places of a list, re-rendering when it changes. */
export function usePlaceList(list: PlaceList, vault: string): Place[] {
  return usePlaces((state) => state.lists[`${list}:${vault}`] ?? state.get(list, vault))
}

export function isPinned(vault: string, id: string): boolean {
  return usePlaces
    .getState()
    .get('pinned', vault)
    .some((place) => place.id === id)
}

export function togglePin(vault: string, place: Place): void {
  const { get, set } = usePlaces.getState()
  const pinned = get('pinned', vault)
  set(
    'pinned',
    vault,
    pinned.some((item) => item.id === place.id)
      ? pinned.filter((item) => item.id !== place.id)
      : [...pinned, place],
  )
}

/** Records a visit: the place moves to the top of the recent list (and pinned names refresh). */
export function visit(vault: string, place: Place): void {
  const { get, set } = usePlaces.getState()
  const recent = get('recent', vault)
  if (recent[0]?.id !== place.id || recent[0].name !== place.name) {
    set(
      'recent',
      vault,
      [place, ...recent.filter((item) => item.id !== place.id)].slice(0, RECENT_LIMIT),
    )
  }
  const pinned = get('pinned', vault)
  if (pinned.some((item) => item.id === place.id && item.name !== place.name)) {
    set(
      'pinned',
      vault,
      pinned.map((item) => (item.id === place.id ? place : item)),
    )
  }
}

/** Forgets an entity (purged). */
export function forget(vault: string, id: string): void {
  const { get, set } = usePlaces.getState()
  for (const list of ['pinned', 'recent'] as const) {
    const places = get(list, vault)
    if (places.some((item) => item.id === id))
      set(
        list,
        vault,
        places.filter((item) => item.id !== id),
      )
  }
}
