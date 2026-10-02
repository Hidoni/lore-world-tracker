/**
 * Format pattern tokens (chronology-engine.md §3.11): parsing and validation. Rendering arrives with
 * formatting (#25); compilation only checks that every token is known.
 */

// Groups: level, attribute, modifier.
const TOKEN = /^([a-z][a-z0-9_]*)(?:\.(name|abbr|id))?(?::(pad2|pad3|ordinal))?$/
// Groups: cycle id, overlay id.
const SPECIAL =
  /^(?:era(?:\.name)?|cycle\.([a-z][a-z0-9_]*)(?:\.(?:abbr|n))?|overlay\.([a-z][a-z0-9_]*)(?:\.fraction)?)$/
const NUMERIC_TOKENS = new Set(['year', 'era_year', 'base'])

/** A pattern with unbalanced braces. */
export class PatternError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'PatternError'
  }
}

/** The tokens (text between single braces) of a pattern; `{{` and `}}` are literal braces. */
export function patternTokens(pattern: string): string[] {
  const found: string[] = []
  let i = 0
  while (i < pattern.length) {
    const char = pattern[i]
    const pair = pattern.slice(i, i + 2)
    if (pair === '{{' || pair === '}}') {
      i += 2
    } else if (char === '{') {
      const end = pattern.indexOf('}', i)
      if (end < 0) throw new PatternError("unclosed '{'")
      found.push(pattern.slice(i + 1, end))
      i = end + 1
    } else if (char === '}') {
      throw new PatternError("unmatched '}'")
    } else {
      i += 1
    }
  }
  return found
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
  return found.filter((token) => !known(token, scope))
}

function known(token: string, scope: TokenScope): boolean {
  const special = SPECIAL.exec(token)
  if (special !== null) {
    const [, cycle, overlay] = special
    if (cycle !== undefined) return scope.cycles.has(cycle)
    if (overlay !== undefined) return scope.overlays.has(overlay)
    return true
  }
  const match = TOKEN.exec(token)
  if (match === null) return false
  const [, level = '', attr, modifier] = match
  if (NUMERIC_TOKENS.has(level)) return attr === undefined
  return scope.levels.has(level) && (attr === undefined || modifier === undefined)
}
