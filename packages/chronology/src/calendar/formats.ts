/**
 * Format pattern tokens (chronology-engine.md §3.11): parsing and validation. Compilation checks
 * that every token is known; `formatting` renders parsed patterns. The Python twin is
 * backend/src/lore/chronology/calendar/formats.py.
 */

// Groups: level, attribute, modifier.
const TOKEN = /^([a-z][a-z0-9_]*)(?:\.(name|abbr|id))?(?::(pad2|pad3|ordinal))?$/
// Groups: era attribute, cycle id, cycle attribute, overlay id, overlay attribute.
const SPECIAL =
  /^(?:era(?:\.(name))?|cycle\.([a-z][a-z0-9_]*)(?:\.(abbr|n))?|overlay\.([a-z][a-z0-9_]*)(?:\.(fraction))?)$/
const NUMERIC_KINDS = new Set(['year', 'era_year', 'base'] as const)

export type TokenKind = 'level' | 'year' | 'era_year' | 'base' | 'era' | 'cycle' | 'overlay'
export type Modifier = 'pad2' | 'pad3' | 'ordinal'

/** A parsed token: `{<id>.<attr>:<modifier>}` of some `kind`. */
export interface Token {
  readonly kind: TokenKind
  /** The level, cycle or overlay id (`null` for `year`, `era_year`, `base`, `era`). */
  readonly id: string | null
  /** `name`/`abbr`/`id` (levels), `name` (era), `abbr`/`n` (cycles), `fraction` (overlays). */
  readonly attr: string | null
  readonly modifier: Modifier | null
}

/** A literal text (braces unescaped) or a token. */
export type Piece = string | Token

export function token(
  kind: TokenKind,
  id: string | null = null,
  attr: string | null = null,
  modifier: Modifier | null = null,
): Token {
  return { kind, id, attr, modifier }
}

/** A pattern with unbalanced braces or an unknown token. */
export class PatternError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'PatternError'
  }
}

/** [isToken, text] pieces; `{{` and `}}` become literal braces. */
function split(pattern: string): [boolean, string][] {
  const pieces: [boolean, string][] = []
  let literal = ''
  let i = 0
  while (i < pattern.length) {
    const char = pattern.charAt(i)
    const pair = pattern.slice(i, i + 2)
    if (pair === '{{' || pair === '}}') {
      literal += char
      i += 2
    } else if (char === '{') {
      const end = pattern.indexOf('}', i)
      if (end < 0) throw new PatternError("unclosed '{'")
      if (literal !== '') pieces.push([false, literal])
      literal = ''
      pieces.push([true, pattern.slice(i + 1, end)])
      i = end + 1
    } else if (char === '}') {
      throw new PatternError("unmatched '}'")
    } else {
      literal += char
      i += 1
    }
  }
  if (literal !== '') pieces.push([false, literal])
  return pieces
}

/** The tokens (text between single braces) of a pattern; `{{` and `}}` are literal braces. */
export function patternTokens(pattern: string): string[] {
  return split(pattern).flatMap(([isToken, text]) => (isToken ? [text] : []))
}

/** The structure of a token, or `null` if it has no valid syntax (ids are not checked). */
export function parseToken(text: string): Token | null {
  const special = SPECIAL.exec(text)
  if (special !== null) {
    const [, eraAttr, cycle, cycleAttr, overlay, overlayAttr] = special
    const kind = cycle !== undefined ? 'cycle' : overlay !== undefined ? 'overlay' : 'era'
    return token(kind, cycle ?? overlay ?? null, eraAttr ?? cycleAttr ?? overlayAttr ?? null)
  }
  const match = TOKEN.exec(text)
  if (match === null) return null
  const [, level = '', attr] = match
  const modifier = match[3] as Modifier | undefined // the regex only matches modifiers
  const numeric = NUMERIC_KINDS.has(level as 'year')
  // modifiers apply to numbers, and the numeric tokens have no attributes
  if (attr !== undefined && (modifier !== undefined || numeric)) return null
  if (numeric) return token(level as TokenKind, null, null, modifier ?? null)
  return token('level', level, attr ?? null, modifier ?? null)
}

/** The pieces of a valid pattern. Throws `PatternError` for bad braces or tokens. */
export function parsePattern(pattern: string): Piece[] {
  return split(pattern).map(([isToken, text]) => {
    if (!isToken) return text
    const parsed = parseToken(text)
    if (parsed === null) throw new PatternError(`unknown token ${text}`)
    return parsed
  })
}

export interface TokenScope {
  readonly levels: ReadonlySet<string>
  readonly cycles: ReadonlySet<string>
  readonly overlays: ReadonlySet<string>
}

/** Tokens of `pattern` that are not valid for this calendar (`['{']` for unbalanced braces). */
export function unknownTokens(pattern: string, scope: TokenScope): string[] {
  let found: string[]
  try {
    found = patternTokens(pattern)
  } catch {
    return ['{'] // the only error is a PatternError
  }
  return found.filter((text) => !known(parseToken(text), scope))
}

function known(parsed: Token | null, scope: TokenScope): boolean {
  if (parsed === null) return false
  const id = parsed.id ?? ''
  if (parsed.kind === 'cycle') return scope.cycles.has(id)
  if (parsed.kind === 'overlay') return scope.overlays.has(id)
  if (parsed.kind === 'level') return scope.levels.has(id)
  return true
}
