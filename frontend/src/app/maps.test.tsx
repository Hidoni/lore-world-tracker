import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { CanvasMarker, CanvasRegion, Point } from '@/modules/maps/views/map-canvas'
import { AXE_TIMEOUT, expectAccessible } from '@/test/axe'
import { CAPS, defaultRows, kind, KINDS, row, serveVault } from '@/test/fake-vault'
import { server } from '@/test/msw'
import { expectNoEditing, settled } from '@/test/reader'
import { renderApp } from '@/test/render-app'

// jsdom draws no Leaflet maps: the canvas is replaced by a button per marker and region drawn,
// and (editing) buttons that click the map at (100, 200), drag a marker to (5, 6), drop Fort at
// (300, 400), drag a region's first corner to (1, 2), and (drawing) add a corner.
vi.mock('@/modules/maps/views/map-canvas', () => ({
  ENTITY_DRAG_TYPE: 'application/x-lore-entity',
  default: ({
    markers,
    regions = [],
    onSelect,
    editing = false,
    onPlace,
    onMove,
    onDropEntity,
    drawing = null,
    onDraw,
    onReshape,
  }: {
    markers: CanvasMarker[]
    regions?: CanvasRegion[]
    onSelect: (id: string | null) => void
    editing?: boolean
    onPlace?: (point: Point) => void
    onMove?: (id: string, point: Point) => void
    onDropEntity?: (entity: string, point: Point) => void
    drawing?: Point[] | null
    onDraw?: (point: Point) => void
    onReshape?: (id: string, points: Point[]) => void
  }) => (
    <>
      {drawing !== null && (
        <button type="button" onClick={() => onDraw?.({ x: drawing.length, y: 10 })}>
          Add a corner
        </button>
      )}
      {editing &&
        regions.map((region) => (
          <button
            key={region.id}
            type="button"
            onClick={() =>
              onReshape?.(region.id, [
                { x: 1, y: 2 },
                ...region.points.slice(1).map(([x = 0, y = 0]) => ({ x, y })),
              ])
            }
          >
            Reshape {region.label}
          </button>
        ))}
      <ul aria-label="Drawn regions">
        {regions.map((region) => (
          <li key={region.id}>
            <button
              type="button"
              style={{ color: region.color ?? undefined }}
              onClick={() => {
                onSelect(region.id)
              }}
            >
              {region.label}
              {region.ghost ? ' (ghost)' : ''}
            </button>
          </li>
        ))}
      </ul>
      {editing && (
        <div>
          <button type="button" onClick={() => onPlace?.({ x: 100, y: 200 })}>
            Click the map
          </button>
          <button type="button" onClick={() => onDropEntity?.('fort', { x: 300, y: 400 })}>
            Drop Fort
          </button>
          {markers.map((marker) => (
            <button
              key={marker.id}
              type="button"
              onClick={() => onMove?.(marker.id, { x: 5, y: 6 })}
            >
              Drag {marker.label}
            </button>
          ))}
        </div>
      )}
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
    </>
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
  const names: Record<string, string> = {
    varn: 'Varn',
    port: 'Port',
    hero: 'Hero Sword',
    fort: 'Fort',
  }
  const kinds: Record<string, string> = {
    varn: 'location',
    port: 'location',
    hero: 'artifact',
    fort: 'location',
  }
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
  let pins: FakePin[] = [
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
  interface FakeRegion {
    id: string
    target: string | null
    label?: string
    from?: string
  }
  let regions: FakeRegion[] = [
    { id: 'r-port', target: 'port' },
    { id: 'r-wilds', target: null, label: 'The Wilds', from: '300' },
  ]
  const regionOut = (region: FakeRegion) => ({
    id: region.id,
    map_id: 'm-varn',
    target:
      region.target === null
        ? null
        : { id: region.target, kind: kinds[region.target], name: names[region.target], icon: null, color: null },
    label: region.label ?? null,
    display_label: region.label ?? names[region.target ?? ''],
    points: [[0, 0], [10, 0], [10, 10]],
    color: null,
    controllers:
      region.target === 'port'
        ? [{ id: 'guild', kind: 'organization', name: 'Harbor Guild', color: '#0e7490' }]
        : [],
    visibility: 'public',
    timeline_id: region.from === undefined ? null : 'd1-prime',
    overrides_id: null,
    valid_from: null,
    valid_to: null,
    valid_from_t: region.from ?? null,
    valid_to_t: null,
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
      row('fort', 'location', 'Fort', { parent_id: 'varn' }),
    ],
  })
  const writes: { method: string; path: string; body: unknown }[] = []
  const affected = { entities: [], dimensions: [], time_changed: false, search_changed: false }
  let seq = 0
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
        regions:
          map.id === 'm-varn'
            ? regions
                .filter(
                  (region) => at === null || region.from === undefined || BigInt(region.from) <= at,
                )
                .map(regionOut)
            : [],
        breadcrumbs:
          map.id === 'm-port' ? [{ map_id: 'm-varn', name: 'Varn', location_id: 'varn' }] : [],
      })
    }),
    http.post('*/api/v1/vaults/v1/m/maps/maps/:id/pins', async ({ request, params }) => {
      const body = (await request.json()) as {
        target_entity_id?: string
        label?: string
      }
      writes.push({ method: 'POST', path: `/maps/${String(params.id)}/pins`, body })
      seq += 1
      const pin: FakePin = {
        id: `new${String(seq)}`,
        map_id: String(params.id),
        target: body.target_entity_id ?? null,
        ...(body.label === undefined ? {} : { label: body.label }),
      }
      pins = [...pins, pin]
      return HttpResponse.json({ pin: pinOut(pin), affected }, { status: 201 })
    }),
    http.patch('*/api/v1/vaults/v1/m/maps/pins/:id', async ({ request, params }) => {
      const body = (await request.json()) as { label?: string | null }
      writes.push({ method: 'PATCH', path: `/pins/${String(params.id)}`, body })
      pins = pins.map((pin) =>
        pin.id === params.id && typeof body.label === 'string'
          ? { ...pin, label: body.label }
          : pin,
      )
      const pin = pins.find((other) => other.id === params.id)
      return pin
        ? HttpResponse.json({ pin: pinOut(pin), affected })
        : new HttpResponse(null, { status: 404 })
    }),
    http.delete('*/api/v1/vaults/v1/m/maps/pins/:id', ({ params }) => {
      writes.push({ method: 'DELETE', path: `/pins/${String(params.id)}`, body: null })
      const pin = pins.find((other) => other.id === params.id)
      pins = pins.filter((other) => other.id !== params.id)
      return pin
        ? HttpResponse.json({ pin: pinOut(pin), affected })
        : new HttpResponse(null, { status: 404 })
    }),
    http.post('*/api/v1/vaults/v1/m/maps/maps/:id/regions', async ({ request, params }) => {
      const body = (await request.json()) as { target_entity_id?: string; label?: string }
      writes.push({ method: 'POST', path: `/maps/${String(params.id)}/regions`, body })
      seq += 1
      const region: FakeRegion = {
        id: `region${String(seq)}`,
        target: body.target_entity_id ?? null,
        ...(body.label === undefined ? {} : { label: body.label }),
      }
      regions = [...regions, region]
      return HttpResponse.json({ region: regionOut(region), affected }, { status: 201 })
    }),
    http.patch('*/api/v1/vaults/v1/m/maps/regions/:id', async ({ request, params }) => {
      const body = (await request.json()) as { label?: string | null }
      writes.push({ method: 'PATCH', path: `/regions/${String(params.id)}`, body })
      regions = regions.map((region) =>
        region.id === params.id && typeof body.label === 'string'
          ? { ...region, label: body.label }
          : region,
      )
      const region = regions.find((other) => other.id === params.id)
      return region
        ? HttpResponse.json({ region: regionOut(region), affected })
        : new HttpResponse(null, { status: 404 })
    }),
    http.delete('*/api/v1/vaults/v1/m/maps/regions/:id', ({ params }) => {
      writes.push({ method: 'DELETE', path: `/regions/${String(params.id)}`, body: null })
      const region = regions.find((other) => other.id === params.id)
      regions = regions.filter((other) => other.id !== params.id)
      return region
        ? HttpResponse.json({ region: regionOut(region), affected })
        : new HttpResponse(null, { status: 404 })
    }),
    http.post('*/api/v1/vaults/v1/m/maps/maps', async ({ request }) => {
      const body = (await request.json()) as { location_id: string; media_id: string; name: string }
      writes.push({ method: 'POST', path: '/maps', body })
      const [template] = maps
      if (template === undefined) return new HttpResponse(null, { status: 500 })
      const map = { ...template, ...body, id: 'm-new' }
      maps.push(map)
      return HttpResponse.json({ map, affected }, { status: 201 })
    }),
    http.get(
      '*/api/v1/vaults/v1/m/media/items',
      () =>
      HttpResponse.json({
        items: [
          {
            id: 'img9', sha256: 'abcdef', filename: 'fort.png', mime: 'image/png', size: 10,
            width: 640, height: 480, alt: '', caption: '', revision: 1,
            created_at: '2026-01-01T00:00:00Z', deleted_at: null, refs: [],
          },
        ],
        next_cursor: null,
      }), // prettier-ignore
    ),
    http.get('*/api/v1/vaults/v1/m/maps/entities/:id/pins', ({ params }) =>
      HttpResponse.json({
        entity_id: params.id,
        items: pins
          .filter((pin) => pin.target === params.id)
          .map((pin) => ({ pin: pinOut(pin), map: maps.find((map) => map.id === pin.map_id) })),
      }),
    ),
  )
  return { queries, writes }
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

  it('shows the map as a list: the same pins, their pages and the maps they drill into', async () => {
    world()
    await renderApp('/v/v1/m/maps/maps/m-varn?at=250')
    await drawn()
    await userEvent.click(screen.getByRole('checkbox', { name: 'As a list' }))
    const list = await screen.findByRole('list', { name: 'Pins' }, WAIT)
    await waitFor(() => {
      expect(
        within(list)
          .getAllByRole('listitem')
          .map((item) => item.textContent),
      ).toEqual([expect.stringContaining('Hero Sword'), expect.stringContaining('Port')])
    }, WAIT)
    expect(within(list).getByRole('link', { name: 'Port' })).toHaveAttribute('href', '/v/v1/e/port')
    // With ghosts, a pin not there at the cursor says so.
    await userEvent.click(screen.getByRole('checkbox', { name: "Ghost what isn't there" }))
    expect(await within(list).findByText('not there at the cursor', {}, WAIT)).toBeInTheDocument()
    await userEvent.click(within(list).getByRole('button', { name: 'Drill into map' }))
    const crumbs = () => screen.getByRole('navigation', { name: 'Map breadcrumbs' })
    await waitFor(() => {
      expect(within(crumbs()).getByText('Port')).toHaveAttribute('aria-current', 'page')
    }, WAIT)
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

  it('adds pins by clicking (an entity or a label), moves them by dragging', async () => {
    const { writes } = world()
    await renderApp('/v/v1/m/maps/maps/m-varn')
    await userEvent.click(await screen.findByRole('button', { name: 'Edit map' }, WAIT))
    await userEvent.click(await screen.findByRole('button', { name: 'Click the map' }, WAIT))
    let dialog = await screen.findByRole('dialog', { name: 'Add a pin' })
    await userEvent.type(within(dialog).getByRole('searchbox', { name: 'Find an entity' }), 'Hero')
    await userEvent.click(await within(dialog).findByRole('button', { name: /Hero Sword/ }, WAIT))
    await waitFor(() => {
      expect(writes).toContainEqual({
        method: 'POST',
        path: '/maps/m-varn/pins',
        body: { target_entity_id: 'hero', x: 100, y: 200 },
      })
    })
    await userEvent.click(screen.getByRole('button', { name: 'Click the map' }))
    dialog = await screen.findByRole('dialog', { name: 'Add a pin' })
    await userEvent.type(within(dialog).getByRole('searchbox', { name: 'Find an entity' }), 'Ruins')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add the label “Ruins”' }))
    await waitFor(() => {
      expect(writes).toContainEqual({
        method: 'POST',
        path: '/maps/m-varn/pins',
        body: { label: 'Ruins', x: 100, y: 200 },
      })
    })
    expect(await screen.findByRole('button', { name: 'Ruins' }, WAIT)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Drag Port' }))
    await waitFor(() => {
      expect(writes).toContainEqual({
        method: 'PATCH',
        path: '/pins/p-port',
        body: { revision: 1, x: 5, y: 6 },
      })
    })
  })

  it('pins unplaced child locations from the tray, by button or by dropping', async () => {
    const { writes } = world()
    await renderApp('/v/v1/m/maps/maps/m-varn')
    await userEvent.click(await screen.findByRole('button', { name: 'Edit map' }, WAIT))
    const tray = await screen.findByRole('region', { name: 'Unplaced child locations' })
    // Port is pinned already.
    expect(await within(tray).findByText('Fort', {}, WAIT)).toBeInTheDocument()
    expect(within(tray).queryByText('Port')).toBeNull()
    await userEvent.click(within(tray).getByRole('button', { name: 'Place Fort on the map' }))
    await waitFor(() => {
      expect(writes).toContainEqual({
        method: 'POST',
        path: '/maps/m-varn/pins',
        body: { target_entity_id: 'fort', x: 500, y: 400 },
      })
    })
    await waitFor(() => {
      expect(within(tray).getByText('Every child location is on this map.')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: 'Drop Fort' }))
    await waitFor(() => {
      expect(writes.filter((write) => write.method === 'POST')).toHaveLength(2)
    })
  })

  it('edits and removes a pin', async () => {
    const { writes } = world()
    await renderApp('/v/v1/m/maps/maps/m-varn')
    await userEvent.click(await screen.findByRole('button', { name: 'Edit map' }, WAIT))
    // Editing shows every pin, the camp too.
    await userEvent.click(await screen.findByRole('button', { name: 'Camp' }, WAIT))
    const editor = screen.getByRole('dialog', { name: 'Edit Camp' })
    const label = within(editor).getByLabelText('Label')
    await userEvent.clear(label)
    await userEvent.type(label, 'Old camp')
    await userEvent.selectOptions(within(editor).getByLabelText('Visibility'), 'private')
    await userEvent.selectOptions(within(editor).getByLabelText('Drills into'), 'm-port')
    await userEvent.click(within(editor).getByRole('button', { name: 'Save' }))
    await waitFor(() => {
      expect(writes).toContainEqual({
        method: 'PATCH',
        path: '/pins/p-camp',
        body: { revision: 1, label: 'Old camp', child_map_id: 'm-port', visibility: 'private' },
      })
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Old camp' }, WAIT))
    await userEvent.click(
      within(screen.getByRole('dialog', { name: 'Edit Old camp' })).getByRole('button', {
        name: 'Remove pin',
      }),
    )
    await waitFor(() => {
      expect(writes).toContainEqual({ method: 'DELETE', path: '/pins/p-camp', body: null })
    })
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Old camp' })).toBeNull()
    })
  })

  it('creates a map for a location with an image from the library', async () => {
    const { writes } = world()
    await renderApp('/v/v1/e/fort')
    const panel = await screen.findByRole('region', { name: 'Map' }, WAIT)
    expect(await within(panel).findByText('No maps of this place.', {}, WAIT)).toBeInTheDocument()
    await userEvent.click(within(panel).getByRole('button', { name: 'New map' }))
    const dialog = await screen.findByRole('dialog', { name: 'New map' })
    expect(within(dialog).getByLabelText('Name')).toHaveValue('Fort')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Choose the image' }))
    const picker = await screen.findByRole('dialog', { name: "The map's image" })
    await userEvent.click(
      await within(picker).findByRole('button', { name: 'Pick fort.png' }, WAIT),
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Create the map' }, WAIT))
    await waitFor(() => {
      expect(writes).toContainEqual({
        method: 'POST',
        path: '/maps',
        body: { location_id: 'fort', media_id: 'img9', name: 'Fort' },
      })
    })
    // The dialog closes on the new map.
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'New map' })).toBeNull()
    })
    expect(await within(panel).findByRole('link', { name: 'Full screen' }, WAIT)).toBeVisible()
  })
  it('draws regions in their controller’s color, says who controls them, follows the cursor', async () => {
    world()
    await renderApp('/v/v1/m/maps/maps/m-varn?at=250')
    const regions = () => within(screen.getByRole('list', { name: 'Drawn regions' }))
    await screen.findByRole('list', { name: 'Drawn regions' }, WAIT)
    // The Wilds start at 300.
    await waitFor(() => {
      expect(
        regions()
          .queryAllByRole('button')
          .map((button) => button.textContent),
      ).toEqual(['Port'])
    }, WAIT)
    const port = regions().getByRole('button', { name: 'Port' })
    expect(port).toHaveStyle({ color: '#0e7490' })
    await userEvent.click(port)
    const popover = await screen.findByRole('dialog', { name: 'Port' }, WAIT)
    expect(popover).toHaveTextContent('Controlled by Harbor Guild')
    expect(within(popover).getByRole('link', { name: 'Harbor Guild' })).toHaveAttribute(
      'href',
      '/v/v1/e/guild',
    )
    await userEvent.click(screen.getByRole('checkbox', { name: "Ghost what isn't there" }))
    expect(
      await within(screen.getByRole('list', { name: 'Drawn regions' })).findByRole(
        'button',
        { name: 'The Wilds (ghost)' },
        WAIT,
      ),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('checkbox', { name: 'As a list' }))
    const list = await screen.findByRole('list', { name: 'Regions' }, WAIT)
    expect(list).toHaveTextContent('Controlled by Harbor Guild')
    expect(list).toHaveTextContent('not there at the cursor')
    await userEvent.click(screen.getByRole('checkbox', { name: 'As a list' }))
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Regions' }, WAIT))
    await waitFor(() => {
      expect(screen.getByRole('list', { name: 'Drawn regions' })).toBeEmptyDOMElement()
    })
  }, 20_000)

  it('draws, reshapes, edits and removes regions', async () => {
    const { writes } = world()
    await renderApp('/v/v1/m/maps/maps/m-varn')
    await userEvent.click(await screen.findByRole('button', { name: 'Edit map' }, WAIT))
    await userEvent.click(await screen.findByRole('button', { name: 'Draw region' }, WAIT))
    const finish = screen.getByRole('button', { name: 'Finish region' })
    expect(finish).toBeDisabled()
    for (let corner = 0; corner < 3; corner += 1)
      await userEvent.click(screen.getByRole('button', { name: 'Add a corner' }))
    expect(screen.getByText(/3 so far/)).toBeInTheDocument()
    await userEvent.click(finish)
    const dialog = await screen.findByRole('dialog', { name: 'Add a region' })
    await userEvent.type(within(dialog).getByRole('searchbox', { name: 'Find an entity' }), 'Marsh')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add the label “Marsh”' }))
    await waitFor(() => {
      expect(writes).toContainEqual({
        method: 'POST',
        path: '/maps/m-varn/regions',
        body: { label: 'Marsh', points: [[0, 10], [1, 10], [2, 10]] },
      }) // prettier-ignore
    })
    // The new region opens in the editor.
    expect(await screen.findByRole('dialog', { name: 'Edit Marsh' }, WAIT)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Reshape Port' }))
    await waitFor(() => {
      expect(writes).toContainEqual({
        method: 'PATCH',
        path: '/regions/r-port',
        body: { revision: 1, points: [[1, 2], [10, 0], [10, 10]] },
      }) // prettier-ignore
    })

    const regions = within(screen.getByRole('list', { name: 'Drawn regions' }))
    await userEvent.click(regions.getByRole('button', { name: 'The Wilds' }))
    const editor = screen.getByRole('dialog', { name: 'Edit The Wilds' })
    const label = within(editor).getByLabelText('Label')
    await userEvent.clear(label)
    await userEvent.type(label, 'Old wilds')
    await userEvent.selectOptions(within(editor).getByLabelText('Visibility'), 'spoiler')
    await userEvent.click(within(editor).getByRole('button', { name: 'Save' }))
    await waitFor(() => {
      expect(writes).toContainEqual({
        method: 'PATCH',
        path: '/regions/r-wilds',
        body: { revision: 1, label: 'Old wilds', visibility: 'spoiler' },
      })
    })
    await userEvent.click(await regions.findByRole('button', { name: 'Old wilds' }, WAIT))
    await userEvent.click(
      within(screen.getByRole('dialog', { name: 'Edit Old wilds' })).getByRole('button', {
        name: 'Remove region',
      }),
    )
    await waitFor(() => {
      expect(writes).toContainEqual({ method: 'DELETE', path: '/regions/r-wilds', body: null })
    })
  }, 20_000)
})

describe('maps pages in reader mode', () => {
  it.each(['/v/v1/e/varn', '/v/v1/m/maps/maps/m-varn'])(
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

describe('maps pages for the author', () => {
  it.each(['/v/v1/e/varn', '/v/v1/m/maps/maps/m-varn'])(
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
