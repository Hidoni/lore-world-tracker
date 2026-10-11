import { formatInteger } from '@lore/chronology'
import { useId, useState, type KeyboardEvent } from 'react'

import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

import { BigNumberError, parseBigNumber } from './big-number'

export interface BigNumberInputProps {
  /** The value (`null`: empty or not a valid number). */
  value: bigint | null
  onChange: (value: bigint | null) => void
  /** Enter with a valid value. */
  onConfirm?: (value: bigint) => void
  /** Allow negative numbers. */
  signed?: boolean
  /** Inclusive bounds, checked after parsing. */
  min?: bigint
  max?: bigint
  /** The bounds' error, e.g. "after the end of time". */
  boundsMessage?: string
  id?: string
  'aria-label'?: string
  placeholder?: string
  disabled?: boolean
  className?: string
}

function grouped(value: bigint): string {
  return value < 0n ? `-${grouped(-value)}` : formatInteger(value, { scientificThreshold: 1001 })
}

/** The parsed value, or why it isn't one. */
function read(
  text: string,
  {
    signed,
    min,
    max,
    boundsMessage,
  }: Pick<BigNumberInputProps, 'signed' | 'min' | 'max' | 'boundsMessage'>,
): { value: bigint } | { error: string } {
  try {
    const value = parseBigNumber(text, { signed: signed === true })
    if ((min !== undefined && value < min) || (max !== undefined && value > max)) {
      return {
        error:
          boundsMessage ??
          `Must be between ${min === undefined ? '…' : grouped(min)} and ${max === undefined ? '…' : grouped(max)}`,
      }
    }
    return { value }
  } catch (error) {
    if (error instanceof BigNumberError) return { error: error.message }
    throw error
  }
}

/**
 * An arbitrary-size integer input (frontend.md §8): digits with any grouping, `1e100` or
 * `3.17 × 10^99`, and products with unit labels as a calculator (`10^100 years × 31,557,600 s`).
 * Below it, the parsed value (scientific notation when long) or the problem. Leaving the field
 * rewrites plain numbers with grouping.
 */
export function BigNumberInput(props: BigNumberInputProps) {
  const { value, onChange, onConfirm, id, placeholder, disabled, className } = props
  const [text, setText] = useState(() => (value === null ? '' : grouped(value)))
  const [shown, setShown] = useState(value)
  const hintId = useId()
  // A new value from outside (not the one this input reported) replaces the text.
  if (value !== shown) {
    setShown(value)
    if (value !== null) setText(grouped(value))
  }
  const result = text.trim() === '' ? null : read(text, props)
  const error = result !== null && 'error' in result ? result.error : null
  const parsed = result !== null && 'value' in result ? result.value : null
  const isExpression = parsed !== null && !/^[+-]?[\d,\s'_]+$/.test(text.trim())
  const magnitude = parsed === null ? null : parsed < 0n ? -parsed : parsed
  const digits = magnitude === null ? 0 : magnitude.toString().length
  const hint =
    error ??
    (magnitude !== null && parsed !== null && (isExpression || digits > 15)
      ? `= ${parsed < 0n ? '-' : ''}${formatInteger(magnitude)}${digits > 15 ? ` (${digits} digits)` : ''}`
      : '\u00a0')

  const change = (next: string) => {
    setText(next)
    const found = next.trim() === '' ? null : read(next, props)
    const nextValue = found !== null && 'value' in found ? found.value : null
    setShown(nextValue)
    onChange(nextValue)
  }
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' && parsed !== null && onConfirm !== undefined) {
      event.preventDefault()
      onConfirm(parsed)
    }
  }

  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <Input
        id={id}
        aria-label={props['aria-label']}
        aria-invalid={error !== null}
        aria-describedby={hintId}
        inputMode="text"
        autoComplete="off"
        spellCheck={false}
        placeholder={placeholder ?? (props.signed ? '-1,000 or 1e100' : '1,000 or 1e100')}
        disabled={disabled}
        className="font-mono"
        value={text}
        onChange={(event) => {
          change(event.target.value)
        }}
        onBlur={() => {
          if (parsed !== null && !isExpression) setText(grouped(parsed))
        }}
        onKeyDown={onKeyDown}
      />
      <p
        id={hintId}
        role={error === null ? undefined : 'alert'}
        className={cn('text-xs', error === null ? 'text-muted-foreground' : 'text-destructive')}
      >
        {hint}
      </p>
    </div>
  )
}
