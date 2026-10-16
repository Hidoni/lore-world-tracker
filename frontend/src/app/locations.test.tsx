import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { AXE_TIMEOUT, expectAccessible } from '@/test/axe'
import { dimensionRow } from '@/test/calendars'
import { CAPS, defaultRows, FIELD, kind, KINDS, linkType, row, serveVault } from '@/test/fake-vault'
import { expectNoEditing, settled } from '@/test/reader'
import { renderApp } from '@/test/render-app'

const WAIT = { timeout: 5000 }

const TYPES = [
  ['galaxy', 'Galaxy'],
  ['city', 'City'],
  ['building', 'Building'],
  ['room', 'Room'],
]
const LOCATION = kind('location', 'Location', {
  module: 'locations',
  icon: 'map-pin',
  allowed_parents: ['location', 'misc'],
  capabilities: { ...CAPS, can_be_multiversal: true },
  fields: [
    {
      ...FIELD,
      key: 'location_type',
      label: 'Type',
      type: 'enum',
      options: TYPES.map(([key, label]) => ({ key, label, color: null })),
    },
  ],
})
const EVENT = kind('event', 'Event', {
  allowed_parents: ['event', 'misc'],
  capabilities: { ...CAPS, is_time_bound: true, has_existence: false },
})
const LINK_TYPES = [
  linkType('core.related', 'related to', { symmetric: true }),
  linkType('locations.event_site', 'took place at', {
    module: 'locations',
    inverse_label: 'site of',
    source_kinds: ['event'],
    target_kinds: ['location'],
  }),
  linkType('locations.resides_in', 'resides in', {
    module: 'locations',
    inverse_label: 'residents',
    target_kinds: ['location'],
  }),
  linkType('locations.connected_to', 'connected to', {
    module: 'locations',
    symmetric: true,
    source_kinds: ['location'],
    target_kinds: ['location'],
  }),
]

const moment = (t: string) => ({ ext: { start_t: t, end_t: t } })

/** Aetheria: Galaxy ⊃ Varn (city) ⊃ Spire, Harbor (buildings); events there; residents. */
function world() {
  return serveVault({
    modules: ['locations'],
    kinds: [KINDS[0], KINDS[1], EVENT, LOCATION],
    linkTypes: LINK_TYPES,
    rows: [
      ...defaultRows().filter((entity) => entity.id !== 'd1'),
      dimensionRow('d1', 'Aetheria', null),
      dimensionRow('d2', 'Umbra', null),
      row('gal', 'location', 'Galaxy', { fields: { location_type: 'galaxy' } }),
      row('varn', 'location', 'Varn', { parent_id: 'gal', fields: { location_type: 'city' } }),
      row('spire', 'location', 'Spire', {
        parent_id: 'varn',
        fields: { location_type: 'building' },
      }),
      row('harbor', 'location', 'Harbor', {
        parent_id: 'varn',
        fields: { location_type: 'building' },
      }),
      row('crypt', 'location', 'Crypt', { parent_id: 'varn' }),
      row('gate', 'location', 'Shadow Gate', { dimension_id: 'd2' }),
      row('founding', 'event', 'Founding', moment('100')),
      row('siege', 'event', 'Siege', moment('300')),
      row('storm', 'event', 'Storm', moment('200')),
      row('hero', 'artifact', 'Hero Sword'),
    ],
    links: [
      { id: 'l1', link_type: 'locations.event_site', source_id: 'founding', target_id: 'varn' },
      { id: 'l2', link_type: 'locations.event_site', source_id: 'siege', target_id: 'spire' },
      {
        id: 'l3',
        link_type: 'locations.resides_in',
        source_id: 'hero',
        target_id: 'varn',
        data: { kind: 'exile' },
      },
      {
        id: 'l4',
        link_type: 'locations.connected_to',
        source_id: 'spire',
        target_id: 'gate',
        data: { kind: 'portal' },
      },
    ],
  })
}

const sidebar = () => screen.getByRole('navigation', { name: 'Vault' })

