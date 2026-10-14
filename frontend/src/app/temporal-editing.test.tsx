import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import { useExistenceFilter } from '@/core/time'
import {
  defaultRows,
  FIELD,
  KINDS,
  kind,
  linkType,
  row,
  serveVault,
  type FactRow,
} from '@/test/fake-vault'
import { renderApp } from '@/test/render-app'

beforeEach(() => {
  localStorage.clear()
  useExistenceFilter.setState({ hide: false })
})

const SECOND = { singular: 'second', plural: 'seconds', abbr: 's' }

/** Aetheria (Absolute calendar only); the Crown with a temporal Rank, Aria a character. */
function world(facts: FactRow[] = []) {
  const rank = { ...FIELD, key: 'rank', label: 'Rank', type: 'integer', temporal: true }
  const kinds = [
    KINDS[0],
    kind('artifact', 'Artifact', { allowed_parents: ['artifact'], fields: [FIELD, rank] }),
    kind('character', 'Character'),
    kind('event', 'Event'),
  ]
  const rows = [
    ...defaultRows().filter((entity) => entity.id !== 'd1'),
    row('d1', 'dimension', 'Aetheria', {
      ext: {
        base_unit: SECOND,
        duration: '1000000',
        default_calendar_id: null,
        present: null,
        present_t: null,
        time_status: 'ok',
        prime_timeline_id: 'd1-prime',
      },
    }),
    row('c1', 'character', 'Aria'),
    row('e1', 'event', 'Coronation'),
  ]
  const linkTypes = [
    linkType('core.related', 'related to', { symmetric: true, temporal: 'optional' }),
  ]
  return serveVault({ kinds, rows, facts, linkTypes })
}

async function setAbsolute(scope: HTMLElement, label: string, value: string) {
  await userEvent.click(within(scope).getByRole('button', { name: `Set ${label.toLowerCase()}` }))
  await userEvent.click(within(scope).getByRole('tab', { name: 'Absolute' }))
  await userEvent.type(within(scope).getByRole('textbox', { name: 'Moment (seconds)' }), value)
}

describe('temporal editing', () => {
  it('adds, edits and deletes values of a temporal field, flagging overlaps', async () => {
    const writes = world([
      { id: 'f1', entity_id: 'a1', field_key: 'rank', value: '3', valid_to_t: '200' },
    ])
    await renderApp('/v/v1/e/a1')
    const fields = await screen.findByRole('region', { name: 'Fields' })
    await userEvent.click(within(fields).getByRole('button', { name: 'Rank over time' }))
    const history = await screen.findByRole('region', { name: 'Rank over time' })
    expect(await within(history).findByText('3')).toBeInTheDocument()

    await userEvent.click(within(history).getByRole('button', { name: 'Add a value' }))
    const form = within(history).getByRole('form', { name: 'New value' })
    await userEvent.type(within(form).getByRole('textbox', { name: 'Rank' }), '7')
    await setAbsolute(form, 'From', '100')
    await userEvent.click(within(form).getByRole('button', { name: 'Add' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'POST',
        path: '/entities/a1/facts',
        body: {
          field_key: 'rank',
          value: '7',
          timeline_id: 'd1-prime',
          valid_from: { anchor: { kind: 'absolute', t: '100' }, precision: 'base' },
          valid_to: null,
        },
      })
    })
    // [100, ∞) overlaps (…, 200): both rows say so.
    await waitFor(() => {
      expect(within(history).getAllByRole('note')).toHaveLength(2)
    })

    const [first] = within(history).getAllByRole('listitem', { name: 'Value over time' })
    if (first === undefined) throw new Error('no values listed')
    await userEvent.click(within(first).getByRole('button', { name: 'Delete this value' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({ method: 'DELETE', path: '/facts/f1' })
    })
    await waitFor(() => {
      expect(within(history).queryByRole('note')).toBeNull()
    })
  })

  it('edits the lifespan, and creates a death event anchoring its end', async () => {
    const writes = world([
      { id: 'f-life', entity_id: 'c1', field_key: 'core.exists', valid_from_t: '10' },
    ])
    await renderApp('/v/v1/e/c1')
    const lifespan = await screen.findByRole('region', { name: 'Lifespan' })
    expect(await within(lifespan).findByText('Born – Died')).toBeInTheDocument()

    await userEvent.click(within(lifespan).getByRole('button', { name: 'Create death event…' }))
    const shortcut = within(lifespan).getByRole('group', { name: 'New death event' })
    expect(shortcut).toHaveTextContent('Death of Aria')
    await userEvent.click(within(shortcut).getByRole('tab', { name: 'Absolute' }))
    await userEvent.type(within(shortcut).getByRole('textbox', { name: 'Moment (seconds)' }), '90')
    await userEvent.click(within(shortcut).getByRole('button', { name: 'Create death event' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'PATCH',
        path: '/facts/f-life',
        body: {
          valid_to: {
            anchor: { kind: 'relative', ref: { type: 'event', id: 'new1', slot: 'start' } },
          },
          source_event_id: 'new1',
        },
      })
    })
    expect(writes.at(-2)).toMatchObject({
      method: 'POST',
      path: '/entities',
      body: {
        kind: 'event',
        name: 'Death of Aria',
        ext: { start: { anchor: { kind: 'absolute', t: '90' } }, end: { kind: 'instant' } },
      },
    })
  })

  it('lists the changes an event caused', async () => {
    world([
      { id: 'f-crowned', entity_id: 'a1', field_key: 'rank', value: '9', source_event_id: 'e1' },
      { id: 'f-born', entity_id: 'c1', field_key: 'core.exists', source_event_id: 'e1' },
    ])
    await renderApp('/v/v1/e/e1')
    const section = await screen.findByRole('region', { name: 'Changes caused' })
    expect(await within(section).findByRole('link', { name: 'Crown' })).toBeInTheDocument()
    expect(within(section).getByText(/Rank:/)).toHaveTextContent('Rank: 9')
    expect(within(section).getByText('exists')).toBeInTheDocument()
  })

  it('gives a new link a validity period', async () => {
    const writes = world()
    await renderApp('/v/v1/e/a1')
    const relations = await screen.findByRole('region', { name: 'Relations' })
    await userEvent.click(within(relations).getByRole('button', { name: 'Add link' }))
    const dialog = await screen.findByRole('dialog', { name: 'Link Crown' })
    await userEvent.type(within(dialog).getByLabelText('Target'), 'Ge')
    await userEvent.click(await within(dialog).findByRole('button', { name: /Gem/ }))
    await setAbsolute(dialog, 'Until', '500')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add link' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'POST',
        path: '/links',
        body: { valid_to: { anchor: { kind: 'absolute', t: '500' } } },
      })
    })
  })
})
