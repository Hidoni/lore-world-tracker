import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { CanvasMarker } from '@/modules/maps/views/map-canvas'
import { CAPS, defaultRows, kind, KINDS, row, serveVault } from '@/test/fake-vault'
import { server } from '@/test/msw'
import { renderApp } from '@/test/render-app'

// jsdom draws no Leaflet maps: the canvas is replaced by a button per marker drawn.
vi.mock('@/modules/maps/views/map-canvas', () => ({
  default: ({
    markers,
    onSelect,
  }: {
    markers: CanvasMarker[]
    onSelect: (id: string | null) => void
  }) => (
    <ul aria-label="Drawn">
      {markers.map((marker) => (
        <li key={marker.id}>
          <button
            type="button"
            onClick={() => {
              onSelect(marker.id)
            }}
          >
            {marker.label}
            {marker.ghost ? ' (ghost)' : ''}
          </button>
        </li>
      ))}
    </ul>
  ),
}))

const WAIT = { timeout: 5000 }

beforeEach(() => {
  localStorage.clear()
})

const LOCATION = kind('location', 'Location', {
  module: 'locations',
  icon: 'map-pin',
  allowed_parents: ['location', 'misc'],
  capabilities: { ...CAPS, can_be_multiversal: true },
})

const SECOND = { singular: 'second', plural: 'seconds', abbr: 's' }

interface FakePin {
  id: string
  map_id: string
  target: string | null
  label?: string
  from?: string
  to?: string
}

/** Varn (a map) with Port inside (its own map); a camp from 100 until 200, a label. */
function world() {
  const names: Record<string, string> = { varn: 'Varn', port: 'Port', hero: 'Hero Sword' }
  const kinds: Record<string, string> = { varn: 'location', port: 'location', hero: 'artifact' }
  const maps = [
    { id: 'm-varn', location_id: 'varn', name: 'Varn', media_id: 'img1' },
    { id: 'm-port', location_id: 'port', name: 'Port', media_id: 'img2' },
  ].map((map) => ({
    ...map,
    description: '',
    width: 1000,
    height: 800,
    scale: null,
    sort_key: null,
    visibility: 'public',
    revision: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    deleted_at: null,
  }))
  const pins: FakePin[] = [
    { id: 'p-port', map_id: 'm-varn', target: 'port' },
    { id: 'p-hero', map_id: 'm-varn', target: 'hero' },
    { id: 'p-camp', map_id: 'm-varn', target: null, label: 'Camp', from: '100', to: '200' },
    { id: 'p-gate', map_id: 'm-port', target: null, label: 'Gate' },
  ]
  const pinOut = (pin: FakePin) => ({
    id: pin.id,
    map_id: pin.map_id,
    target:
      pin.target === null
        ? null
        : { id: pin.target, kind: kinds[pin.target], name: names[pin.target], icon: null, color: null },
    label: pin.label ?? null,
    display_label: pin.label ?? names[pin.target ?? ''],
    x: 100,
    y: 100,
    icon: null,
    color: null,
    child_map_id: null,
    drill_map_id: pin.target === 'port' ? 'm-port' : null,
    visibility: 'public',
    timeline_id: pin.from === undefined ? null : 'd1-prime',
    overrides_id: null,
    valid_from: null,
    valid_to: null,
    valid_from_t: pin.from ?? null,
    valid_to_t: pin.to ?? null,
    time_status: null,
    revision: 1,
    shown: 'certain',
  }) // prettier-ignore
  const queries: Record<string, string>[] = []
  serveVault({
    modules: ['locations', 'media', 'maps'],
    kinds: [KINDS[0], KINDS[1], LOCATION],
    rows: [
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
      row('varn', 'location', 'Varn'),
      row('port', 'location', 'Port', { parent_id: 'varn', summary: 'A busy harbor.' }),
      row('hero', 'artifact', 'Hero Sword'),
    ],
  })
  server.use(
    http.get('*/api/v1/vaults/v1/m/maps/maps', ({ request }) => {
      const location = new URL(request.url).searchParams.get('location')
      return HttpResponse.json({
        items: maps.filter((map) => location === null || map.location_id === location),
      })
    }),
    http.get('*/api/v1/vaults/v1/m/maps/maps/:id', ({ request, params }) => {
      const query = Object.fromEntries(new URL(request.url).searchParams)
      queries.push(query)
      const map = maps.find((item) => item.id === params.id)
      if (map === undefined) return new HttpResponse(null, { status: 404 })
      const at = query.at === undefined ? null : BigInt(query.at)
      const there = (pin: FakePin) =>
        at === null ||
        ((pin.from === undefined || BigInt(pin.from) <= at) &&
          (pin.to === undefined || at < BigInt(pin.to)))
      return HttpResponse.json({
        ...map,
        pins: pins.filter((pin) => pin.map_id === map.id && there(pin)).map(pinOut),
        breadcrumbs:
          map.id === 'm-port' ? [{ map_id: 'm-varn', name: 'Varn', location_id: 'varn' }] : [],
      })
    }),
    http.get('*/api/v1/vaults/v1/m/maps/entities/:id/pins', ({ params }) =>
      HttpResponse.json({
        entity_id: params.id,
        items: pins
          .filter((pin) => pin.target === params.id)
          .map((pin) => ({ pin: pinOut(pin), map: maps.find((map) => map.id === pin.map_id) })),
      }),
    ),
  )
  return { queries }
}

