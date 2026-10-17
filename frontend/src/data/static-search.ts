import type { components } from '@/api'

import { StaticProblem, type Handler, type Load } from './static-core'

/**
 * Search in a static export (#377, ADR 0016): the server's search, ported over the documents
 * readers can search (`lore/static_export/search.py`): the expression grammar
 * (`lore.core.search.expression`), matching as FTS5's `unicode61 remove_diacritics 2` tokenizer
 * does (word starts, exact phrases, OR, NOT, groups), the quick switcher (word starts, then
 * substrings: the `trigram` table) and snippets (`highlight.py`). Results are the server's; their
 * order is ranked by the same bm25 formula and column weights, with statistics over the exported
 * documents, so ties and near ties can be ordered differently (visibility-and-sharing.md §8).
 */

type Schemas = components['schemas']
type Hit = Omit<Schemas['SearchHit'], 'snippet'>

/** A reader's columns (`PUBLIC_COLUMNS`). */
interface Texts {
  name: string
  aliases_public: string
  summary: string
  body_public: string
  fields_public: string
  extra_public: string
}

interface Doc {
  rowid: number
  hit: Hit
  text: Texts
  origin: string | null
}

interface SearchFile {
  docs: Doc[]
  kinds: string[]
  rows: number
}

interface IndexFile {
  timelines: Record<string, { lineage: string[] }>
}

type Column = keyof Texts
const COLUMNS: readonly Column[] = [
  'name',
  'aliases_public',
  'summary',
  'body_public',
  'fields_public',
  'extra_public',
]
const WEIGHTS: Record<Column, number> = {
  name: 10,
  aliases_public: 6,
  summary: 4,
  body_public: 2,
  fields_public: 1,
  extra_public: 2,
}
const QUICK_COLUMNS: readonly Column[] = ['name', 'aliases_public']
const SNIPPET_COLUMNS: readonly (readonly [Column, Schemas['Snippet']['source']])[] = [
  ['body_public', 'body'],
  ['summary', 'summary'],
  ['extra_public', 'extra'],
  ['fields_public', 'fields'],
  ['aliases_public', 'aliases'],
]
const QUICK_LIMIT = 20
const TRIGRAM_MIN = 3
const MAX_DEPTH = 8
const MAX_TERMS = 32
const WINDOW = 16
const LEAD = 4
const ELLIPSIS = '…'

/** `fold_text`: accents removed, case folded. */
export function fold(text: string): string {
  return text.normalize('NFKD').replace(/\p{M}/gu, '').normalize('NFC').toLowerCase()
}

/** Tokens as FTS5's `unicode61` sees them (letters, digits, private-use characters). */
const TOKEN = /[\p{L}\p{N}\p{Co}]+/gu
function tokens(text: string): string[] {
  return fold(text).match(TOKEN) ?? []
}

// --- the expression (expression.py) -------------------------------------------------------------

/** A phrase: words in order, each exactly, the last one a word start with `prefix`. */
interface Term {
  kind: 'term'
  words: string[]
  prefix: boolean
}
interface All {
  kind: 'all'
  included: Node[]
  excluded: Node[]
}
interface Any {
  kind: 'any'
  alternatives: Node[]
}
type Node = Term | All | Any

class ExpressionError extends Error {}

/** Python's `\w`: letters, digits and the underscore, in any script. */
const WORD = /[\p{L}\p{N}_]/u
const SPLIT = /\s+|\(|\)|"[^"]*"?\*?|[^\s()"]+/gu

class Parser {
  tokens: string[]
  position = 0
  terms: Term[] = []
  phrases: Term[] = []

  constructor(text: string) {
    this.tokens = (text.match(SPLIT) ?? []).filter((t) => t.trim() !== '')
  }

  peek(): string | undefined {
    return this.tokens[this.position]
  }

  take(): string {
    const token = this.tokens[this.position] ?? ''
    this.position++
    return token
  }

  parse(): Node {
    if (this.tokens.length === 0) throw new ExpressionError('Type something to search for.')
    const node = this.expression(0)
    if (this.peek() !== undefined) {
      throw new ExpressionError('A closing parenthesis has no opening one.')
    }
    if (node === null) throw new ExpressionError('Nothing to search for: use words or letters.')
    if (this.terms.length > MAX_TERMS) {
      throw new ExpressionError(`Use at most ${MAX_TERMS} words or phrases.`)
    }
    return node
  }

  expression(depth: number): Node | null {
    if (depth > MAX_DEPTH) throw new ExpressionError('Too many nested parentheses.')
    const alternatives = [this.allOf(depth)]
    while (this.peek() === 'OR') {
      this.take()
      alternatives.push(this.allOf(depth))
    }
    const kept = alternatives.filter((a): a is Node => a !== null)
    if (kept.length === 0) return null
    return kept.length === 1 ? (kept[0] ?? null) : { kind: 'any', alternatives: kept }
  }

