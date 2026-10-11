import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { defaultRows, finding, rule, serveVault, type BlockingRow } from '@/test/fake-vault'
import { renderApp } from '@/test/render-app'

const crown = { id: 'a1', name: 'Crown', kind: 'artifact' }
const gem = { id: 'a3', name: 'Gem', kind: 'artifact' }

const RULES = [
  rule('core.parent_cycle', 'No parent cycles', { configurable: false, findings: 1 }),
  rule('core.event_order', 'Events in order', { default_severity: 'warning', severity: 'warning' }),
  rule('characters.lifespan', 'Alive at events', { findings: 2 }),
]

const FINDINGS = [
  finding('f-error', 'core.event_order', 'error', 'The coronation precedes the forging.', [crown]),
  finding('f-warning', 'characters.lifespan', 'warning', 'Gem outlives its maker.', [gem, crown]),
  finding('f-possible', 'characters.lifespan', 'info', 'Maybe too early.', [gem], {
    certainty: 'possible',
  }),
  finding('f-suppressed', 'core.event_order', 'warning', 'Known paradox.', [gem], {
    suppression: { note: 'Time travel', created_at: '2026-10-11T11:00:00Z' },
  }),
]

const BLOCKING: BlockingRow = {
  fingerprint: 'b1',
  rule_id: 'core.event_order',
  message: 'The crown is forged after its coronation.',
  subjects: ['a1'],
  suppressible: true,
}

const patches = (writes: { method: string; path: string; body: unknown }[]) =>
  writes.filter((write) => write.method === 'PATCH' && write.path.startsWith('/entities/'))

async function rename(name: string) {
  await userEvent.click(await screen.findByRole('button', { name: 'Rename' }))
  const input = screen.getByRole('textbox', { name: 'Name' })
  await userEvent.clear(input)
  await userEvent.type(input, `${name}{Enter}`)
}