const drawn = async () => {
  const list = await screen.findByRole('list', { name: 'Drawn' }, WAIT)
  return within(list)
}
const drawnLabels = () =>
  within(screen.getByRole('list', { name: 'Drawn' }))
    .queryAllByRole('button')
    .map((button) => button.textContent)

describe('maps module', () => {
  it('shows a location its map, a pin its popover, and drills into nested maps', async () => {
    world()
    await renderApp('/v/v1/e/varn')
    const panel = await screen.findByRole('region', { name: 'Map' }, WAIT)
    const pins = await drawn()
    await userEvent.click(await pins.findByRole('button', { name: 'Port' }))
    const popover = within(panel).getByRole('dialog', { name: 'Port' })
    expect(await within(popover).findByText('A busy harbor.')).toBeInTheDocument()
    expect(within(popover).getByRole('link', { name: 'Open page' })).toHaveAttribute(
      'href',
      '/v/v1/e/port',
    )
    // Port's map isn't one of Varn's: the full-screen page opens with it.
    await userEvent.click(within(popover).getByRole('button', { name: 'Drill into map' }))
    const crumbs = () => screen.getByRole('navigation', { name: 'Map breadcrumbs' })
    await waitFor(() => {
      expect(within(crumbs()).getByText('Port')).toHaveAttribute('aria-current', 'page')
    }, WAIT)
    expect(await (await drawn()).findByRole('button', { name: 'Gate' })).toBeInTheDocument()
    await userEvent.click(within(crumbs()).getByRole('button', { name: 'Varn' }))
    expect(await (await drawn()).findByRole('button', { name: 'Port' }, WAIT)).toBeInTheDocument()
  })

  it('hides or ghosts pins that are not there at the time cursor, and toggles layers', async () => {
    const { queries } = world()
    await renderApp('/v/v1/m/maps/maps/m-varn?at=250')
    const pins = await drawn()
    await waitFor(() => {
      expect(queries).toContainEqual({ timeline: 'd1-prime', at: '250' })
    }, WAIT)
    await waitFor(() => {
      expect(drawnLabels()).toEqual(['Port', 'Hero Sword'])
    })

    await userEvent.click(screen.getByRole('checkbox', { name: "Ghost what isn't there" }))
    expect(await pins.findByRole('button', { name: 'Camp (ghost)' }, WAIT)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Camp (ghost)' }))
    expect(screen.getByRole('dialog', { name: 'Camp' })).toHaveTextContent(
      'Not there at the cursor.',
    )

    await userEvent.click(screen.getByRole('checkbox', { name: 'Labels' }))
    await waitFor(() => {
      expect(drawnLabels()).not.toContain('Camp (ghost)')
    })
    await userEvent.click(screen.getByRole('checkbox', { name: 'Artifacts' }))
    await waitFor(() => {
      expect(drawnLabels()).toEqual(['Port'])
    })
  })

  it('offers "Show on map" on pinned entities, opening the map at the pin', async () => {
    world()
    await renderApp('/v/v1/e/hero')
    const panel = await screen.findByRole('region', { name: 'Show on map' }, WAIT)
    await userEvent.click(within(panel).getByRole('link', { name: 'Show on map Varn' }))
    expect(await screen.findByRole('heading', { name: 'Varn', level: 1 }, WAIT)).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByRole('dialog', { name: 'Hero Sword' })).toBeInTheDocument()
    }, WAIT)
  })

  it('leaves the panel out on entities pinned nowhere', async () => {
    world()
    await renderApp('/v/v1/e/a1')
    await screen.findByRole('heading', { name: 'Crown', level: 1 }, WAIT)
    await waitFor(() => {
      expect(screen.queryByRole('region', { name: 'Show on map' })).not.toBeInTheDocument()
    })
  })
})
