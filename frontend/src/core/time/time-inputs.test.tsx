import { fromFields, toFields, type Duration, type TimePoint } from '@lore/chronology'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'

import { presetLenses } from '@/test/calendars'

import { parseBigNumber } from './big-number'
import { BigNumberInput } from './big-number-input'
import { DurationPicker } from './duration-picker'
import { TimePointPicker } from './time-point-picker'

describe('parseBigNumber', () => {
  it('reads grouping, exponents, powers and products with unit labels', () => {
    expect(parseBigNumber('1,000,000')).toBe(1_000_000n)
    expect(parseBigNumber('1 000 000')).toBe(1_000_000n)
    expect(parseBigNumber('1e100')).toBe(10n ** 100n)
    expect(parseBigNumber('3.17 × 10^99')).toBe(317n * 10n ** 97n)
    expect(parseBigNumber('3.17e99')).toBe(317n * 10n ** 97n)
    expect(parseBigNumber('10^100 years × 31,557,600 s')).toBe(10n ** 100n * 31_557_600n)
    expect(parseBigNumber('2 days * 86400 s')).toBe(172_800n)
    expect(parseBigNumber('-86,400', { signed: true })).toBe(-86_400n)
  })

  it('rejects fractions, negatives where unsigned, too many digits and words', () => {
    expect(() => parseBigNumber('1.5')).toThrow('Must be a whole number')
    expect(() => parseBigNumber('-5')).toThrow('Must not be negative')
    expect(() => parseBigNumber('1e1000')).toThrow('At most 1000 digits')
    expect(() => parseBigNumber('ten')).toThrow('isn’t a number')
    expect(() => parseBigNumber('  ')).toThrow('Enter a number')
  })
})

describe('BigNumberInput', () => {
  function Harness({ max }: { max?: bigint }) {
    const [value, setValue] = useState<bigint | null>(null)
    return (
      <>
        <BigNumberInput
          aria-label="Amount"
          value={value}
          onChange={setValue}
          {...(max === undefined ? {} : { max })}
        />
        <output>{value === null ? 'none' : value.toString()}</output>
      </>
    )
  }

  it('shows huge values in scientific notation and checks bounds', async () => {
    render(<Harness max={10n ** 40n} />)
    const input = screen.getByRole('textbox', { name: 'Amount' })
    await userEvent.type(input, '10^39 × 3')
    expect(screen.getByText('= 3 × 10^39 (40 digits)')).toBeInTheDocument()
    expect(screen.getByRole('status', { hidden: true }).textContent).toBe(`3${'0'.repeat(39)}`)
    await userEvent.clear(input)
    await userEvent.type(input, '1e41')
    expect(screen.getByRole('alert')).toHaveTextContent('Must be between … and')
    expect(screen.getByRole('status', { hidden: true })).toHaveTextContent('none')
  })

  it('groups plain numbers on blur', async () => {
    render(<Harness />)
    const input = screen.getByRole('textbox', { name: 'Amount' })
    await userEvent.type(input, '31557600')
    await userEvent.tab()
    expect(input).toHaveValue('31,557,600')
  })
})

function Picker({ initial = null }: { initial?: TimePoint | null }) {
  const { dimension, lenses } = presetLenses('alternating-years', 'gregorian')
  const [value, setValue] = useState<TimePoint | null>(initial)
  return (
    <>
      <TimePointPicker dimension={dimension} lenses={lenses} value={initial} onChange={setValue} />
      <pre data-testid="value">{JSON.stringify(value)}</pre>
    </>
  )
}

const emitted = () => JSON.parse(screen.getByTestId('value').textContent) as TimePoint | null
const select = (name: string) => screen.getByRole('combobox', { name })
const optionsOf = (name: string) =>
  within(select(name))
    .getAllByRole('option')
    .map((option) => option.textContent)

