import type { LexiconDefinition as Definition, LexiconEntry, LexiconEntryUpdate } from '@/data'

/** Suggested parts of speech (free text; docs/modules/languages.md). */
export const PARTS_OF_SPEECH = [
  'noun',
  'verb',
  'adjective',
  'adverb',
  'pronoun',
  'preposition',
  'conjunction',
  'interjection',
  'particle',
  'numeral',
  'affix',
  'phrase',
  'other',
] as const

/** The columns the table edits inline, in order. */
export const COLUMNS = [
  { key: 'headword', title: 'Headword' },
  { key: 'romanization', title: 'Romanization' },
  { key: 'pronunciation', title: 'Pronunciation' },
  { key: 'part_of_speech', title: 'Part of speech' },
  { key: 'glosses', title: 'Glosses' },
  { key: 'tags', title: 'Tags' },
] as const

export type ColumnKey = (typeof COLUMNS)[number]['key']

/** The glosses as one line: `the sea; a lake`. */
export function glossText(definitions: readonly Definition[]): string {
  return definitions.map((definition) => definition.gloss).join('; ')
}

/**
 * Glosses typed as one line (`;` between them) as definitions: a definition keeps its notes and
 * examples while it stays at its position.
 */
export function definitionsFrom(text: string, previous: readonly Definition[]): Definition[] {
  return text
    .split(';')
    .map((gloss) => gloss.trim())
    .filter((gloss) => gloss !== '')
    .map((gloss, index) => ({ ...previous[index], gloss }))
}

/** Tags typed as one line (`,` between them). */
export function tagsFrom(text: string): string[] {
  return [
    ...new Set(
      text
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean),
    ),
  ]
}

/** A column's text in the table. */
export function cellText(entry: LexiconEntry, key: ColumnKey): string {
  switch (key) {
    case 'glosses':
      return glossText(entry.definitions)
    case 'tags':
      return entry.tags.join(', ')
    default:
      return entry[key] ?? ''
  }
}

/**
 * The update a column's edited text makes (`null`: nothing to save, e.g. an empty headword or the
 * same text).
 */
export function columnChange(
  entry: LexiconEntry,
  key: ColumnKey,
  text: string,
): LexiconEntryUpdate | null {
  const value = text.trim()
  if (value === cellText(entry, key).trim()) return null
  const base = { revision: entry.revision }
  switch (key) {
    case 'headword':
      return value === '' ? null : { ...base, headword: value }
    case 'glosses':
      return { ...base, definitions: definitionsFrom(value, entry.definitions) }
    case 'tags':
      return { ...base, tags: tagsFrom(value) }
    default:
      return { ...base, [key]: value === '' ? null : value }
  }
}

/** The headers of a CSV's first line (quoted headers may hold commas and `""`). */
export function csvHeaders(csv: string): string[] {
  const headers: string[] = []
  let current = ''
  let quoted = false
  const text = csv.replace(/^\uFEFF/, '')
  for (let index = 0; index < text.length; index++) {
    const char = text.charAt(index)
    if (quoted) {
      if (char === '"' && text.charAt(index + 1) === '"') {
        current += '"'
        index++
      } else if (char === '"') {
        quoted = false
      } else {
        current += char
      }
    } else if (char === '"') {
      quoted = true
    } else if (char === ',') {
      headers.push(current.trim())
      current = ''
    } else if (char === '\n' || char === '\r') {
      break
    } else {
      current += char
    }
  }
  headers.push(current.trim())
  return headers.filter((header, index) => header !== '' || index < headers.length - 1)
}

/** The fields a CSV column can fill (the import's mapping). */
export const IMPORT_FIELDS = [
  'headword',
  'romanization',
  'pronunciation',
  'part_of_speech',
  'definitions',
  'tags',
  'etymology',
  'notes',
] as const
