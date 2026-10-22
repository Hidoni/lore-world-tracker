import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { CastleIcon, TagIcon } from 'lucide-react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import MapCanvas, { type CanvasMarker, type CanvasRegion } from './views/map-canvas'

const markers: CanvasMarker[] = [
  { id: 'p1', label: 'Port', x: 500, y: 400, icon: CastleIcon, color: '#b45309', ghost: false },
  { id: 'p2', label: 'Camp', x: 100, y: 700, icon: TagIcon, color: null, ghost: true },
]

// jsdom lays nothing out: the map gets a size so that Leaflet can fit the image.
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(500)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(400)
})
afterEach(() => {
  vi.restoreAllMocks()
})

describe('map canvas', () => {
  it('draws the image and a marker per pin (Leaflet in jsdom)', async () => {
    const onSelect = vi.fn()
    const { container } = render(
      <MapCanvas
        image="/map.png"
        width={1000}
        height={800}
        markers={markers}
        selected="p1"
        onSelect={onSelect}
      />,
    )
    expect(container.querySelector('img.leaflet-image-layer')).toHaveAttribute('src', '/map.png')
    const port = await screen.findByRole('button', { name: 'Port' })
    expect(port.querySelector('svg')).toHaveClass('lucide-castle')
    expect(port.querySelector('span')).toHaveClass('ring-2')
    expect(screen.getByRole('button', { name: 'Camp' }).querySelector('span')).toHaveClass(
      'opacity-40',
    )
    fireEvent.click(port)
    await waitFor(() => {
      expect(onSelect).toHaveBeenLastCalledWith('p1')
    })
    // The map's own click (not on a marker) clears the selection.
    const map = container.querySelector('.leaflet-container')
    if (map === null) throw new Error('no map')
    fireEvent.click(map)
    expect(onSelect).toHaveBeenLastCalledWith(null)
  })

  it('draws a large image as deep-zoom tiles over its small copy (#162)', async () => {
    const { container } = render(
      <MapCanvas
        image="/small.webp"
        tiles={{ url: '/tiles/{level}/{x}/{y}', levels: 2 }}
        width={1000}
        height={800}
        markers={[]}
        selected={null}
        onSelect={vi.fn()}
      />,
    )
    expect(container.querySelector('img.leaflet-image-layer')).toHaveAttribute('src', '/small.webp')
    // 1000 by 800 fitted into 500 by 400: zoom -1, the image shrunk twice, so level 1, whose
    // 500 by 400 pixels are 2 by 2 tiles (and none beyond the image).
    await waitFor(() => {
      expect(container.querySelectorAll('img.leaflet-tile')).toHaveLength(4)
    })
    const sources = [...container.querySelectorAll('img.leaflet-tile')].map((tile) =>
      tile.getAttribute('src'),
    )
    expect(sources.sort()).toEqual(['/tiles/1/0/0', '/tiles/1/0/1', '/tiles/1/1/0', '/tiles/1/1/1'])
  })

  it('draws regions under the pins, drags the selected one’s corners, adds corners while drawing', async () => {
    const regions: CanvasRegion[] = [
      { id: 'r1', label: 'Varn', points: [[0, 0], [100, 0], [100, 100]], color: '#0e7490', ghost: false },
      { id: 'r2', label: 'Wilds', points: [[200, 200], [300, 200], [300, 300]], color: null, ghost: true },
    ] // prettier-ignore
    const onSelect = vi.fn()
    const onDraw = vi.fn()
    const props = {
      image: '/map.png',
      width: 1000,
      height: 800,
      markers: [],
      regions,
      selected: 'r1',
      onSelect,
      editing: true,
      onDraw,
    }
    const { container, rerender } = render(<MapCanvas {...props} />)
    const shapes = container.querySelectorAll('path.lore-region')
    expect(shapes).toHaveLength(2)
    expect(shapes[0]).toHaveAttribute('stroke', '#0e7490')
    expect(shapes[1]).toHaveClass('lore-region-ghost')
    // Editing, the selected region's corners are handles.
    expect(await screen.findAllByRole('button', { name: /^Corner \d of Varn$/ })).toHaveLength(3)
    const wilds = shapes[1]
    if (wilds === undefined) throw new Error('no region')
    fireEvent.click(wilds)
    expect(onSelect).toHaveBeenLastCalledWith('r2')

    rerender(<MapCanvas {...props} drawing={[{ x: 1, y: 2 }]} />)
    expect(screen.queryAllByRole('button', { name: /^Corner/ })).toHaveLength(0)
    const map = container.querySelector('.leaflet-container')
    if (map === null) throw new Error('no map')
    fireEvent.click(map)
    expect(onDraw).toHaveBeenCalledOnce()
  })
})
