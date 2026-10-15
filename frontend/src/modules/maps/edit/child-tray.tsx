import { GripVerticalIcon, MapPinPlusIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useChildren, type MapPin } from '@/data'

import { ENTITY_DRAG_TYPE } from '../views/map-canvas'

/**
 * "Pin child locations": the map location's child locations not pinned on this map yet, to drag
 * onto the map (or place in the middle).
 */
export function ChildTray({
  vault,
  location,
  pins,
  onPlace,
}: {
  vault: string
  location: string
  pins: readonly MapPin[]
  /** Pin the location in the middle of the map. */
  onPlace: (entity: string) => void
}) {
  const children = useChildren(vault, location, { kind: ['location'], limit: 200 })
  const pinned = new Set(pins.flatMap((pin) => (pin.target === null ? [] : [pin.target.id])))
  const unplaced = (children.data?.items ?? []).filter((child) => !pinned.has(child.id))
  return (
    <section aria-label="Unplaced child locations" className="flex flex-col gap-1 text-sm">
      <h3 className="font-medium">Pin child locations</h3>
      {children.isPending ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : unplaced.length === 0 ? (
        <p className="text-muted-foreground">Every child location is on this map.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {unplaced.map((child) => (
            <li
              key={child.id}
              draggable
              onDragStart={(event) => {
                event.dataTransfer.setData(ENTITY_DRAG_TYPE, child.id)
                event.dataTransfer.effectAllowed = 'copy'
              }}
              className="flex cursor-grab items-center gap-1 rounded-md border px-2 py-1"
            >
              <GripVerticalIcon aria-hidden className="size-3.5 text-muted-foreground" />
              <span className="flex-1 truncate">{child.name}</span>
              <Button
                size="icon"
                variant="ghost"
                className="size-6"
                aria-label={`Place ${child.name} on the map`}
                onClick={() => {
                  onPlace(child.id)
                }}
              >
                <MapPinPlusIcon aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
