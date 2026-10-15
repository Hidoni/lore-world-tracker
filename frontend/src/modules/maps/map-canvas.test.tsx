import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { CastleIcon, TagIcon } from 'lucide-react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import MapCanvas, { type CanvasMarker } from './views/map-canvas'

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
      expect(onSelect).toHaveBeenCalledWith('p1')
    })
  })
})
