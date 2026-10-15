import { configure, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import { CAPS, FIELD, defaultRows, kind, KINDS, row, serveVault } from '@/test/fake-vault'
import { server } from '@/test/msw'
import { renderApp } from '@/test/render-app'

const WAIT = { timeout: 5000 }
// Uploads go through XHR: slower than fetch on a busy CI runner.
configure({ asyncUtilTimeout: 5000 })

beforeEach(() => {
  localStorage.clear()
})

interface FakeItem {
  id: string
  filename: string
  mime?: string
  alt?: string
  refs?: { entity_id: string; context: string }[]
  deleted?: boolean
}

const itemOut = (item: FakeItem & { revision?: number }) => ({
  id: item.id,
  sha256: `${item.id}0000000000000000`,
  filename: item.filename,
  mime: item.mime ?? 'image/png',
  size: 2048,
  width: 400,
  height: 300,
  alt: item.alt ?? '',
  caption: '',
  revision: item.revision ?? 1,
  created_at: '2026-10-01T00:00:00Z',
  deleted_at: item.deleted === true ? '2026-10-02T00:00:00Z' : null,
  refs: item.refs ?? [],
})

interface GalleryEntry {
  id: string
  media: string
  key: string
  caption: string
  revision: number
}

/**
 * A multipart body's file name and text fields, read from its text (Node 26's `formData()`
 * rejects the files jsdom's XHR sends).
 */
async function multipart(
  request: Request,
): Promise<{ filename: string; fields: Record<string, string> }> {
  const text = await request.text()
  const filename = /filename="([^"]*)"/.exec(text)?.[1] ?? ''
  const fields: Record<string, string> = {}
  for (const match of text.matchAll(/name="([^"]+)"\r\n\r\n([^\r]*)\r\n/g)) {
    const [, name = '', value = ''] = match
    fields[name] = value
  }
  return { filename, fields }
}

const ARTIFACT = kind('artifact', 'Artifact', {
  allowed_parents: ['artifact'],
  capabilities: { ...CAPS, can_be_multiversal: true },
  fields: [FIELD, { ...FIELD, key: 'portrait', label: 'Portrait', type: 'media' }],
})

/**
 * A vault with the media module: a map, a portrait (used as the Crown's cover) and a pdf; the
 * Crown's gallery has three images. Returns the media requests seen.
 */
