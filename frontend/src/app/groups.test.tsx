import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { AXE_TIMEOUT, expectAccessible } from '@/test/axe'
import { calendarRow, dimensionRow } from '@/test/calendars'
import { defaultRows, kind, KINDS, linkType, row, serveVault } from '@/test/fake-vault'
import { expectNoEditing, settled } from '@/test/reader'
import { renderApp } from '@/test/render-app'

const WAIT = { timeout: 5000 }

const GROUP = kind('group', 'Group', {
  module: 'groups',
  icon: 'users',
  allowed_parents: ['group', 'misc'],
})
const groups = { module: 'groups', source_kinds: ['group'], target_kinds: ['group'] }
const LINK_TYPES = [
  linkType('core.related', 'related to', { symmetric: true }),
  linkType('groups.member_of', 'member of', { module: 'groups', inverse_label: 'members' }),
  linkType('groups.led_by', 'led by', { module: 'groups', inverse_label: 'leads' }),
  linkType('groups.part_of', 'part of', { ...groups, inverse_label: 'has part' }),
  linkType('groups.allied_with', 'allied with', { ...groups, symmetric: true }),
  linkType('groups.at_war_with', 'at war with', { ...groups, symmetric: true }),
  linkType('groups.vassal_of', 'vassal of', { ...groups, inverse_label: 'overlord of' }),
  linkType('groups.controls', 'controls', { module: 'groups', inverse_label: 'controlled by' }),
]

function world() {
  return serveVault({
    modules: ['groups'],
    kinds: [
      KINDS[0],
      KINDS[1],
      GROUP,
      kind('character', 'Character'),
      kind('location', 'Location'),
    ],
    linkTypes: LINK_TYPES,
    rows: [
      ...defaultRows(),
      row('empire', 'group', 'Empire'),
      row('ministry', 'group', 'Ministry of Tides', { parent_id: 'empire' }),
      row('guard', 'group', 'Harbor Guard'),
      row('rebels', 'group', 'Rebels'),
      row('ilsa', 'character', 'Ilsa'),
      row('oren', 'character', 'Oren'),
      row('varn', 'location', 'Varn'),
    ],
    links: [
      {
        id: 'm1',
        link_type: 'groups.member_of',
        source_id: 'ilsa',
        target_id: 'empire',
        data: { rank: 'Empress', is_leader: true },
      },
      {
        id: 'm2',
        link_type: 'groups.member_of',
        source_id: 'oren',
        target_id: 'ministry',
        data: { title: 'Minister' },
      },
      { id: 'l1', link_type: 'groups.led_by', source_id: 'empire', target_id: 'ilsa' },
      { id: 'p1', link_type: 'groups.part_of', source_id: 'guard', target_id: 'empire' },
      { id: 'w1', link_type: 'groups.at_war_with', source_id: 'empire', target_id: 'rebels' },
      { id: 'c1', link_type: 'groups.controls', source_id: 'empire', target_id: 'varn' },
    ],
  })
}

describe('groups module', () => {
  it('lists members with ranks, and those of sub-groups on request', async () => {
    world()
    await renderApp('/v/v1/e/empire')
    const panel = await screen.findByRole('region', { name: 'Members' }, WAIT)
    const list = await within(panel).findByRole('list', { name: 'Members' }, WAIT)
    expect(
      within(list)
        .getAllByRole('listitem')
        .map((item) => item.textContent),
    ).toEqual(['Ilsa(Empress, leader)'])
    await userEvent.click(within(panel).getByRole('checkbox', { name: 'Include sub-groups' }))
    await waitFor(() => {
      expect(
        within(within(panel).getByRole('list', { name: 'Members' }))
          .getAllByRole('listitem')
          .map((item) => item.textContent),
      ).toEqual(['Ilsa(Empress, leader)', 'Oren(Minister)in Ministry of Tides'])
    })
  })

  it('shows the structure, leadership, relations and territory', async () => {
    world()
    await renderApp('/v/v1/e/empire')
    const structure = await screen.findByRole('region', { name: 'Structure' }, WAIT)
    expect(
      await within(structure).findByRole('link', { name: 'Ministry of Tides' }, WAIT),
    ).toBeVisible()
    expect(within(structure).getByRole('list', { name: 'Parts' })).toHaveTextContent(
      'has partHarbor Guard',
    )
    const leadership = screen.getByRole('region', { name: 'Leadership' })
    expect(await within(leadership).findByRole('link', { name: 'Ilsa' })).toBeVisible()
    const relations = screen.getByRole('region', { name: 'Group relations' })
    expect(await within(relations).findByRole('listitem')).toHaveTextContent('at war withRebels')
    const territory = screen.getByRole('region', { name: 'Territory' })
    expect(await within(territory).findByRole('link', { name: 'Varn' })).toBeVisible()
  })

  it('says when a group has nobody', async () => {
    world()
    await renderApp('/v/v1/e/rebels')
    const panel = await screen.findByRole('region', { name: 'Members' }, WAIT)
    expect(await within(panel).findByText('No members.')).toBeVisible()
    expect(
      await within(screen.getByRole('region', { name: 'Leadership' })).findByText('No leaders.'),
    ).toBeVisible()
  })
})

