import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { dimensionRow } from '@/test/calendars'
import {
  CAPS,
  defaultRows,
  kind,
  KINDS,
  linkType,
  row,
  serveVault,
  type LinkRow,
} from '@/test/fake-vault'
import { renderApp } from '@/test/render-app'

const WAIT = { timeout: 5000 }

const CHARACTER = kind('character', 'Character', {
  module: 'characters',
  icon: 'user',
  allowed_parents: ['misc'],
})
const EVENT = kind('event', 'Event', {
  allowed_parents: ['event'],
  capabilities: { ...CAPS, is_time_bound: true, has_existence: false },
})
const people = { module: 'characters', source_kinds: ['character'], target_kinds: ['character'] }
const LINK_TYPES = [
  linkType('core.related', 'related to', { symmetric: true }),
  linkType('core.participant', 'participant', {
    inverse_label: 'participates in',
    source_kinds: ['event'],
  }),
  linkType('characters.parent_of', 'parent of', { ...people, inverse_label: 'child of' }),
  linkType('characters.spouse_of', 'spouse of', { ...people, symmetric: true }),
  linkType('characters.rival_of', 'rival of', { ...people, symmetric: true }),
  linkType('characters.relationship', 'related to', people),
  linkType('locations.resides_in', 'resides in', { module: 'locations' }),
]

function world(extra: { links?: LinkRow[]; linkTypes?: ReturnType<typeof linkType>[] } = {}) {
  const at = (t: string) => ({ ext: { start_t: t, end_t: t } })
  return serveVault({
    modules: ['characters', 'locations'],
    kinds: [KINDS[0], KINDS[1], EVENT, CHARACTER, kind('location', 'Location')],
    linkTypes: extra.linkTypes ?? LINK_TYPES,
    rows: [
      ...defaultRows().filter((entity) => entity.id !== 'd1'),
      dimensionRow('d1', 'Aetheria', null),
      row('ilsa', 'character', 'Ilsa'),
      row('oren', 'character', 'Oren'),
      row('mara', 'character', 'Mara'),
      row('tam', 'character', 'Tam'),
      row('varn', 'location', 'Varn'),
      row('crown', 'event', 'Crowning', at('300')),
      row('birth', 'event', 'Birth of Ilsa', at('100')),
    ],
    links: extra.links ?? [
      {
        id: 'l1',
        link_type: 'characters.parent_of',
        source_id: 'mara',
        target_id: 'ilsa',
        data: { kind: 'adoptive' },
      },
      {
        id: 'l2',
        link_type: 'characters.spouse_of',
        source_id: 'oren',
        target_id: 'ilsa',
        data: { kind: 'marriage' },
      },
      { id: 'l3', link_type: 'characters.rival_of', source_id: 'ilsa', target_id: 'tam' },
      {
        id: 'l4',
        link_type: 'characters.relationship',
        source_id: 'ilsa',
        target_id: 'tam',
        role: 'godmother',
      },
      { id: 'l5', link_type: 'locations.resides_in', source_id: 'ilsa', target_id: 'varn' },
      {
        id: 'l6',
        link_type: 'core.participant',
        source_id: 'crown',
        target_id: 'ilsa',
        role: 'queen',
      },
      { id: 'l7', link_type: 'core.participant', source_id: 'birth', target_id: 'ilsa' },
    ],
  })
}

describe('characters module', () => {
  it('groups relationships by category with their kinds and roles', async () => {
    world()
    await renderApp('/v/v1/e/ilsa')
    const panel = await screen.findByRole('region', { name: 'Relationships' }, WAIT)
    const family = await within(panel).findByRole('list', { name: 'Family' }, WAIT)
    expect(
      within(family)
        .getAllByRole('listitem')
        .map((item) => item.textContent),
    ).toEqual(['child ofMara(adoptive)', 'spouse ofOren(married)'])
    expect(
      within(within(panel).getByRole('list', { name: 'Social' })).getByRole('listitem'),
    ).toHaveTextContent('rival ofTam')
    expect(
      within(within(panel).getByRole('list', { name: 'Other' })).getByRole('listitem'),
    ).toHaveTextContent('related toTam(godmother)')
  })

  it('adds a relationship through the link dialog', async () => {
    world()
    await renderApp('/v/v1/e/oren')
    const panel = await screen.findByRole('region', { name: 'Relationships' }, WAIT)
    await userEvent.click(within(panel).getByRole('button', { name: 'Add relationship' }))
    expect(await screen.findByRole('dialog', { name: 'Link Oren' })).toBeInTheDocument()
  })

  it('lists affiliations and the events of a life by time', async () => {
    world()
    await renderApp('/v/v1/e/ilsa')
    const affiliations = await screen.findByRole('region', { name: 'Affiliations' }, WAIT)
    expect(await within(affiliations).findByRole('link', { name: 'Varn' })).toBeVisible()
    expect(affiliations).toHaveTextContent('resides in')

    const life = screen.getByRole('region', { name: 'Life' })
    const events = await within(life).findByRole('list', { name: 'Life events' }, WAIT)
    expect(
      within(events)
        .getAllByRole('listitem')
        .map((item) => item.textContent),
    ).toEqual(['100 sBirth of Ilsa', '300 sCrowningas queen'])
  })

  it('says when there is nothing to show', async () => {
    world({ links: [], linkTypes: LINK_TYPES.filter((t) => t.module !== 'locations') })
    await renderApp('/v/v1/e/tam')
    const panel = await screen.findByRole('region', { name: 'Relationships' }, WAIT)
    expect(await within(panel).findByText('No relationships yet.')).toBeVisible()
    await waitFor(() => {
      expect(screen.getByRole('region', { name: 'Affiliations' })).toHaveTextContent(
        'No modules with affiliations are enabled.',
      )
    })
    expect(
      await within(screen.getByRole('region', { name: 'Life' })).findByText(
        'Takes part in no events on this timeline.',
      ),
    ).toBeVisible()
  })
})