  allOf(depth: number): Node | null {
    const included: Node[] = []
    const excluded: Node[] = []
    let parts = 0
    for (let token = this.peek(); token !== undefined && token !== 'OR' && token !== ')';) {
      if (token === 'AND') {
        this.take()
        token = this.peek()
        continue
      }
      let negated = false
      if (token === '-' || token === 'NOT') {
        this.take()
        negated = true
      } else if (token.startsWith('-') && token.length > 1) {
        this.tokens[this.position] = token.slice(1)
        negated = true
      }
      const atom = this.atom(depth, negated)
      parts++
      if (atom !== null) (negated ? excluded : included).push(atom)
      token = this.peek()
    }
    if (parts === 0) throw new ExpressionError('OR needs something to search for on both sides.')
    if (included.length === 0) {
      if (excluded.length > 0) {
        throw new ExpressionError('Say what to search for, not only what to leave out.')
      }
      return null
    }
    if (included.length === 1 && excluded.length === 0) return included[0] ?? null
    return { kind: 'all', included, excluded }
  }

  atom(depth: number, negated: boolean): Node | null {
    const token = this.peek()
    if (token === undefined || token === 'OR' || token === ')') {
      throw new ExpressionError('Leave out what? Put a word after - or NOT.')
    }
    this.take()
    if (token === '(') {
      const inner = this.expression(depth + 1)
      if (this.peek() !== ')') throw new ExpressionError("A parenthesis isn't closed.")
      this.take()
      return inner
    }
    if (token.startsWith('"')) {
      const prefix = token.endsWith('*')
      const body = token.replace(/\*+$/u, '')
      if (body.length < 2 || !body.endsWith('"')) throw new ExpressionError("A quote isn't closed.")
      const phrase = body.slice(1, -1)
      if (!WORD.test(phrase)) return null
      return this.term(phrase, prefix, negated)
    }
    const word = token.replace(/\*+$/u, '')
    if (!WORD.test(word)) return null
    return this.term(word, true, negated)
  }

  term(text: string, prefix: boolean, negated: boolean): Term {
    const term: Term = { kind: 'term', words: tokens(text), prefix }
    if (!negated) this.terms.push(term)
    this.phrases.push(term)
    return term
  }
}

// --- matching and ranking ------------------------------------------------------------------------

/** A document's columns as tokens (made once per document). */
const TOKENS = new WeakMap<Doc, Record<Column, string[]>>()

function columnsOf(doc: Doc): Record<Column, string[]> {
  let found = TOKENS.get(doc)
  if (found === undefined) {
    found = Object.fromEntries(COLUMNS.map((c) => [c, tokens(doc.text[c])])) as Record<
      Column,
      string[]
    >
    TOKENS.set(doc, found)
  }
  return found
}

/** How many times a phrase occurs in a column's tokens. */
function hits(column: readonly string[], term: Term): number {
  const { words, prefix } = term
  if (words.length === 0) return 0
  const last = words.length - 1
  let count = 0
  for (let at = 0; at + words.length <= column.length; at++) {
    let ok = true
    for (let i = 0; i < words.length && ok; i++) {
      const token = column[at + i] ?? ''
      const word = words[i] ?? ''
      ok = token === word || (i === last && prefix && token.startsWith(word))
    }
    if (ok) count++
  }
  return count
}

function matches(node: Node, doc: Doc, columns: readonly Column[]): boolean {
  if (node.kind === 'term') {
    const tokensOf = columnsOf(doc)
    return columns.some((c) => hits(tokensOf[c], node) > 0)
  }
  if (node.kind === 'any') return node.alternatives.some((a) => matches(a, doc, columns))
  return (
    node.included.every((n) => matches(n, doc, columns)) &&
    !node.excluded.some((n) => matches(n, doc, columns))
  )
}

/** FTS5's `bm25()` (k1 1.2, b 0.75) with the server's column weights: lower is better. */
function ranker(
  phrases: readonly Term[],
  docs: readonly Doc[],
  rows: number,
  columns: readonly Column[],
  weights: Record<Column, number>,
) {
  const sizes = new Map(
    docs.map((doc) => {
      const tokensOf = columnsOf(doc)
      return [doc, COLUMNS.reduce((total, c) => total + tokensOf[c].length, 0)] as const
    }),
  )
  const total = rows || docs.length || 1
  const average = [...sizes.values()].reduce((a, b) => a + b, 0) / Math.max(docs.length, 1) || 1
  const idf = phrases.map((phrase) => {
    const n = docs.filter((doc) => columns.some((c) => hits(columnsOf(doc)[c], phrase) > 0)).length
    const value = Math.log((total - n + 0.5) / (n + 0.5))
    return value <= 0 ? 1e-6 : value
  })
  return (doc: Doc): number => {
    const tokensOf = columnsOf(doc)
    const size = sizes.get(doc) ?? 0
    let score = 0
    phrases.forEach((phrase, i) => {
      const freq = columns.reduce((sum, c) => sum + weights[c] * hits(tokensOf[c], phrase), 0)
      score += ((idf[i] ?? 0) * (freq * 2.2)) / (freq + 1.2 * (1 - 0.75 + (0.75 * size) / average))
    })
    return -score
  }
}

