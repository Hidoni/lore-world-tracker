import { expect, test } from './fixtures'
import { createGregorianDimension, yearStart } from './time-helpers'

const point = (t: bigint) => ({ anchor: { kind: 'absolute', t: t.toString() }, precision: 'base' })

// E7 (testing.md §3): branch from an event → override a war that spans the branch point →
// compare lanes show where the timelines diverge and what differs.
test('E7: branch from an event → override a spanning war → compare lanes show divergence', async ({
  page,
  lore,
}) => {
  const dimension = await createGregorianDimension(page, lore, 'Aetheria')
  const { id: war } = await lore.createEntity('event', 'The Long War', {
    dimension_id: dimension,
    ext: {
      start: point(yearStart(100)),
      end: { kind: 'time_point', time_point: point(yearStart(110)) },
    },
  })
  const { id: assassination } = await lore.createEntity('event', 'Assassination', {
    dimension_id: dimension,
    ext: { start: point(yearStart(105)), end: { kind: 'instant' } },
  })
  const prime = (
    (await lore.entity(dimension)) as unknown as { ext: { prime_timeline_id: string } }
  ).ext.prime_timeline_id
  const primeName = (await lore.entity(prime)).name

  // "What if…" on the assassination: a branch at its start, which becomes the viewed timeline.
  await page.goto(lore.url(assassination))
  await page.getByRole('button', { name: /What if…/ }).click()
  await page.getByRole('menuitem', { name: 'Branch at its start…' }).click()
  const create = page.getByRole('dialog', { name: 'New branch' })
  await create.getByLabel('Name').fill('The Emperor Survives')
  await create.getByLabel('Premise').fill('The assassin misses.')
  await create.getByRole('button', { name: 'Create branch' }).click()
  await expect(page.getByRole('button', { name: 'Timeline: The Emperor Survives' })).toBeVisible()
  const branch = new URL(page.url()).searchParams.get('tl')
  if (branch === null) throw new Error('the branch is not viewed')

  // The war spans the branch point: in the branch it ends earlier.
  await page.goto(`${lore.url(war)}?tl=${branch}`)
  const status = page.getByTestId('event-branch-status')
  await expect(status.getByText(`Inherited from ${primeName}`)).toBeVisible()
  await status.getByRole('button', { name: /Edit in this timeline/ }).click()
  const override = page.getByRole('dialog', { name: 'Edit The Long War in this timeline' })
  const end = override.getByRole('group', { name: 'End date' })
  await end.getByRole('tab', { name: 'Absolute' }).click()
  await end.getByRole('textbox', { name: 'Moment (seconds)' }).fill(yearStart(107).toString())
  await override.getByRole('button', { name: 'Save in this timeline' }).click()
  await expect(status.getByText('Changed in The Emperor Survives')).toBeVisible()

  // Compare the branch with the prime: two lane groups, the divergence and the shorter war.
  const from = yearStart(98)
  const to = yearStart(112)
  await page.goto(`${lore.url()}/d/${dimension}/timeline?tl=${branch}&from=${from}&to=${to}`)
  const timeline = page.getByRole('application', { name: 'Timeline' })
  await page.getByRole('button', { name: 'Compare timelines' }).click()
  await page.getByRole('menuitemcheckbox', { name: primeName }).click()
  await page.keyboard.press('Escape')
  const compared = timeline.getByRole('region', { name: `Compared: ${primeName}` })
  await expect(compared.getByRole('button', { name: 'The Long War' })).toBeVisible()
  await expect(timeline.getByTestId('divergence-marker')).toHaveAttribute('data-timeline', branch)
  const branchWar = timeline.locator('[data-diff]', { hasText: 'The Long War' })
  await expect(branchWar).toBeVisible()
  const primeWar = compared.getByRole('button', { name: 'The Long War' })
  await expect(primeWar).not.toHaveAttribute('data-diff', '')
  const widths = await Promise.all([branchWar.boundingBox(), primeWar.boundingBox()])
  expect(widths[0]?.width ?? 0).toBeLessThan(widths[1]?.width ?? 0)
})
