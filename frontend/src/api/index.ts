// API client: generated schema.gen.ts, openapi-fetch client and error mapping (frontend.md §5.2).
export {
  api,
  apiMiddleware,
  CLIENT_HEADER,
  createApiClient,
  unwrap,
  type ApiClient,
} from './client'
export { ApiError, toApiError, type Problem, type ProblemErrorItem } from './errors'
export type { components, operations, paths } from './schema.gen'