describe('TimePointPicker', () => {
  it('offers the months of the year’s own template, by slot id', async () => {
    render(<Picker />)
    await userEvent.selectOptions(select('Precision'), 'day')
    await userEvent.type(screen.getByRole('textbox', { name: 'year' }), '1')
    expect(optionsOf('month')).toEqual(['Frostfall', 'Thawing', 'Bloom'])
    await userEvent.clear(screen.getByRole('textbox', { name: 'year' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'year' }), '2')
    expect(optionsOf('month')).toEqual(['Ember', 'Ash', 'Cinder'])
    await userEvent.selectOptions(select('month'), 'Ash')
    await userEvent.selectOptions(select('day'), '30')
    expect(emitted()).toEqual({
      anchor: {
        kind: 'calendar',
        calendar_id: 'alternating-years',
        fields: { year: '2', month: 'ash', day: '30' },
      },
      precision: 'day',
      approximate: false,
    })
    expect(screen.getByTestId('time-preview')).toHaveTextContent('t = ')
  })

  it('hides the levels finer than the precision', async () => {
    render(<Picker />)
    expect(screen.getByRole('textbox', { name: 'year' })).toBeInTheDocument()
    await userEvent.type(screen.getByRole('textbox', { name: 'year' }), '3')
    expect(screen.getByRole('combobox', { name: 'second' })).toBeInTheDocument()
    await userEvent.selectOptions(select('Precision'), 'month')
    expect(screen.queryByRole('combobox', { name: 'day' })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'second' })).not.toBeInTheDocument()
    expect(emitted()?.anchor).toEqual({
      kind: 'calendar',
      calendar_id: 'alternating-years',
      fields: { year: '3', month: 'frostfall' },
    })
  })

  it('never offers an invalid date', async () => {
    render(<Picker />)
    await userEvent.selectOptions(select('Precision'), 'day')
    await userEvent.type(screen.getByRole('textbox', { name: 'year' }), '1')
    await userEvent.selectOptions(select('month'), 'Thawing')
    expect(optionsOf('day').at(-1)).toBe('31')
    await userEvent.selectOptions(select('day'), '31')
    // Frostfall has 30 days: the 31st isn't offered, the day falls back to a valid one.
    await userEvent.selectOptions(select('month'), 'Frostfall')
    expect(optionsOf('day').at(-1)).toBe('30')
    const point = emitted()
    expect(point?.anchor).toMatchObject({ fields: { year: '1', month: 'frostfall', day: '1' } })
    // Era years start at 1: AF 0 doesn't exist.
    await userEvent.selectOptions(select('Era'), 'After the Founding (AF)')
    await userEvent.clear(screen.getByRole('textbox', { name: 'year' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'year' }), '0')
    expect(emitted()).toBeNull()
  })

  it('round-trips a stored time point through the engine', async () => {
    const { lenses } = presetLenses('alternating-years')
    const calendar = lenses[0]?.calendar
    if (calendar === undefined || calendar === null) throw new Error('no calendar')
    const initial: TimePoint = {
      anchor: {
        kind: 'calendar',
        calendar_id: 'alternating-years',
        fields: { year: '7', month: 'bloom', day: '12' },
        era: 'af',
      },
      precision: 'day',
      approximate: false,
    }
    render(<Picker initial={initial} />)
    expect(select('Era')).toHaveValue('af')
    expect(screen.getByRole('textbox', { name: 'year' })).toHaveValue('7')
    expect(select('month')).toHaveValue('bloom')
    expect(select('day')).toHaveValue('12')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Circa (approximate)' }))
    const point = emitted()
    expect(point).toEqual({ ...initial, approximate: true })
    if (point?.anchor.kind !== 'calendar') throw new Error('not a calendar anchor')
    const t = fromFields(calendar, point.anchor.fields, 'day', { era: 'af' })
    const back = toFields(calendar, t)
    expect(back.era).toMatchObject({ id: 'af', year: 7n })
    expect(back.levels.get('month')?.slotId).toBe('bloom')
    expect(back.levels.get('day')?.n).toBe(12n)
  })

  it('takes huge absolute moments within the dimension', async () => {
    render(<Picker />)
    await userEvent.click(screen.getByRole('tab', { name: 'Absolute' }))
    const input = screen.getByRole('textbox', { name: 'Moment (seconds)' })
    await userEvent.type(input, '1e41')
    expect(screen.getByRole('alert')).toHaveTextContent('After the end of time')
    expect(emitted()).toBeNull()
    await userEvent.clear(input)
    await userEvent.type(input, '10^25 years × 31,557,600 s')
    expect(emitted()).toEqual({
      anchor: { kind: 'absolute', t: (10n ** 25n * 31_557_600n).toString() },
      precision: 'base',
      approximate: false,
    })
    expect(screen.getByTestId('time-preview')).toHaveTextContent('t = 3.156 × 10^32 s')
  })
})

describe('DurationPicker', () => {
  function Harness() {
    const { dimension, lenses } = presetLenses('gregorian')
    const [value, setValue] = useState<Duration | null>(null)
    return (
      <>
        <DurationPicker dimension={dimension} lenses={lenses} value={null} onChange={setValue} />
        <pre data-testid="duration">{JSON.stringify(value)}</pre>
      </>
    )
  }
  const duration = () => JSON.parse(screen.getByTestId('duration').textContent) as unknown

  it('takes base units with a sign, or calendar amounts per level', async () => {
    render(<Harness />)
    await userEvent.selectOptions(select('Duration sign'), '− earlier')
    await userEvent.type(screen.getByRole('textbox', { name: 'Duration in seconds' }), '86,400')
    expect(duration()).toEqual({ kind: 'base', units: '-86400' })
    await userEvent.selectOptions(select('Duration unit'), 'Gregorian units')
    await userEvent.type(screen.getByRole('textbox', { name: 'Duration: months' }), '3')
    await userEvent.type(screen.getByRole('textbox', { name: 'Duration: days' }), '2')
    expect(duration()).toEqual({
      kind: 'calendar',
      calendar_id: 'gregorian',
      amounts: { month: '3', day: '2' },
      sign: -1,
    })
  })
})