// --- snippets (highlight.py) ---------------------------------------------------------------------

const SNIPPET_WORD = /[\p{L}\p{N}]+/gu

function snippet(text: string, terms: readonly Term[]): Schemas['SnippetPart'][] | null {
  const spans = [...text.matchAll(SNIPPET_WORD)].map(
    (m) => [m.index, m.index + m[0].length] as const,
  )
  const words = spans.map(([start, end]) => fold(text.slice(start, end)))
  const matched = words.map(() => false)
  for (let at = 0; at < words.length; at++) {
    for (const term of terms) {
      if (term.words.length === 0 || at + term.words.length > words.length) continue
      const last = term.words.length - 1
      const ok = term.words.every((word, i) => {
        const token = words[at + i] ?? ''
        return token === word || (i === last && term.prefix && token.startsWith(word))
      })
      if (ok) for (let i = 0; i < term.words.length; i++) matched[at + i] = true
    }
  }
  const firstMatch = matched.indexOf(true)
  if (firstMatch < 0) return null
  let first = Math.max(0, firstMatch - LEAD)
  const last = Math.min(words.length, first + WINDOW) - 1
  first = Math.max(0, Math.min(first, last + 1 - WINDOW))
  const start = first === 0 ? 0 : (spans[first]?.[0] ?? 0)
  const end = last === words.length - 1 ? text.length : (spans[last]?.[1] ?? text.length)
  const parts: Schemas['SnippetPart'][] = []
  const add = (piece: string, match: boolean) => {
    const cleaned = piece.replaceAll('\n', ' ')
    if (!cleaned) return
    const previous = parts[parts.length - 1]
    if (previous?.match === match) previous.text += cleaned
    else parts.push({ text: cleaned, match })
  }
  if (start > 0) add(ELLIPSIS, false)
  let position = start
  for (let index = first; index <= last; index++) {
    const [tokenStart, tokenEnd] = spans[index] ?? [0, 0]
    if (matched[index]) {
      const joined = index > first && (matched[index - 1] ?? false)
      add(text.slice(position, tokenStart), joined)
      add(text.slice(tokenStart, tokenEnd), true)
      position = tokenEnd
    }
  }
  add(text.slice(position, end), false)
  if (end < text.length) add(ELLIPSIS, false)
  return parts
}

function snippetOf(doc: Doc, terms: readonly Term[]): Schemas['Snippet'] | null {
  for (const [column, source] of SNIPPET_COLUMNS) {
    const parts = snippet(doc.text[column], terms)
    if (parts !== null) return { source, parts }
  }
  return null
}

// --- the reads ----------------------------------------------------------------------------------

function invalid(path: string, message: string): StaticProblem {
  return new StaticProblem(422, 'validation_error', 'Validation error', message, [
    { path, code: 'invalid_value', message },
  ])
}

/** The documents the request's filters keep (`SearchQueries._conditions`), by rowid. */
async function candidates(load: Load, vault: string, params: URLSearchParams) {
  const file = (await load(`vaults/${vault}/static/search`)) as SearchFile
  const kinds = params.getAll('kind')
  const unknown = kinds.find((kind) => !file.kinds.includes(kind))
  if (unknown !== undefined) throw invalid('kind', `Unknown kind '${unknown}'.`)
  const dimension = params.get('dimension')
  const multiversal = params.get('include_multiversal') !== 'false'
  const timeline = params.get('timeline')
  let lineage: string[] | null = null
  if (timeline !== null) {
    const index = (await load(`vaults/${vault}/static/index`)) as IndexFile
    const found = index.timelines[timeline]
    if (found === undefined) {
      throw new StaticProblem(404, 'not_found', 'Not found', `No timeline ${timeline}.`)
    }
    lineage = found.lineage
  }
  const docs = file.docs.filter(
    (doc) =>
      (doc.origin === null || (lineage?.includes(doc.origin) ?? false)) &&
      (kinds.length === 0 || kinds.includes(doc.hit.kind)) &&
      (dimension === null ||
        doc.hit.dimension_id === dimension ||
        (multiversal && doc.hit.dimension_id === null && doc.hit.kind !== 'dimension')),
  )
  return { file, docs }
}

function encodeCursor(offset: number): string {
  return btoa(`{"offset": ${offset}}`).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/u, '')
}

