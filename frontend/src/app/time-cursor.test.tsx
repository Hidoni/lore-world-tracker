import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import { useExistenceFilter } from '@/core/time'
import { defaultRows, FIELD, KINDS, kind, row, serveVault, type FactRow } from '@/test/fake-vault'
import { renderApp } from '@/test/render-app'

beforeEach(() => {
  localStorage.clear()
  useExistenceFilter.setState({ hide: false })
})

const SECOND = { singular: 'second', plural: 'seconds', abbr: 's' }

/** Aetheria (Absolute calendar only, present at t = 500); the Crown with a history. */
function world() {
  const rank = { ...FIELD, key: 'rank', label: 'Rank', type: 'integer', temporal: true }
  const kinds = [
    KINDS[0],
    kind('artifact', 'Artifact', {
      allowed_parents: ['artifact'],
      fields: [FIELD, rank],
    }),
  ]
  const rows = [
    ...defaultRows().filter((entity) => entity.id !== 'd1'),
    row('d1', 'dimension', 'Aetheria', {
      ext: {
        base_unit: SECOND,
        duration: '1000000',
        default_calendar_id: null,
        present: null,
        present_t: '500',
        time_status: 'ok',
        prime_timeline_id: 'd1-prime',
      },
    }),
  ]
  const facts: FactRow[] = [
    { id: 'f-exists', entity_id: 'a1', field_key: 'core.exists', valid_from_t: '100', valid_to_t: '300' },
    { id: 'f-name', entity_id: 'a1', field_key: 'core.name', value: 'Old Crown', valid_to_t: '200' },
    { id: 'f-rank-1', entity_id: 'a1', field_key: 'rank', value: '3', valid_from_t: '100', valid_to_t: '200' },
    { id: 'f-rank-2', entity_id: 'a1', field_key: 'rank', value: '7', valid_from_t: '200', possible: true },
    { id: 'f-treasury', entity_id: 'a2', field_key: 'core.exists', valid_to_t: '350' },
  ] // prettier-ignore
  const links = [
    { id: 'l-gem', link_type: 'core.related', source_id: 'a1', target_id: 'a3' },
    { id: 'l-treasury', link_type: 'core.related', source_id: 'a1', target_id: 'a2',
      valid_from_t: '250' },
  ] // prettier-ignore
  return serveVault({ kinds, rows, facts, links })
}

const cursor = () => screen.findByRole('button', { name: /^Time cursor:/ })
const relations = () => screen.getByRole('region', { name: 'Relations' })

describe('time cursor', () => {
  it('reads the cursor from the URL and shows the entity as it was then', async () => {
    world()
    const { router } = await renderApp('/v/v1/e/a1?at=150')
    expect(await cursor()).toHaveAccessibleName('Time cursor: t = 150 s')
    const note = await screen.findByRole('status', { name: 'As of the time cursor' })
    expect(within(note).getByText(/Known as/)).toHaveTextContent('Known as Old Crown then.')
    const fields = screen.getByRole('region', { name: 'Fields' })
    expect(await within(fields).findByText('3')).toBeInTheDocument()
    expect(within(fields).getByText('Changed 2 times over time')).toBeInTheDocument()
    // The temporal link starts later: only the timeless one.
    await waitFor(() => {
      expect(within(relations()).queryByRole('link', { name: 'Treasury' })).toBeNull()
    })
    expect(within(relations()).getByRole('link', { name: 'Gem' })).toBeInTheDocument()

    // Moving the cursor changes what is shown, and goes to the URL.
    await userEvent.click(screen.getByRole('button', { name: 'One base unit later' }))
    expect(router.state.location.search).toMatchObject({ at: '151' })
    await userEvent.click(await cursor())
    await userEvent.click(await screen.findByRole('button', { name: 'All time' }))
    expect(router.state.location.search).toMatchObject({ at: 'all' })
    expect(await cursor()).toHaveAccessibleName('Time cursor: All time')
    await waitFor(() => {
      expect(screen.queryByRole('status', { name: 'As of the time cursor' })).toBeNull()
    })
    expect(await within(relations()).findByRole('link', { name: 'Treasury' })).toBeInTheDocument()
  })

  it('mutes what is only possible then', async () => {
    world()
    await renderApp('/v/v1/e/a1?at=260')
    await screen.findByRole('heading', { name: 'Crown', level: 1 })
    const fields = screen.getByRole('region', { name: 'Fields' })
    const value = await within(fields).findByText('7')
    expect(value.closest('[data-certainty]')).toHaveAttribute('data-certainty', 'possible')
    expect(await within(relations()).findByRole('link', { name: 'Treasury' })).toBeInTheDocument()
    // It exists then, under its own name: nothing to say.
    expect(screen.queryByRole('status', { name: 'As of the time cursor' })).toBeNull()
  })

  it('says when the entity no longer exists', async () => {
    world()
    await renderApp('/v/v1/e/a1?at=400')
    expect(await screen.findByText('No longer exists t = 300 s.')).toBeInTheDocument()
  })

  it('goes to the present, and hides what does not exist then from the sidebar', async () => {
    world()
    const { router } = await renderApp('/v/v1/e/a3?at=10')
    const sidebar = await screen.findByRole('navigation', { name: 'Vault' })
    expect(await within(sidebar).findByRole('link', { name: 'Treasury' })).toBeInTheDocument()

    await userEvent.click(await cursor())
    await userEvent.click(await screen.findByRole('button', { name: 'Present' }))
    expect(router.state.location.search).toMatchObject({ at: 'present' })
    expect(await cursor()).toHaveAccessibleName('Time cursor: Present')
    // At the present (t = 500) the Treasury is gone: hidden once the filter is on.
    await userEvent.click(await cursor())
    await userEvent.click(
      await screen.findByRole('checkbox', { name: /Hide entities that don’t exist then/ }),
    )
    await waitFor(() => {
      expect(within(sidebar).queryByRole('link', { name: 'Treasury' })).toBeNull()
    })
  })
})
