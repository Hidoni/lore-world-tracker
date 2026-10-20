import { PencilLineIcon, TrashIcon, XIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { BoundsEditor, type Bounds } from '@/core/time'
import {
  useDeleteRegion,
  useEntity,
  useUpdateRegion,
  type components,
  type MapRegion,
  type WireTimePoint,
} from '@/data'

import { AddPinDialog } from './add-pin-dialog'

type Schemas = components['schemas']
type Visibility = Schemas['Visibility']

/** A region's validity as it was stored (`null` bounds are open). */
function boundsOf(region: MapRegion): Bounds {
  return {
    from: region.valid_from ?? null,
    to: region.valid_to ?? null,
  }
}

/**
 * Editing one region (docs/modules/maps.md, UI: edit mode): the place it is (whose controllers
 * color it) or its label, its color, when it stands and who sees it; redrawing its outline (its
 * corners also drag on the map) or removing it.
 */
export function RegionEditor({
  vault,
  region,
  location,
  dimension,
  timeline,
  onRedraw,
  onClose,
}: {
  vault: string
  region: MapRegion
  /** The map's location (the parent of a location created for the region). */
  location: string
  /** The map location's dimension (its time points). */
  dimension: string | null
  /** Where a new validity lives (the cursor's timeline, else the dimension's prime). */
  timeline: string | null
  onRedraw: () => void
  onClose: () => void
}) {
  const update = useUpdateRegion(vault)
  const remove = useDeleteRegion(vault)
  const [label, setLabel] = useState(region.label ?? '')
  const [target, setTarget] = useState(region.target?.id ?? null)
  const picked = useEntity(
    vault,
    target ?? '',
    {},
    {
      enabled: target !== null && target !== region.target?.id,
    },
  )
  const targetName =
    target === null
      ? null
      : target === region.target?.id
        ? region.target.name
        : (picked.data?.name ?? '…')
  const [choosing, setChoosing] = useState(false)
  const [color, setColor] = useState(region.color ?? '')
  const [bounds, setBounds] = useState<Bounds>(boundsOf(region))
  const [visibility, setVisibility] = useState<Visibility>(region.visibility)
  const failed = (error: Error) => {
    toast.error(`The region wasn't saved: ${error.message}`)
  }
  const save = () => {
    const before = boundsOf(region)
    const body: Schemas['RegionUpdate'] = { revision: region.revision }
    const text = label.trim()
    if (text !== (region.label ?? '')) body.label = text === '' ? null : text
    if (target !== (region.target?.id ?? null)) body.target_entity_id = target
    if (color !== (region.color ?? '')) body.color = color === '' ? null : color
    if (visibility !== region.visibility) body.visibility = visibility
    if (JSON.stringify(bounds) !== JSON.stringify(before)) {
      body.valid_from = bounds.from as WireTimePoint | null
      body.valid_to = bounds.to as WireTimePoint | null
      body.timeline_id =
        bounds.from === null && bounds.to === null ? null : (region.timeline_id ?? timeline)
    }
    update.mutate({ region: region.id, body }, { onSuccess: onClose, onError: failed })
  }
  return (
    <section
      role="dialog"
      aria-label={`Edit ${region.display_label}`}
      className="absolute top-2 right-2 z-[1000] flex max-h-[calc(100%-1rem)] w-80 flex-col gap-3 overflow-y-auto rounded-md border bg-popover p-3 text-sm text-popover-foreground shadow-md"
    >
      <header className="flex items-center gap-2">
        <h3 className="flex-1 font-medium">{region.display_label}</h3>
        <button type="button" aria-label="Close" onClick={onClose}>
          <XIcon aria-hidden className="size-4" />
        </button>
      </header>
      <div className="flex flex-col gap-1">
        <span>Place</span>
        <div className="flex items-center gap-2">
          <span className="flex-1 truncate">{targetName ?? 'None (a label region)'}</span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setChoosing(true)
            }}
          >
            Change
          </Button>
          {target !== null && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setTarget(null)
              }}
            >
              Clear
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          Who controls the place (its “controls” links) colors the region.
        </p>
      </div>
      <label htmlFor={`${region.id}-label`}>Label</label>
      <Input
        id={`${region.id}-label`}
        value={label}
        placeholder={targetName ?? 'Label'}
        onChange={(event) => {
          setLabel(event.target.value)
        }}
      />
      <label className="flex flex-col gap-1">
        Color
        <span className="flex items-center gap-1">
          <input
            type="color"
            aria-label="Color"
            className="h-9 w-12 rounded-md border"
            value={color === '' ? '#64748b' : color}
            onChange={(event) => {
              setColor(event.target.value)
            }}
          />
          {color !== '' && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setColor('')
              }}
            >
              Controller’s color
            </Button>
          )}
        </span>
      </label>
      <fieldset className="flex flex-col gap-1">
        <legend className="mb-1">When it stands</legend>
        {timeline === null && region.timeline_id === null ? (
          <p className="text-xs text-muted-foreground">The location has no timeline.</p>
        ) : (
          <BoundsEditor vault={vault} dimensionId={dimension} value={bounds} onChange={setBounds} />
        )}
        <p className="text-xs text-muted-foreground">
          Without a period, it shows while its place exists.
        </p>
      </fieldset>
      <label className="flex flex-col gap-1">
        Visibility
        <select
          className="h-9 rounded-md border bg-transparent px-2"
          value={visibility}
          onChange={(event) => {
            setVisibility(event.target.value as Visibility)
          }}
        >
          <option value="public">Public</option>
          <option value="spoiler">Spoiler</option>
          <option value="private">Private</option>
        </select>
      </label>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={save} disabled={update.isPending}>
          Save
        </Button>
        <Button size="sm" variant="outline" onClick={onRedraw}>
          <PencilLineIcon aria-hidden />
          Redraw
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="ml-auto"
          onClick={() => {
            remove.mutate(region.id, { onSuccess: onClose, onError: failed })
          }}
        >
          <TrashIcon aria-hidden />
          Remove region
        </Button>
      </div>
      {choosing && (
        <AddPinDialog
          vault={vault}
          location={location}
          noun="region"
          onAdd={(choice) => {
            if ('target' in choice) {
              setTarget(choice.target)
            } else {
              setTarget(null)
              setLabel(choice.label)
            }
            setChoosing(false)
          }}
          onClose={() => {
            setChoosing(false)
          }}
        />
      )}
    </section>
  )
}