describe('locations module', () => {
  it('shows the containment tree in the sidebar with type icons', async () => {
    world()
    await renderApp('/v/v1')
    const section = await within(sidebar()).findByRole('region', { name: 'Locations' })
    const galaxy = await within(section).findByRole('link', { name: 'Galaxy' }, WAIT)
    expect(galaxy.querySelector('svg')).toHaveClass('lucide-orbit')
    await userEvent.click(within(section).getByRole('button', { name: 'Expand Galaxy' }))
    const varn = await within(section).findByRole('link', { name: 'Varn' })
    expect(varn.querySelector('svg')).toHaveClass('lucide-building-2')
  })

  it('lists contents by type, events here, residents and connections', async () => {
    world()
    await renderApp('/v/v1/e/varn')
    const contents = await screen.findByRole('region', { name: 'Contents' }, WAIT)
    const groups = await within(contents).findAllByRole('region')
    expect(groups.map((group) => group.getAttribute('aria-label'))).toEqual([
      'Building',
      'Other places',
    ])
    const [buildings] = groups
    if (buildings === undefined) throw new Error('no groups')
    expect(
      within(buildings)
        .getAllByRole('link')
        .map((l) => l.textContent),
    ).toEqual(['Harbor', 'Spire'])

    const events = screen.getByRole('region', { name: 'Events here' })
    const list = await within(events).findByRole('list', { name: 'Events here' }, WAIT)
    expect(
      within(list)
        .getAllByRole('listitem')
        .map((item) => item.textContent),
    ).toEqual(['100 sFounding', '300 sSiege(inside)'])
    await userEvent.click(within(events).getByRole('checkbox', { name: 'Include places inside' }))
    await waitFor(() => {
      expect(within(events).getAllByRole('listitem')).toHaveLength(1)
    })

    const residents = screen.getByRole('region', { name: 'Residents' })
    expect(await within(residents).findByRole('link', { name: 'Hero Sword' })).toBeVisible()
    expect(residents).toHaveTextContent('in exile')
  })

  it('marks connections to other dimensions', async () => {
    world()
    await renderApp('/v/v1/e/spire')
    const connections = await screen.findByRole('region', { name: 'Connections' }, WAIT)
    expect(await within(connections).findByRole('link', { name: 'Shadow Gate' })).toBeVisible()
    expect(connections).toHaveTextContent('portal')
    expect(connections).toHaveTextContent('(another dimension)')
  })

  it('sets and replaces an event’s location from its page', async () => {
    const writes = world()
    await renderApp('/v/v1/e/storm')
    const field = await screen.findByRole('region', { name: 'Location' }, WAIT)
    expect(await within(field).findByText('Where it took place isn’t set.')).toBeVisible()
    await userEvent.click(within(field).getByRole('button', { name: 'Set location' }))
    await userEvent.type(within(field).getByRole('textbox', { name: 'Find a location' }), 'Ha')
    await userEvent.click(await within(field).findByRole('button', { name: 'Harbor' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'POST',
        path: '/links',
        body: { link_type: 'locations.event_site', source_id: 'storm', target_id: 'harbor' },
      })
    })
    expect(await within(field).findByRole('link', { name: 'Harbor' })).toBeVisible()

    // Choosing another location replaces it.
    await userEvent.click(within(field).getByRole('button', { name: 'Change location' }))
    await userEvent.type(within(field).getByRole('textbox', { name: 'Find a location' }), 'Sp')
    await userEvent.click(await within(field).findByRole('button', { name: 'Spire' }))
    await waitFor(() => {
      expect(writes.filter((write) => write.method === 'DELETE')).toHaveLength(1)
    })
    expect(await within(field).findByRole('link', { name: 'Spire' })).toBeVisible()
    expect(within(field).queryByRole('link', { name: 'Harbor' })).not.toBeInTheDocument()
  })

  it('has a location tree page with a type filter', async () => {
    world()
    await renderApp('/v/v1/m/locations/tree')
    const tree = await screen.findByRole('list', { name: 'Locations' }, WAIT)
    expect(within(tree).getByRole('link', { name: 'Spire' })).toBeVisible()
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Type' }), 'building')
    expect(
      within(screen.getByRole('list', { name: 'Locations' }))
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['Galaxy', 'Varn', 'Harbor', 'Spire'])
  })
})

describe('locations pages in reader mode', () => {
  it.each(['/v/v1', '/v/v1/e/varn', '/v/v1/e/storm', '/v/v1/m/locations/tree'])(
    '%s offers no editing',
    async (path) => {
      world()
      await renderApp(path, undefined, { readOnly: true })
      await settled()
      expectNoEditing()
      await expectAccessible()
    },
    AXE_TIMEOUT,
  )
})

describe('locations pages for the author', () => {
  it.each(['/v/v1', '/v/v1/e/varn', '/v/v1/e/storm', '/v/v1/m/locations/tree'])(
    '%s is accessible',
    async (path) => {
      world()
      await renderApp(path)
      await settled()
      await expectAccessible()
    },
    AXE_TIMEOUT,
  )
})
