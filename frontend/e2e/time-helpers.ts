import { expect, type Page } from '@playwright/test'

import type { Lore } from './fixtures'

/**
 * The dimension wizard (frontend.md §8): a dimension named `name` in seconds, 10,000 years
 * long, with the Gregorian preset. Ends on the dimension's overview; returns its id.
 */
export async function createGregorianDimension(page: Page, lore: Lore, name: string) {
  await page.goto(lore.url())
  await page.getByRole('button', { name: 'Create dimension' }).click()
  const wizard = page.getByRole('dialog', { name: 'New dimension' })
  await wizard.getByLabel('Name').fill(name)
  await wizard.getByRole('button', { name: 'Next' }).click()
  await wizard.getByRole('button', { name: 'Next' }).click() // seconds
  await wizard.getByRole('button', { name: '10,000 years' }).click()
  await wizard.getByRole('button', { name: 'Next' }).click()
  await wizard.getByLabel('Preset').selectOption({ label: 'Gregorian' })
  await expect(wizard.getByRole('region', { name: 'Preview' })).toContainText('1 January AD 1')
  await wizard.getByRole('button', { name: 'Next' }).click()
  await wizard.getByRole('button', { name: 'Create dimension' }).click()
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
  const match = /\/d\/([^/?]+)/.exec(page.url())
  if (match?.[1] === undefined) throw new Error(`not on a dimension: ${page.url()}`)
  return match[1]
}

/** Fills a time point picker (the event dialog's start) with a Gregorian date at day precision. */
export async function typeDay(
  scope: ReturnType<Page['getByRole']>,
  year: number,
  month: string,
  day: number,
  picker = 'Start',
) {
  const start = scope.getByRole('group', { name: picker })
  await start.getByLabel('Precision').selectOption('day')
  await start.getByLabel('year', { exact: true }).fill(String(year))
  await start.getByLabel('month', { exact: true }).selectOption({ label: month })
  await start.getByLabel('day', { exact: true }).selectOption(String(day))
}

/** Seconds from the inception to the start of 1 January of a (proleptic Gregorian) year. */
export function yearStart(year: number): bigint {
  let days = 0n
  for (let y = 1; y < year; y++) {
    const leap = (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0
    days += leap ? 366n : 365n
  }
  return days * 86_400n
}

/** Moves the top bar's time cursor to a Gregorian day. */
export async function moveCursor(page: Page, year: number, month: string, day: number) {
  await page.getByRole('button', { name: /^Time cursor:/ }).click()
  const popover = page.getByRole('dialog')
  await typeDay(popover, year, month, day, 'Moment')
  await popover.getByRole('button', { name: 'Go to this moment' }).click()
  await expect(page.getByRole('button', { name: /^Time cursor:/ })).toHaveAccessibleName(
    new RegExp(`${day} ${month} AD ${year}`),
  )
}

/** An absolute time point at a moment. */
export function absolute(t: bigint) {
  return { anchor: { kind: 'absolute', t: t.toString() }, precision: 'base' }
}

/** A time point anchored to the start of an event. */
export function atStartOf(eventId: string) {
  return {
    anchor: {
      kind: 'relative',
      ref: { type: 'event', id: eventId, slot: 'start' },
      offset: { kind: 'base', units: '0' },
    },
    precision: 'base',
  }
}
