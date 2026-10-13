import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { defaultRows, kind, KINDS, linkType, row, serveVault } from '@/test/fake-vault'
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
