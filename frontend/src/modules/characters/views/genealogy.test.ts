import { describe, expect, it } from 'vitest'

import type { Genealogy } from '@/data'

import { CELL_Y, layoutGenealogy, treeInput, UNKNOWN_PARENT } from './genealogy'

type Edge = Genealogy['edges'][number]

function family(
  root: string,
  people: Record<string, number>,
  edges: [Edge['kind'], string, string, string?][],
): Genealogy {
  return {
    root_id: root,
    people: Object.entries(people).map(([id, generation]) => ({
      id,
      name: id,
      visibility: 'public',
      generation,
      from_t: null,
      to_t: null,
    })),
    edges: edges.map(([kind, source_id, target_id, relation], index) => ({
      id: `l${index}`,
      kind,
      source_id,
      target_id,
      relation: relation ?? null,
    })),
    truncated: false,
  }
}

/** Aldric married Bera (Cyra, Dain) and then Elin (Fenn); Cyra married Gord (Hale). */
const HOUSE = family(
  'cyra',
  { cyra: 0, aldric: -1, bera: -1, elin: -1, dain: 0, fenn: 0, gord: 0, hale: 1 },
  [
    ['spouse', 'aldric', 'bera'],
    ['spouse', 'aldric', 'elin'],
    ['spouse', 'cyra', 'gord'],
    ['parent', 'aldric', 'cyra', 'biological'],
    ['parent', 'bera', 'cyra', 'biological'],
    ['parent', 'aldric', 'dain'],
    ['parent', 'bera', 'dain'],
    ['parent', 'aldric', 'fenn'],
    ['parent', 'elin', 'fenn'],
    ['parent', 'cyra', 'hale'],
    ['parent', 'gord', 'hale'],
  ],
)

function rows(layout: ReturnType<typeof layoutGenealogy>) {
  const byRow = new Map<number, { id: string; x: number }[]>()
  for (const person of layout.people) {
    byRow.set(person.y, [...(byRow.get(person.y) ?? []), person])
  }
  return [...byRow.entries()]
    .sort(([a], [b]) => a - b)
    .map(([, people]) => people.sort((a, b) => a.x - b.x).map((person) => person.id))
}

/** Spouses side by side: same row, nobody between them. */
function adjacent(layout: ReturnType<typeof layoutGenealogy>, a: string, b: string): boolean {
  return rows(layout).some(
    (row) => Math.abs(row.indexOf(a) - row.indexOf(b)) === 1 && row.includes(a),
  )
}

describe('genealogy layout', () => {
  it('puts generations top to bottom and spouses side by side, remarriages too', () => {
    const layout = layoutGenealogy(HOUSE)
    expect(rows(layout)).toEqual([
      expect.arrayContaining(['aldric', 'bera', 'elin']),
      expect.arrayContaining(['cyra', 'gord', 'dain', 'fenn']),
      ['hale'],
    ])
    expect(rows(layout)[0]).toHaveLength(3)
    for (const [a, b] of [
      ['aldric', 'bera'],
      ['aldric', 'elin'],
      ['cyra', 'gord'],
    ] as const) {
      expect(adjacent(layout, a, b)).toBe(true)
    }
    // Rows are a box apart; the lines join them.
    const ys = [...new Set(layout.people.map((person) => person.y))].sort((a, b) => a - b)
    expect((ys[1] ?? 0) - (ys[0] ?? 0)).toBe(2 * CELL_Y)
    expect(layout.lines.length).toBeGreaterThan(5)
  })

  it('keeps siblings without recorded parents together under an unknown parent', () => {
    const input = treeInput(
      family('dain', { dain: 0, ivy: 0, ash: 0 }, [
        ['sibling', 'dain', 'ivy', 'half'],
        ['sibling', 'ivy', 'ash'],
      ]),
    )
    const unknown = input.filter((node) => node.placeholder)
    expect(unknown).toHaveLength(1)
    expect(unknown[0]?.id.startsWith(UNKNOWN_PARENT)).toBe(true)
    expect(unknown[0]?.children.map((child) => child.id).sort()).toEqual(['ash', 'dain', 'ivy'])
    const layout = layoutGenealogy(
      family('dain', { dain: 0, ivy: 0 }, [['sibling', 'dain', 'ivy']]),
    )
    expect(layout.people.map((person) => person.id).sort()).toEqual([
      'dain',
      'ivy',
      `${UNKNOWN_PARENT}0`,
    ])
  })

  it('keeps two parents a person, biological ones first', () => {
    const input = treeInput(
      family('kid', { kid: 0, step: -1, mum: -1, dad: -1 }, [
        ['parent', 'step', 'kid', 'step'],
        ['parent', 'mum', 'kid', 'biological'],
        ['parent', 'dad', 'kid', 'biological'],
      ]),
    )
    expect(input.find((node) => node.id === 'kid')?.parents.map((parent) => parent.id)).toEqual([
      'mum',
      'dad',
    ])
  })

  it('lays out 300 people in well under a second', () => {
    // Six generations of couples with three children each, one in five remarried.
    const people: Record<string, number> = { p0: 0, s0: 0 }
    const edges: [Edge['kind'], string, string, string?][] = [['spouse', 'p0', 's0']]
    let couples = [['p0', 's0']]
    let seq = 1
    for (let generation = 1; Object.keys(people).length < 300; generation++) {
      const next: string[][] = []
      for (const [a = '', b = ''] of couples) {
        for (let k = 0; k < 3; k++) {
          const child = `p${seq++}`
          const spouse = `s${seq++}`
          people[child] = generation
          people[spouse] = generation
          edges.push(['parent', a, child], ['parent', b, child], ['spouse', child, spouse])
          next.push([child, spouse])
        }
        if (seq % 5 === 0) {
          const second = `r${seq++}`
          people[second] = generation - 1
          edges.push(['spouse', a, second])
        }
      }
      couples = next
    }
    const big = family('p0', people, edges)
    const started = performance.now()
    const layout = layoutGenealogy(big)
    const elapsed = performance.now() - started
    expect(layout.people.length).toBeGreaterThanOrEqual(300)
    expect(elapsed).toBeLessThan(1000)
    // Every parent is above each of their children.
    const y = new Map(layout.people.map((person) => [person.id, person.y]))
    for (const edge of big.edges.filter((item) => item.kind === 'parent')) {
      expect(y.get(edge.source_id) ?? Infinity).toBeLessThan(y.get(edge.target_id) ?? -Infinity)
    }
  })
})