describe('membership history and org chart', () => {
  // Aetheria (Gregorian) holds the empire; Ilsa was a member from 100 to 250 days, Oren is
  // undated.
  const DAY = 86_400n
  function dated() {
    return serveVault({
      modules: ['groups'],
      kinds: [...KINDS, GROUP, kind('character', 'Character'), kind('calendar', 'Calendar')],
      linkTypes: LINK_TYPES,
      rows: [
        ...defaultRows().filter((entity) => entity.id !== 'd1'),
        dimensionRow('d1', 'Aetheria', 'c-greg'),
        calendarRow('c-greg', 'Gregorian', 'gregorian'),
        row('empire', 'group', 'Empire', { dimension_id: 'd1' }),
        row('ministry', 'group', 'Ministry of Tides', { parent_id: 'empire', dimension_id: 'd1' }),
        row('office', 'group', 'Harbor Office', { parent_id: 'ministry', dimension_id: 'd1' }),
        row('guard', 'group', 'Harbor Guard', { dimension_id: 'd1' }),
        row('ilsa', 'character', 'Ilsa'),
        row('oren', 'character', 'Oren'),
      ],
      links: [
        {
          id: 'm1',
          link_type: 'groups.member_of',
          source_id: 'ilsa',
          target_id: 'empire',
          valid_from_t: (100n * DAY).toString(),
          valid_to_t: (250n * DAY).toString(),
        },
        { id: 'm2', link_type: 'groups.member_of', source_id: 'oren', target_id: 'empire' },
        { id: 'm3', link_type: 'groups.member_of', source_id: 'oren', target_id: 'ministry' },
        {
          id: 'l1',
          link_type: 'groups.led_by',
          source_id: 'empire',
          target_id: 'ilsa',
          data: { title: 'Empress' },
        },
        { id: 'p1', link_type: 'groups.part_of', source_id: 'guard', target_id: 'empire' },
      ],
    })
  }

  it('draws memberships as bars on the display calendar’s axis', async () => {
    dated()
    await renderApp('/v/v1/e/empire?cal=c-greg')
    const panel = await screen.findByRole('region', { name: 'Members' }, WAIT)
    await within(panel).findByRole('list', { name: 'Members' }, WAIT)
    await userEvent.click(within(panel).getByRole('checkbox', { name: 'History' }))
    const history = await within(panel).findByRole('list', { name: 'Membership history' }, WAIT)
    const rows = within(history).getAllByTestId('gantt-row')
    expect(rows.map((item) => within(item).getByRole('link').textContent)).toEqual(['Ilsa', 'Oren'])
    // Ilsa's bar lies inside the chart; Oren's (open both ways) spans it.
    const [ilsa, oren] = within(history).getAllByTestId('gantt-bar')
    const x = (bar: Element | undefined, name: string) => Number(bar?.getAttribute(name))
    expect(x(ilsa, 'x')).toBeGreaterThan(0)
    expect(oren).toHaveAttribute('data-open-start', 'true')
    expect(oren).toHaveAttribute('data-open-end', 'true')
    expect(x(oren, 'x')).toBe(0)
    expect(x(oren, 'width')).toBeGreaterThan(x(ilsa, 'width'))
    // The spans read in the display calendar; the axis has its ticks.
    expect(rows[0]).toHaveTextContent(/11 April AD 1.* – 8 September AD 1/)
    expect(rows[1]).toHaveTextContent('always – ongoing')
    expect(await within(panel).findByRole('img', { name: 'Time axis' }, WAIT)).toBeVisible()
    expect(within(panel).getAllByTestId(/-tick$/).length).toBeGreaterThan(0)
  })

  it('shows the org chart with leaders and member counts, drawn or as a list', async () => {
    dated()
    await renderApp('/v/v1/e/empire')
    const structure = await screen.findByRole('region', { name: 'Structure' }, WAIT)
    const link = await within(structure).findByRole('link', { name: 'Open the org chart' }, WAIT)
    expect(link).toHaveAttribute('href', '/v/v1/m/groups/empire/org-chart')
    await userEvent.click(link)
    expect(await screen.findByRole('heading', { name: 'Org chart of Empire' }, WAIT)).toBeVisible()
    const figure = await screen.findByRole('figure', { name: 'Org chart' }, WAIT)
    await waitFor(
      () => {
        expect(
          within(figure)
            .getAllByTestId('org-unit')
            .map((unit) => unit.getAttribute('title'))
            .sort(),
        ).toEqual(['Empire', 'Harbor Guard', 'Harbor Office', 'Ministry of Tides'])
      },
      { timeout: 10_000 },
    )
    await userEvent.click(screen.getByRole('checkbox', { name: 'As a list' }))
    expect(screen.getAllByTestId('org-item').map((item) => item.textContent)).toEqual([
      'Empire · led by Ilsa (Empress) · 2 members',
      'Ministry of Tides · 1 member',
      'Harbor Guard (part) · 0 members',
      'Harbor Office · 0 members',
    ])
    await userEvent.selectOptions(screen.getByLabelText('Levels'), '1')
    await waitFor(() => {
      expect(screen.getAllByTestId('org-item')).toHaveLength(3)
    })
  }, 20_000)
})

describe('groups pages in reader mode', () => {
  it.each(['/v/v1/e/empire', '/v/v1/e/rebels'])(
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

describe('groups pages for the author', () => {
  it.each(['/v/v1/e/empire', '/v/v1/e/rebels'])(
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
