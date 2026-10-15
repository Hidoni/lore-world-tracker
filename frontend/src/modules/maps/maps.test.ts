import { describe, expect, it } from 'vitest'

import type { MapPin } from '@/data'

import { layersOf, pinsToShow, toLatLng } from './pins'

const pin = (id: string, kind: string | null, shown: 'certain' | 'possible' = 'certain') =>
  ({
    id,
    target: kind === null ? null : { id: `e-${id}`, kind, name: id, icon: null, color: null },
    shown,
    x: 10,
    y: 30,
  }) as MapPin

describe('map pins', () => {
  const camp = pin('camp', null)
  const fort = pin('fort', 'location')
  const hero = pin('hero', 'character')

  it('groups pins in layers by kind, labels last', () => {
    expect(layersOf([camp, hero, fort])).toEqual(['character', 'location', 'label'])
  })

  it('shows every pin without a cursor', () => {
    expect(pinsToShow([camp, fort], null, 'hide')).toEqual([
      { pin: camp, ghost: false },
      { pin: fort, ghost: false },
    ])
  })

  it('hides or ghosts pins not there at the cursor, fading possible ones', () => {
    const maybe = pin('fort', 'location', 'possible')
    expect(pinsToShow([camp, fort, hero], [maybe, hero], 'hide')).toEqual([
      { pin: maybe, ghost: true },
      { pin: hero, ghost: false },
    ])
    expect(pinsToShow([camp, fort, hero], [maybe, hero], 'ghost')).toEqual([
      { pin: camp, ghost: true },
      { pin: maybe, ghost: true },
      { pin: hero, ghost: false },
    ])
  })

  it('leaves hidden layers out', () => {
    const hidden = new Set(['label', 'character'])
    expect(pinsToShow([camp, fort, hero], [fort], 'ghost', hidden)).toEqual([
      { pin: fort, ghost: false },
    ])
  })

  it('turns image pixels into simple-CRS coordinates', () => {
    expect(toLatLng(fort, 800)).toEqual([770, 10])
  })
})
