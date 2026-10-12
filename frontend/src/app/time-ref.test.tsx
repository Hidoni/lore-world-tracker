import type { Editor } from '@tiptap/core'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { calendarRow, dimensionRow } from '@/test/calendars'
import { defaultRows, kind, KINDS, row, serveVault } from '@/test/fake-vault'
import { renderApp } from '@/test/render-app'

const WAIT = { timeout: 4000 }

const march10 = {
  anchor: {
    kind: 'calendar',
    calendar_id: 'c-greg',
    fields: { year: '1023', month: 'mar', day: '10' },
  },
  precision: 'day',
}

/** Aetheria with the Gregorian (default) and Julian calendars, and a page writing dates. */
function world(body: unknown) {
  return serveVault({
    kinds: [...KINDS, kind('calendar', 'Calendar'), kind('event', 'Event')],
    rows: [
      ...defaultRows().filter((entity) => entity.id !== 'd1'),
      dimensionRow('d1', 'Aetheria', 'c-greg'),
      calendarRow('c-greg', 'Gregorian', 'gregorian'),
      calendarRow('c-jul', 'Julian', 'julian'),
      row('war', 'event', 'The Long War', {
        dimension_id: 'd1',
        // 1 January AD 1 (Gregorian) plus 400 days.
        ext: { start_t: (400n * 86_400n).toString(), end_t: (400n * 86_400n).toString() },
      }),
      row('w1', 'artifact', 'Chronicle', { dimension_id: 'd1', body }),
    ],
  })
}

const paragraph = (...content: unknown[]) => ({ type: 'paragraph', content })
const text = (value: string) => ({ type: 'text', text: value })

describe('timeRef', () => {
  it('renders in the reader’s display calendar, which a switch changes', async () => {
    world({
      type: 'doc',
      content: [
        paragraph(
          text('In '),
          { type: 'timeRef', attrs: { timePoint: march10 } },
          text(' the empire fell; the war began '),
          { type: 'timeRef', attrs: { ref: { type: 'event', id: 'war', slot: 'start' } } },
          text('; the plot dates from '),
          { type: 'timeRef', attrs: { hidden_ref: true } },
          text('.'),
        ),
      ],
    })
    const { router } = await renderApp('/v/v1/e/w1?cal=c-greg', undefined, { readOnly: true })
    const body = await screen.findByRole('region', { name: 'Body' })
    const fell = await within(body).findByRole('button', { name: '10 March AD 1023' }, WAIT)
    expect(fell).toHaveAttribute('data-time-ref')
    // A slot of a record resolves through it; a reference the reader may not see is "a date".
    expect(await within(body).findByRole('button', { name: /February AD 2/ })).toBeVisible()
    expect(within(body).getByText('a date')).toBeInTheDocument()

    // The popover lists every calendar and leads to the timeline.
    await userEvent.click(fell)
    const popover = await screen.findByRole('dialog', { name: 'The date 10 March AD 1023' })
    expect(popover).toHaveTextContent('Gregorian10 March AD 1023')
    expect(popover).toHaveTextContent(/Julian2 March AD 1023/)
    expect(within(popover).getByRole('link', { name: 'Show on timeline' })).toHaveAttribute(
      'href',
      expect.stringMatching(/^\/v\/v1\/d\/d1\/timeline\?from=\d+&to=\d+$/),
    )
    await userEvent.keyboard('{Escape}')

    // The reader switches to the Julian calendar: the same moment reads 2 March there.
    await act(async () => {
      await router.navigate({
        to: '.',
        search: (previous: Record<string, unknown>) => ({ ...previous, cal: 'c-jul' }),
      })
    })
    expect(await within(body).findByRole('button', { name: '2 March AD 1023' }, WAIT)).toBeVisible()
  })

  it('inserts a date from the slash menu or @date, saved as a time point', async () => {
    const writes = world(null)
    await renderApp('/v/v1/e/w1')
    const textbox = await screen.findByRole('textbox', { name: 'Body' }, WAIT)
    const editor = (textbox as HTMLElement & { editor: Editor }).editor
    act(() => {
      editor.chain().focus('end').insertContent('In /dat').run()
    })
    const menu = await screen.findByRole('listbox', { name: 'Insert a block' })
    expect(within(menu).getByRole('option', { name: /^Date/ })).toBeInTheDocument()
    await userEvent.keyboard('{Enter}')
    const dialog = await screen.findByRole('dialog', { name: 'Insert a date' })
    await userEvent.selectOptions(within(dialog).getByLabelText('Precision'), 'year')
    await userEvent.type(within(dialog).getByRole('textbox', { name: 'year' }), '1023')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Insert' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Insert a date' })).toBeNull()
    })
    expect(editor.getJSON().content[0]).toMatchObject({
      type: 'paragraph',
      content: [
        { type: 'text', text: 'In ' },
        {
          type: 'timeRef',
          attrs: {
            timePoint: {
              anchor: { kind: 'calendar', calendar_id: 'c-greg', fields: { year: '1023' } },
              precision: 'year',
            },
          },
        },
        { type: 'text', text: ' ' },
      ],
    })
    // In the editor it reads in the display calendar too.
    expect(await within(textbox).findByRole('button', { name: 'AD 1023' })).toBeVisible()
    await waitFor(() => {
      const saved = writes.filter((write) => write.method === 'PATCH').at(-1)?.body as
        { body?: unknown } | undefined
      expect(JSON.stringify(saved?.body)).toContain('"timeRef"')
    }, WAIT)

    // `@date` opens the same dialog.
    act(() => {
      editor.chain().focus('end').insertContent(' then @dat').run()
    })
    const mentions = await screen.findByRole('listbox')
    await userEvent.click(within(mentions).getByRole('option', { name: /^Date…/ }))
    expect(await screen.findByRole('dialog', { name: 'Insert a date' })).toBeInTheDocument()
    expect(editor.getText()).not.toContain('@dat')
  })
})