describe('save anyway', () => {
  it('resends a refused write with suppressions and the author’s note', async () => {
    const writes = serveVault({ refusals: { findings: [BLOCKING], times: 1 } })
    await renderApp('/v/v1/e/a1')
    await rename('Old Crown')
    const dialog = await screen.findByRole('dialog', { name: 'Save anyway?' })
    expect(within(dialog).getByText(BLOCKING.message)).toBeInTheDocument()
    expect(await within(dialog).findByText('Crown')).toBeInTheDocument()
    const save = within(dialog).getByRole('button', { name: 'Save anyway (intentional)' })
    expect(save).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText('Why is this intentional?'), ' A legend ')
    await userEvent.click(save)
    await waitFor(() => {
      expect(patches(writes)).toHaveLength(2)
    })
    expect(patches(writes).map((write) => write.body)).toEqual([
      { name: 'Old Crown', revision: 1 },
      {
        name: 'Old Crown',
        revision: 1,
        suppress: [{ rule_id: 'core.event_order', note: 'A legend' }],
      },
    ])
    expect(await screen.findByRole('heading', { level: 1, name: 'Old Crown' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('gives up when cancelled, without a toast', async () => {
    const writes = serveVault({ refusals: { findings: [BLOCKING] } })
    await renderApp('/v/v1/e/a1')
    await rename('Old Crown')
    const dialog = await screen.findByRole('dialog', { name: 'Save anyway?' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    expect(patches(writes)).toHaveLength(1)
    expect(screen.queryByText('Consistency rule violated')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Crown' })).toBeInTheDocument()
  })

  it('only explains a refusal by a hard rule', async () => {
    const writes = serveVault({
      refusals: { findings: [{ ...BLOCKING, rule_id: 'core.parent_cycle', suppressible: false }] },
    })
    await renderApp('/v/v1/e/a1')
    await rename('Old Crown')
    const dialog = await screen.findByRole('dialog', { name: 'Can’t save this' })
    expect(
      within(dialog).getByText('It breaks a rule that can’t be overridden.'),
    ).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: /Save anyway/ })).not.toBeInTheDocument()
    expect(within(dialog).queryByLabelText('Why is this intentional?')).not.toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    expect(patches(writes)).toHaveLength(1)
  })
})

describe('findings panel', () => {
  const vault = () => serveVault({ findings: FINDINGS.map((item) => ({ ...item })), rules: RULES })
  const listed = () =>
    within(screen.getByRole('list', { name: 'Findings' }))
      .getAllByRole('listitem')
      .map((item) => item.getAttribute('aria-label'))

  it('filters by severity, certainty, rule, owner and suppression, in the URL', async () => {
    vault()
    const { router } = await renderApp('/v/v1/consistency')
    await screen.findByRole('list', { name: 'Findings' })
    expect(listed()).toEqual(['The coronation precedes the forging.', 'Gem outlives its maker.'])

    await userEvent.click(screen.getByRole('checkbox', { name: 'Error' }))
    await waitFor(() => {
      expect(listed()).toEqual(['Gem outlives its maker.'])
    })
    expect(router.state.location.search).toMatchObject({ severity: 'warning,info' })
    await userEvent.click(screen.getByRole('checkbox', { name: 'Show uncertain' }))
    await waitFor(() => {
      expect(listed()).toEqual(['Gem outlives its maker.', 'Maybe too early.'])
    })
    await userEvent.click(screen.getByRole('checkbox', { name: 'Show suppressed' }))
    await waitFor(() => {
      expect(listed()).toContain('Known paradox.')
    })
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Rule' }), 'Events in order')
    await waitFor(() => {
      expect(listed()).toEqual(['Known paradox.'])
    })
    expect(router.state.location.search).toMatchObject({
      severity: 'warning,info',
      uncertain: 'true',
      suppressed: 'true',
      rule: 'core.event_order',
    })
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Rule' }), 'Every rule')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Error' }))
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Owner' }), 'characters')
    await waitFor(() => {
      expect(listed()).toEqual(['Gem outlives its maker.', 'Maybe too early.'])
    })
  })

  it('filters by entity from a badge, explains and suppresses with a note', async () => {
    const writes = vault()
    await renderApp('/v/v1/e/a1')
    await userEvent.click(await screen.findByRole('link', { name: '2 consistency findings' }))
    expect(await screen.findByText('Crown', { selector: 'strong' })).toBeInTheDocument()
    await waitFor(() => {
      expect(listed()).toEqual(['The coronation precedes the forging.', 'Gem outlives its maker.'])
    })

    const first = screen.getByRole('listitem', { name: 'The coronation precedes the forging.' })
    await userEvent.click(within(first).getByRole('button', { name: 'Explain' }))
    const sheet = await screen.findByRole('dialog', { name: 'core.event_order' })
    expect(within(sheet).getByText('Events in order: the description.')).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')

    await userEvent.click(within(first).getByRole('button', { name: 'Suppress…' }))
    const dialog = await screen.findByRole('dialog', { name: 'Suppress this finding?' })
    await userEvent.type(within(dialog).getByLabelText('Why is this intentional?'), 'Prophecy')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Suppress' }))
    await waitFor(() => {
      expect(listed()).toEqual(['Gem outlives its maker.'])
    })
    expect(writes.find((write) => write.path === '/consistency/suppressions')?.body).toEqual({
      fingerprint: 'f-error',
      note: 'Prophecy',
    })
    await userEvent.click(screen.getByRole('button', { name: 'Show all' }))
    await waitFor(() => {
      expect(screen.queryByText('Crown', { selector: 'strong' })).not.toBeInTheDocument()
    })
  })

  it('shows badges on entity headers and tree rows', async () => {
    serveVault({
      findings: [
        ...FINDINGS.map((item) => ({ ...item })),
        finding('f-treasury', 'core.event_order', 'error', 'Empty treasury.', [
          { id: 'a2', name: 'Treasury', kind: 'artifact' },
        ]),
      ],
      rules: RULES,
    })
    await renderApp('/v/v1/e/a3')
    const main = await screen.findByRole('main')
    // Gem: a warning and a possible finding (the suppressed one doesn't count).
    const header = await within(main).findByRole('link', { name: '2 consistency findings' })
    expect(header).toHaveAttribute('data-severity', 'warning')
    const sidebar = screen.getByRole('complementary', { name: 'Sidebar' })
    const treasury = await within(sidebar).findByRole('link', { name: '1 consistency finding' })
    expect(treasury).toHaveAttribute('data-severity', 'error')
    expect(treasury).toHaveAttribute('href', '/v/v1/consistency?entity=a2')
  })

  it('shows no badges to readers', async () => {
    vault()
    await renderApp('/v/v1/e/a1', undefined, { readOnly: true })
    await screen.findByRole('heading', { level: 1, name: 'Crown' })
    expect(screen.queryByRole('link', { name: /consistency finding/ })).not.toBeInTheDocument()
  })
})

describe('rule settings', () => {
  it('groups rules by owner and sets severities; hard rules are locked', async () => {
    const writes = serveVault({ rows: defaultRows(), rules: RULES.map((item) => ({ ...item })) })
    await renderApp('/v/v1/settings/consistency')
    const core = await screen.findByRole('region', { name: 'Core rules' })
    expect(within(core).getByRole('combobox', { name: 'No parent cycles severity' })).toBeDisabled()
    expect(screen.getByRole('region', { name: 'characters rules' })).toHaveTextContent(
      'Alive at events',
    )
    const order = within(core).getByRole('combobox', { name: 'Events in order severity' })
    await userEvent.selectOptions(order, 'error')
    await waitFor(() => {
      expect(order).toHaveValue('error')
    })
    await userEvent.selectOptions(order, 'warning')
    await waitFor(() => {
      expect(order).toHaveValue('warning')
    })
    expect(
      writes.filter((write) => write.method === 'PATCH').map((write) => [write.path, write.body]),
    ).toEqual([
      ['/consistency/rules/core.event_order', { severity: 'error' }],
      ['/consistency/rules/core.event_order', { severity: null }],
    ])
  })
})
