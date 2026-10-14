import type { TimePoint } from '@lore/chronology'
import { useState } from 'react'

import { Button } from '@/components/ui/button'

import { useDimensionLenses, useDisplayLens } from './time-context'
import { TimePointPicker } from './time-point-picker'

export interface Bounds {
  from: TimePoint | null
  to: TimePoint | null
}

function Bound({
  vault,
  dimensionId,
  label,
  open,
  value,
  onChange,
}: {
  vault: string
  dimensionId: string | null
  label: string
  /** What an unset bound means ("Always", "Still"). */
  open: string
  value: TimePoint | null
  onChange: (value: TimePoint | null) => void
}) {
  const { dimension, lenses } = useDimensionLenses(vault, dimensionId)
  const { lens } = useDisplayLens(vault, dimensionId)
  // Shown while a bound is set (a picker reports `null` until its date is valid).
  const [editing, setEditing] = useState(value !== null)
  if (!editing) {
    return (
      <div className="flex items-center gap-2 text-sm">
        <span className="w-12 text-muted-foreground">{label}</span>
        <span>{open}</span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={dimension === null}
          onClick={() => {
            setEditing(true)
          }}
        >
          Set {label.toLowerCase()}
        </Button>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-1 rounded-md border p-2">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{label}</span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            setEditing(false)
            onChange(null)
          }}
        >
          Clear
        </Button>
      </div>
      {dimension !== null && (
        <TimePointPicker
          dimension={dimension}
          lenses={lenses}
          value={value}
          onChange={onChange}
          displayLens={lens}
          vault={vault}
          label={label}
        />
      )}
    </div>
  )
}

/**
 * A validity period's bounds (time-model.md §10.1): each is open ("Always", "Still") or a time
 * point of the dimension, absolute, a date, or anchored to an event or another record
 * (`TimePointPicker`'s Relative tab). The end is excluded.
 */
export function BoundsEditor({
  vault,
  dimensionId,
  value,
  onChange,
  labels = { from: 'From', to: 'Until' },
}: {
  vault: string
  dimensionId: string | null
  value: Bounds
  onChange: (value: Bounds) => void
  labels?: { from: string; to: string }
}) {
  return (
    <div className="flex flex-col gap-2">
      <Bound
        vault={vault}
        dimensionId={dimensionId}
        label={labels.from}
        open="Always"
        value={value.from}
        onChange={(from) => {
          onChange({ ...value, from })
        }}
      />
      <Bound
        vault={vault}
        dimensionId={dimensionId}
        label={labels.to}
        open="Still"
        value={value.to}
        onChange={(to) => {
          onChange({ ...value, to })
        }}
      />
    </div>
  )
}