function world(options: { body?: unknown; gallery?: boolean } = {}) {
  const items = new Map<string, ReturnType<typeof itemOut>>(
    [
      { id: 'm1', filename: 'map.png', alt: 'A map' },
      { id: 'm2', filename: 'portrait.png', refs: [{ entity_id: 'a1', context: 'cover' }] },
      { id: 'm3', filename: 'notes.pdf', mime: 'application/pdf' },
    ].map((item) => [item.id, itemOut(item)]),
  )
  let gallery: GalleryEntry[] =
    options.gallery === true
      ? (
          [
            ['g1', 'm1', 'a'],
            ['g2', 'm2', 'aV'],
            ['g3', 'm3', 'aVV'],
          ] as const
        ).map(([id, media, key]) => ({ id, media, key, caption: '', revision: 1 }))
      : []
  const requests: {
    method: string
    path: string
    body: unknown
    query?: Record<string, string>
  }[] = []
  let seq = 0
  const writes = serveVault({
    modules: ['media'],
    kinds: [KINDS[0], ARTIFACT],
    rows: [
      ...defaultRows().filter((entity) => entity.id !== 'a1'),
      row('a1', 'artifact', 'Crown', {
        parent_id: 'a2',
        body: options.body ?? null,
      }),
    ],
  })
  const galleryOut = (entry: GalleryEntry) => ({
    id: entry.id,
    entity_id: 'a1',
    media_id: entry.media,
    caption: entry.caption,
    sort_key: entry.key,
    visibility: 'public',
    revision: entry.revision,
    media: items.get(entry.media),
  })
  const base = '*/api/v1/vaults/v1/m/media'
  server.use(
    http.get(`${base}/items`, ({ request }) => {
      const query = Object.fromEntries(new URL(request.url).searchParams)
      requests.push({ method: 'GET', path: '/items', body: null, query })
      const shown = [...items.values()].filter(
        (item) =>
          (query.trashed === 'true') === (item.deleted_at !== null) &&
          (query.unused !== 'true' || item.refs.length === 0) &&
          (query.mime === undefined || item.mime.startsWith(query.mime)) &&
          (query.q === undefined || item.filename.includes(query.q)),
      )
      return HttpResponse.json({ items: shown.reverse(), next_cursor: null })
    }),
    http.get(`${base}/items/:id`, ({ params }) => {
      const item = items.get(String(params.id))
      return item ? HttpResponse.json(item) : new HttpResponse(null, { status: 404 })
    }),
    http.post(`${base}/items`, async ({ request }) => {
      const { filename } = await multipart(request)
      requests.push({ method: 'POST', path: '/items', body: filename })
      seq += 1
      const item = itemOut({ id: `new${String(seq)}`, filename })
      items.set(item.id, item)
      return HttpResponse.json({ item, created: true }, { status: 201 })
    }),
    http.patch(`${base}/items/:id`, async ({ request, params }) => {
      const body = (await request.json()) as Record<string, unknown>
      requests.push({ method: 'PATCH', path: `/items/${String(params.id)}`, body })
      const item = items.get(String(params.id))
      if (!item) return new HttpResponse(null, { status: 404 })
      const next = { ...item, ...body, revision: item.revision + 1 }
      items.set(item.id, next)
      return HttpResponse.json(next)
    }),
    http.put(`${base}/items/:id/file`, async ({ request, params }) => {
      const { filename, fields } = await multipart(request)
      requests.push({
        method: 'PUT',
        path: `/items/${String(params.id)}/file`,
        body: { file: filename, revision: fields.revision },
      })
      const item = items.get(String(params.id))
      if (!item) return new HttpResponse(null, { status: 404 })
      const next = { ...item, filename, revision: item.revision + 1 }
      items.set(item.id, next)
      return HttpResponse.json(next)
    }),
    http.delete(`${base}/items/:id`, ({ params }) => {
      requests.push({ method: 'DELETE', path: `/items/${String(params.id)}`, body: null })
      const item = items.get(String(params.id))
      if (!item) return new HttpResponse(null, { status: 404 })
      const next = { ...item, deleted_at: '2026-10-15T00:00:00Z' }
      items.set(item.id, next)
      return HttpResponse.json(next)
    }),
    http.get(`${base}/entities/:id/gallery`, ({ params }) =>
      HttpResponse.json({
        entity_id: params.id,
        items: [...gallery].sort((a, b) => (a.key < b.key ? -1 : 1)).map(galleryOut),
      }),
    ),
    http.post(`${base}/entities/:id/gallery`, async ({ request }) => {
      const body = (await request.json()) as { media_id: string }
      requests.push({ method: 'POST', path: '/gallery', body })
      const entry = {
        id: `g${String(gallery.length + 1)}`,
        media: body.media_id,
        key: 'z',
        caption: '',
        revision: 1,
      }
      gallery = [...gallery, entry]
      return HttpResponse.json(galleryOut(entry), { status: 201 })
    }),
    http.patch(`${base}/gallery/:id`, async ({ request, params }) => {
      const body = (await request.json()) as { sort_key?: string; caption?: string }
      requests.push({ method: 'PATCH', path: `/gallery/${String(params.id)}`, body })
      gallery = gallery.map((entry) =>
        entry.id === params.id
          ? {
              ...entry,
              key: body.sort_key ?? entry.key,
              caption: body.caption ?? entry.caption,
              revision: entry.revision + 1,
            }
          : entry,
      )
      const entry = gallery.find((other) => other.id === params.id)
      return entry ? HttpResponse.json(galleryOut(entry)) : new HttpResponse(null, { status: 404 })
    }),
  )
  return { requests, writes }
}

const png = (name: string) =>
  new File([new Uint8Array([137, 80, 78, 71])], name, { type: 'image/png' })

