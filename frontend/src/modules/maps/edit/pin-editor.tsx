import { TrashIcon, XIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { iconMap } from '@/core/registry'
import { BoundsEditor, type Bounds } from '@/core/time'
import {
  useDeletePin,
  useMaps,
  useUpdatePin,
  type components,
  type MapPin,
  type WireTimePoint,
} from '@/data'

type Schemas = components['schemas']
type Visibility = Schemas['Visibility']

const ICONS = Object.keys(iconMap).sort()

/** A pin's validity as it was stored (`null` bounds are open). */
function boundsOf(pin: MapPin): Bounds {
  return {
    from: pin.valid_from ?? null,
    to: pin.valid_to ?? null,
  }
}

/**
 * Editing one pin (docs/modules/maps.md, UI: edit mode): its label, icon, color, the map it drills
 * into, when it stands (a validity in `timeline`) and who sees it; or removing it.
 */
export function PinEditor({
  vault,
  pin,
  dimension,
  timeline,
  onClose,
}: {
  vault: string
  pin: MapPin
  /** The map location's dimension (its time points). */
  dimension: string | null
  /** Where a new validity lives (the cursor's timeline, else the dimension's prime). */
  timeline: string | null
  onClose: () => void
}) {
  const update = useUpdatePin(vault)
  const remove = useDeletePin(vault)
  const maps = useMaps(vault, null)
  const [label, setLabel] = useState(pin.label ?? '')
  const [icon, setIcon] = useState(pin.icon ?? '')
  const [color, setColor] = useState(pin.color ?? '')
  const [childMap, setChildMap] = useState(pin.child_map_id ?? '')
  const [bounds, setBounds] = useState<Bounds>(boundsOf(pin))
  const [visibility, setVisibility] = useState<Visibility>(pin.visibility)
  const failed = (error: Error) => {
    toast.error(`The pin wasn't saved: ${error.message}`)
  }
  const save = () => {
    const before = boundsOf(pin)
    const body: Schemas['PinUpdate'] = { revision: pin.revision }
    const text = label.trim()
    if (text !== (pin.label ?? '')) body.label = text === '' ? null : text
    if (icon !== (pin.icon ?? '')) body.icon = icon === '' ? null : icon
    if (color !== (pin.color ?? '')) body.color = color === '' ? null : color
    if (childMap !== (pin.child_map_id ?? '')) body.child_map_id = childMap === '' ? null : childMap
    if (visibility !== pin.visibility) body.visibility = visibility
    if (JSON.stringify(bounds) !== JSON.stringify(before)) {
      body.valid_from = bounds.from as WireTimePoint | null
      body.valid_to = bounds.to as WireTimePoint | null
      body.timeline_id =
        bounds.from === null && bounds.to === null ? null : (pin.timeline_id ?? timeline)
    }
    update.mutate({ pin: pin.id, body }, { onSuccess: onClose, onError: failed })
  }
  const others = (maps.data?.items ?? []).filter((map) => map.id !== pin.map_id)
  return (
    <section
      role="dialog"
      aria-label={`Edit ${pin.display_label}`}
      className="absolute top-2 right-2 z-[1000] flex max-h-[calc(100%-1rem)] w-80 flex-col gap-3 overflow-y-auto rounded-md border bg-popover p-3 text-sm text-popover-foreground shadow-md"
    >
      <header className="flex items-center gap-2">
        <h3 className="flex-1 font-medium">{pin.display_label}</h3>
        <button type="button" aria-label="Close" onClick={onClose}>
          <XIcon aria-hidden className="size-4" />
        </button>
      </header>
      <label htmlFor={`${pin.id}-label`}>Label</label>
      <Input
        id={`${pin.id}-label`}
        value={label}
        placeholder={pin.target?.name ?? 'Label'}
        onChange={(event) => {
          setLabel(event.target.value)
        }}
      />
      <div className="flex gap-2">
        <label className="flex flex-1 flex-col gap-1">
          Icon
          <select
            className="h-9 rounded-md border bg-transparent px-2"
            value={icon}
            onChange={(event) => {
              setIcon(event.target.value)
            }}
          >
            <option value="">Default</option>
            {ICONS.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
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
                Default
              </Button>
            )}
          </span>
        </label>
      </div>
      <label className="flex flex-col gap-1">
        Drills into
        <select
          className="h-9 rounded-md border bg-transparent px-2"
          value={childMap}
          onChange={(event) => {
            setChildMap(event.target.value)
          }}
        >
          <option value="">{pin.target === null ? 'No map' : 'The location’s own map'}</option>
          {others.map((map) => (
            <option key={map.id} value={map.id}>
              {map.name}
            </option>
          ))}
        </select>
      </label>
      <fieldset className="flex flex-col gap-1">
        <legend className="mb-1">When it stands</legend>
        {timeline === null && pin.timeline_id === null ? (
          <p className="text-xs text-muted-foreground">The location has no timeline.</p>
        ) : (
          <BoundsEditor vault={vault} dimensionId={dimension} value={bounds} onChange={setBounds} />
        )}
        <p className="text-xs text-muted-foreground">
          Without a period, it shows while its target exists.
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
      <div className="flex gap-2">
        <Button size="sm" onClick={save} disabled={update.isPending}>
          Save
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="ml-auto"
          onClick={() => {
            remove.mutate(pin.id, { onSuccess: onClose, onError: failed })
          }}
        >
          <TrashIcon aria-hidden />
          Remove pin
        </Button>
      </div>
    </section>
  )
}
