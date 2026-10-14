import { expect, test } from './fixtures'

// The graph view (docs/modules/graph.md) in a real browser: sigma.js draws with WebGL, the
// layout runs in a worker, the page stays responsive to pan and zoom, and a found entity opens.
test('graph: draws the world, finds and opens an entity', async ({ page, lore }) => {
  const dimension = await lore.createDimension('Aetheria')
  const ids: string[] = []
  for (let index = 0; index < 60; index++) {
    const entity = await lore.createEntity('misc', `Place ${index}`, {
      dimension_id: dimension.id,
    })
    ids.push(entity.id)
  }
  for (let index = 1; index < ids.length; index++) {
    await lore.link('core.related', ids[index] ?? '', ids[Math.floor(index / 3)] ?? '')
  }
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))

  await page.goto(`${lore.url()}/m/graph`)
  await expect(page.getByRole('heading', { name: 'Graph', level: 1 })).toBeVisible()
  const canvas = page.getByTestId('graph-canvas')
  await expect(canvas).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0) // WebGL works
  await expect(page.getByRole('button', { name: 'Stop the layout' })).toBeVisible()

  // Pan and zoom while the layout runs.
  const box = await canvas.boundingBox()
  if (box === null) throw new Error('no canvas')
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  for (let step = 0; step < 5; step++) await page.mouse.wheel(0, -200)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2 + 60, { steps: 10 })
  await page.mouse.up()
  await page.getByRole('button', { name: 'Freeze' }).click()
  await expect(page.getByRole('button', { name: 'Run the layout' })).toBeVisible()

  // Find one entity, then open it from the preview.
  await page.getByRole('textbox', { name: 'Find in the graph' }).fill('Place 42')
  await expect(page.getByText('1 found')).toBeVisible()
  await page.getByRole('textbox', { name: 'Find in the graph' }).press('Enter')
  const preview = page.getByRole('complementary', { name: 'Selected entity' })
  await preview.getByRole('link', { name: 'Open Place 42' }).click()
  await expect(page.getByRole('heading', { name: 'Place 42', level: 1 })).toBeVisible()
  expect(errors).toEqual([])
})