describe('media module', () => {
  it(
    'lists the library, filters it, uploads, edits, replaces and trashes in bulk',
    { timeout: 30_000 },
    async () => {
      const { requests } = world()
      await renderApp('/v/v1/m/media/library')
      const files = await screen.findByRole('list', { name: 'Files' }, WAIT)
      expect(
        within(files)
          .getAllByRole('button')
          .map((b) => b.getAttribute('aria-label')),
      ).toEqual(['Open notes.pdf', 'Open portrait.png', 'Open map.png'])

      await userEvent.click(screen.getByRole('checkbox', { name: 'Unused only' }))
      await waitFor(() => {
        expect(
          within(screen.getByRole('list', { name: 'Files' })).queryByText('portrait.png'),
        ).toBeNull()
      })
      expect(requests.at(-1)?.query).toMatchObject({ unused: 'true' })
      await userEvent.click(screen.getByRole('checkbox', { name: 'Unused only' }))

      await userEvent.upload(screen.getByLabelText('Upload files'), [png('dragon.png')])
      // (jsdom's XHR sends files without their names.)
      await waitFor(() => {
        expect(
          within(screen.getByRole('list', { name: 'Files' })).getAllByRole('listitem'),
        ).toHaveLength(4)
      }, WAIT)
      expect(requests.filter((r) => r.method === 'POST' && r.path === '/items')).toHaveLength(1)

      // One file: who uses it, its alt text, a new file.
      await userEvent.click(screen.getByRole('button', { name: 'Open portrait.png' }))
      const sheet = await screen.findByRole('dialog', {}, WAIT)
      const usedBy = within(sheet).getByRole('region', { name: 'Used by' })
      expect(await within(usedBy).findByRole('link', { name: 'Crown' }, WAIT)).toHaveAttribute(
        'href',
        '/v/v1/e/a1',
      )
      expect(usedBy).toHaveTextContent('(cover)')
      await userEvent.type(within(sheet).getByLabelText('Alt text'), 'The queen')
      await userEvent.click(within(sheet).getByRole('button', { name: 'Save' }))
      await waitFor(() => {
        expect(requests).toContainEqual({
          method: 'PATCH',
          path: '/items/m2',
          body: { revision: 1, alt: 'The queen', caption: '' },
        })
      })
      await userEvent.upload(within(sheet).getByLabelText('Replacement file'), [png('queen.png')])
      await waitFor(() => {
        expect(requests).toContainEqual({
          method: 'PUT',
          path: '/items/m2/file',
          body: { file: expect.any(String) as unknown, revision: '2' },
        })
      })
      await userEvent.keyboard('{Escape}')

      await userEvent.click(await screen.findByRole('checkbox', { name: 'Select map.png' }))
      await userEvent.click(screen.getByRole('checkbox', { name: 'Select notes.pdf' }))
      await userEvent.click(screen.getByRole('button', { name: 'Move to the trash' }))
      await waitFor(() => {
        expect(requests.filter((r) => r.method === 'DELETE').map((r) => r.path)).toEqual([
          '/items/m1',
          '/items/m3',
        ])
      })
      await waitFor(() => {
        expect(
          within(screen.getByRole('list', { name: 'Files' })).queryByText('map.png'),
        ).toBeNull()
      })
    },
  )

  it('sets a cover image from the library picker', async () => {
    const { writes } = world()
    await renderApp('/v/v1/e/a1')
    const cover = await screen.findByRole('group', { name: 'Cover image' }, WAIT)
    await userEvent.click(within(cover).getByRole('button', { name: 'Add cover' }))
    const picker = await screen.findByRole('dialog', { name: 'Choose a cover image' })
    await userEvent.click(await within(picker).findByRole('button', { name: 'Pick map.png' }, WAIT))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({ method: 'PATCH', body: { cover_media_id: 'm1' } })
    })
    expect(
      await within(cover).findByRole('img', { name: 'Crown (cover)' }, WAIT),
    ).toBeInTheDocument()
    await userEvent.click(within(cover).getByRole('button', { name: 'Remove the cover' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({ method: 'PATCH', body: { cover_media_id: null } })
    })
  })

  it('reorders, captions and adds gallery images', async () => {
    const { requests } = world({ gallery: true })
    await renderApp('/v/v1/e/a1')
    const gallery = await screen.findByRole('list', { name: 'Gallery' }, WAIT)
    await userEvent.click(within(gallery).getByRole('button', { name: 'Move portrait.png later' }))
    await waitFor(() => {
      const moved = requests.find((r) => r.path === '/gallery/g2')
      expect((moved?.body as { sort_key: string }).sort_key > 'aVV').toBe(true)
    })
    await waitFor(() => {
      const names = within(screen.getByRole('list', { name: 'Gallery' }))
        .getAllByRole('textbox')
        .map((box) => box.getAttribute('aria-label'))
      expect(names).toEqual([
        'Caption of map.png',
        'Caption of notes.pdf',
        'Caption of portrait.png',
      ])
    })
    const caption = screen.getByRole('textbox', { name: 'Caption of map.png' })
    await userEvent.type(caption, 'The old world{Enter}')
    await waitFor(() => {
      expect(requests).toContainEqual({
        method: 'PATCH',
        path: '/gallery/g1',
        body: { revision: 1, caption: 'The old world' },
      })
    })
    await userEvent.click(screen.getByRole('button', { name: 'Add an image' }))
    const picker = await screen.findByRole('dialog', { name: 'Add to the gallery' })
    await userEvent.upload(within(picker).getByLabelText('Upload'), [png('dragon.png')])
    await waitFor(() => {
      expect(requests).toContainEqual({
        method: 'POST',
        path: '/gallery',
        body: { media_id: 'new1' },
      })
    }, WAIT)
  })

  it('edits a media field with the image picker', async () => {
    const { writes } = world()
    await renderApp('/v/v1/e/a1')
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Portrait' }, WAIT))
    await userEvent.click(screen.getByRole('button', { name: 'Choose an image' }))
    const picker = await screen.findByRole('dialog', { name: 'Portrait' })
    await userEvent.click(await within(picker).findByRole('button', { name: 'Pick map.png' }, WAIT))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({ method: 'PATCH', body: { fields: { portrait: 'm1' } } })
    })
    expect(await screen.findByRole('img', { name: 'A map' }, WAIT)).toBeInTheDocument()
  })

  it('shows image nodes of pages with their captions', async () => {
    world({
      body: {
        type: 'doc',
        content: [
          {
            type: 'image',
            attrs: {
              mediaId: 'm1',
              alt: 'The continent',
              caption: 'Varn, before the flood',
              width: 480,
            },
          },
        ],
      },
    })
    await renderApp('/v/v1/e/a1', undefined, { readOnly: true })
    const image = await screen.findByRole('img', { name: 'The continent' }, WAIT)
    expect(image).toHaveAttribute('loading', 'lazy')
    expect(image.getAttribute('src')).toContain('/m/media/items/m1/file?size=480')
    expect(screen.getByText('Varn, before the flood').tagName).toBe('FIGCAPTION')
  })
})
