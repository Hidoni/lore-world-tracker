import createClient from 'openapi-fetch'
import { describe, expect, it } from 'vitest'

import { apiMiddleware, CLIENT_HEADER, createApiClient, unwrap } from './client'
import { ApiError, PROBLEM_MEDIA_TYPE } from './errors'

const BASE_URL = 'http://lore.test'

interface Thing {
  name: string
}

interface ThingOperation {
  parameters: { query?: never; header?: never; path?: never; cookie?: never }
  requestBody?: { content: { 'application/json': Thing } }
  responses: { 200: { headers: Record<string, unknown>; content: { 'application/json': Thing } } }
}

/** A stand-in API with mutating routes (the real one only has GETs so far). */
interface TestPaths {
  '/api/v1/things': {
    parameters: { query?: never; header?: never; path?: never; cookie?: never }
    get: ThingOperation
    post: ThingOperation
    delete: ThingOperation
  }
}

function recordingFetch(respond: () => Response = () => Response.json({ name: 'Ilúvatar' })) {
  const requests: Request[] = []
  const fetch = (request: Request) => {
    requests.push(request)
    return Promise.resolve(respond())
  }
  return { requests, fetch }
}

function testClient(respond?: () => Response) {
  const { requests, fetch } = recordingFetch(respond)
  const client = createClient<TestPaths>({ baseUrl: BASE_URL, fetch })
  client.use(...apiMiddleware)
  return { client, requests }
}

function problemResponse(status: number, body: object): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': PROBLEM_MEDIA_TYPE },
  })
}

describe('client header middleware', () => {
  it('leaves safe requests alone', async () => {
    const { client, requests } = testClient()
    await client.GET('/api/v1/things')
    expect(requests[0]?.headers.has(CLIENT_HEADER)).toBe(false)
  })

  it('marks mutating requests as coming from the web client', async () => {
    const { client, requests } = testClient()
    await client.POST('/api/v1/things', { body: { name: 'Melkor' } })
    await client.DELETE('/api/v1/things')
    expect(requests.map((request) => request.headers.get(CLIENT_HEADER))).toEqual(['web', 'web'])
  })
})

describe('problem middleware', () => {
  it('maps application/problem+json responses to ApiError', async () => {
    const { client } = testClient(() =>
      problemResponse(422, {
        type: 'urn:lore:problem:validation_error',
        title: 'Validation error',
        status: 422,
        detail: 'The request is invalid.',
        code: 'validation_error',
        errors: [{ path: 'body.name', code: 'missing', message: 'Field required' }],
        context: { kind: 'character' },
      }),
    )
    const error = await client
      .POST('/api/v1/things', { body: { name: '' } })
      .catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 422,
      code: 'validation_error',
      title: 'Validation error',
      detail: 'The request is invalid.',
      errors: [{ path: 'body.name', code: 'missing', message: 'Field required' }],
      context: { kind: 'character' },
      message: 'The request is invalid.',
    })
  })

  it('defaults errors and context for problems without them', async () => {
    const { client } = testClient(() =>
      problemResponse(404, {
        type: 'urn:lore:problem:not_found',
        title: 'Not found',
        status: 404,
        detail: 'No such thing.',
        code: 'not_found',
      }),
    )
    await expect(client.GET('/api/v1/things')).rejects.toMatchObject({
      code: 'not_found',
      errors: [],
      context: {},
    })
  })

  it('falls back to http_<status> for responses that are not problems', async () => {
    const { client } = testClient(
      () => new Response('<h1>Bad gateway</h1>', { status: 502, statusText: 'Bad Gateway' }),
    )
    await expect(client.GET('/api/v1/things')).rejects.toMatchObject({
      name: 'ApiError',
      status: 502,
      code: 'http_502',
      title: 'Bad Gateway',
    })
  })

  it('falls back when a problem body is malformed', async () => {
    const { client } = testClient(
      () => new Response('{', { status: 500, headers: { 'Content-Type': PROBLEM_MEDIA_TYPE } }),
    )
    await expect(client.GET('/api/v1/things')).rejects.toMatchObject({
      status: 500,
      code: 'http_500',
      title: 'HTTP 500',
    })
  })
})

describe('createApiClient', () => {
  it('returns typed data for the real API', async () => {
    const meta = {
      app_version: '0.0.0',
      api_version: 'v1',
      read_only: false,
      exposed_vaults: [],
      features: [],
    }
    const { requests, fetch } = recordingFetch(() => Response.json(meta))
    const client = createApiClient({ baseUrl: BASE_URL, fetch })

    await expect(unwrap(client.GET('/api/v1/meta'))).resolves.toEqual(meta)
    expect(requests[0]?.url).toBe(`${BASE_URL}/api/v1/meta`)
  })
})