function decodeCursor(cursor: string): number {
  try {
    const raw = atob(cursor.replaceAll('-', '+').replaceAll('_', '/'))
    const offset = (JSON.parse(raw) as { offset?: unknown }).offset
    if (typeof offset === 'number' && Number.isInteger(offset) && offset >= 0) return offset
  } catch {
    // An invalid cursor, below.
  }
  throw invalid('cursor', 'The cursor is invalid.')
}

/** `GET search`: matching documents, best first, with snippets. */
const search: Handler = async (load, _route, params, [vault = '']) => {
  const parser = new Parser(params.get('q') ?? '')
  let node: Node
  try {
    node = parser.parse()
  } catch (error) {
    if (error instanceof ExpressionError) throw invalid('q', error.message)
    throw error
  }
  const offset = params.get('cursor') ? decodeCursor(params.get('cursor') ?? '') : 0
  const limit = Number(params.get('limit') ?? '50')
  const { file, docs } = await candidates(load, vault, params)
  const found = docs.filter((doc) => matches(node, doc, COLUMNS))
  const rank = ranker(parser.phrases, file.docs, file.rows, COLUMNS, WEIGHTS)
  const scores = new Map(found.map((doc) => [doc, rank(doc)]))
  found.sort((a, b) => (scores.get(a) ?? 0) - (scores.get(b) ?? 0) || a.rowid - b.rowid)
  const page = found.slice(offset, offset + limit)
  return {
    items: page.map((doc) => ({ ...doc.hit, snippet: snippetOf(doc, parser.terms) })),
    next_cursor: found.length > offset + limit ? encodeCursor(offset + limit) : null,
  }
}

const QUICK_WORD = /[\p{L}\p{N}_]+/gu

/** SQLite's `length()` of text, Python's `len()`: code points. */
function codePoints(text: string): number {
  return Array.from(text).length
}

/** `_matches`: every typed word starts a word of the text, or the text holds the typed text. */
function quickMatches(text: string, words: readonly string[], needle: string): boolean {
  const folded = fold(text)
  const parts = folded.match(QUICK_WORD) ?? []
  const prefixes = words.every((w) => parts.some((t) => t.startsWith(fold(w))))
  return prefixes || (needle.length >= TRIGRAM_MIN && folded.includes(fold(needle)))
}

/** `GET search/quick`: names or aliases starting with the typed words, then containing it. */
const quick: Handler = async (load, _route, params, [vault = '']) => {
  const q = params.get('q') ?? ''
  const words = q.match(QUICK_WORD) ?? []
  if (words.length === 0) return { items: [] }
  const { file, docs } = await candidates(load, vault, params)
  const terms: Term[] = words
    .slice(0, 16)
    .map((word) => ({ kind: 'term', words: tokens(word), prefix: true }))
  const node: Node = { kind: 'all', included: terms, excluded: [] }
  const weights = { ...WEIGHTS, summary: 0, body_public: 0, fields_public: 0, extra_public: 0 }
  const rank = ranker(terms, file.docs, file.rows, QUICK_COLUMNS, weights)
  const length = (doc: Doc) => codePoints(doc.text.name)
  const found = docs.filter((doc) => matches(node, doc, QUICK_COLUMNS))
  const scores = new Map(found.map((doc) => [doc, rank(doc)]))
  found.sort(
    (a, b) =>
      (scores.get(a) ?? 0) - (scores.get(b) ?? 0) || length(a) - length(b) || a.rowid - b.rowid,
  )
  const shown = found.slice(0, QUICK_LIMIT)
  const needle = q.trim()
  if (shown.length < QUICK_LIMIT && codePoints(needle) >= TRIGRAM_MIN) {
    const sought = fold(needle)
    const substring = docs
      .filter((doc) => QUICK_COLUMNS.some((c) => fold(doc.text[c]).includes(sought)))
      .sort((a, b) => length(a) - length(b) || a.rowid - b.rowid)
      .slice(0, QUICK_LIMIT * 2)
    for (const doc of substring) {
      if (!shown.includes(doc)) shown.push(doc)
      if (shown.length === QUICK_LIMIT) break
    }
  }
  return {
    items: shown.map((doc) => ({
      ...doc.hit,
      alias: quickMatches(doc.text.name, words, needle)
        ? null
        : (doc.text.aliases_public
            .split('\n')
            .find((alias) => alias !== '' && quickMatches(alias, words, needle)) ?? null),
    })),
  }
}

const V = '^vaults/([^/]+)'

/** The search reads of a static export, by route. */
export const SEARCH_HANDLERS: readonly (readonly [RegExp, Handler])[] = [
  [new RegExp(`${V}/search$`), search],
  [new RegExp(`${V}/search/quick$`), quick],
]