describe('family tree', () => {
  /** Mara (adoptive) mother of Ilsa, married to Oren; their son Tam. */
  const FAMILY: LinkRow[] = [
    {
      id: 'l1',
      link_type: 'characters.parent_of',
      source_id: 'mara',
      target_id: 'ilsa',
      data: { kind: 'adoptive' },
    },
    { id: 'l2', link_type: 'characters.spouse_of', source_id: 'oren', target_id: 'ilsa' },
    { id: 'l3', link_type: 'characters.parent_of', source_id: 'ilsa', target_id: 'tam' },
    { id: 'l4', link_type: 'characters.parent_of', source_id: 'oren', target_id: 'tam' },
  ]
  const names = (scope: HTMLElement) =>
    within(scope)
      .getAllByTestId('family-person')
      .map((node) => node.getAttribute('title'))
      .sort()

  it('draws the family in the panel, with existence unknown, and re-centers in place', async () => {
    world({ links: FAMILY })
    await renderApp('/v/v1/e/ilsa')
    const panel = await screen.findByRole('region', { name: 'Family tree' }, WAIT)
    const figure = await within(panel).findByRole('figure', { name: 'Family tree' }, WAIT)
    await waitFor(() => {
      expect(names(figure)).toEqual(['Ilsa', 'Mara', 'Oren', 'Tam'])
    }, WAIT)
    const ilsa = within(figure)
      .getAllByTestId('family-person')
      .find((node) => node.getAttribute('title') === 'Ilsa')
    expect(ilsa).toHaveAttribute('data-existence', 'unknown')
    expect(ilsa).toHaveTextContent('Lifespan unknown')

    // A click on the son re-centers on him: one generation each way from Tam is his parents.
    await userEvent.selectOptions(within(panel).getByLabelText('Generations up'), '1')
    // A plain click: userEvent's mousedown reaches d3-zoom, which needs a window jsdom lacks.
    fireEvent.click(within(figure).getByTitle('Tam'))
    await waitFor(() => {
      expect(names(within(panel).getByRole('figure', { name: 'Family tree' }))).toEqual([
        'Ilsa',
        'Oren',
        'Tam',
      ])
    }, WAIT)
    expect(within(panel).getByRole('link', { name: 'Open the family tree view' })).toHaveAttribute(
      'href',
      '/v/v1/m/characters/tam/family-tree',
    )
    await userEvent.click(within(panel).getByRole('button', { name: 'Back to this character' }))
    await waitFor(() => {
      expect(names(within(panel).getByRole('figure', { name: 'Family tree' }))).toContain('Mara')
    }, WAIT)
  }, 20_000)

  it('shows the full view with depth controls and a list', async () => {
    world({ links: FAMILY })
    const { router } = await renderApp('/v/v1/m/characters/ilsa/family-tree')
    expect(await screen.findByRole('heading', { name: 'Family tree of Ilsa' }, WAIT)).toBeVisible()
    const figure = await screen.findByRole('figure', { name: 'Family tree' }, WAIT)
    await waitFor(() => {
      expect(names(figure)).toEqual(['Ilsa', 'Mara', 'Oren', 'Tam'])
    }, WAIT)
    await userEvent.selectOptions(screen.getByLabelText('Generations down'), '0')
    await userEvent.click(screen.getByRole('checkbox', { name: 'As a list' }))
    const up = await screen.findByRole('region', { name: '1 generation up' }, WAIT)
    expect(up).toHaveTextContent('Mara')
    const same = screen.getByRole('region', { name: 'Same generation' })
    expect(same).toHaveTextContent('Ilsa · child of Mara · spouse of Oren')
    expect(screen.queryByRole('region', { name: '1 generation down' })).toBeNull()

    // Opening a relative from the drawing goes to their page.
    await userEvent.click(screen.getByRole('checkbox', { name: 'As a list' }))
    // React Flow keeps nodes hidden until it has measured them (jsdom has no layout), and a
    // hidden button has no accessible name: find it by its label.
    fireEvent.click(await screen.findByLabelText('Open Mara', {}, WAIT))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/e/mara')
    })
  }, 20_000)
})
