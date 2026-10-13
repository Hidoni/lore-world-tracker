import calcTree from 'relatives-tree'
import type { Node as TreeNode, RelData } from 'relatives-tree/lib/types'

import type { Genealogy } from '@/data'

/** A person's box (pixels) and the grid relatives-tree lays out on: a box spans 2 × 2 cells. */
export const NODE_WIDTH = 180
export const NODE_HEIGHT = 64
export const CELL_X = 100
export const CELL_Y = 64

/** An unknown parent added so that siblings without recorded parents stay together. */
export const UNKNOWN_PARENT = 'unknown-parent:'

export interface PlacedPerson {
  id: string
  x: number
  y: number
  /** An unknown parent (not a person of the tree). */
  placeholder: boolean
}

export interface GenealogyLayout {
  people: PlacedPerson[]
  /** Lines in pixels: `[x1, y1, x2, y2]`. */
  lines: (readonly [number, number, number, number])[]
  width: number
  height: number
}

interface Relation {
  id: string
  type: string
}
interface Draft {
  id: string
  gender: 'male' | 'female'
  parents: Relation[]
  children: Relation[]
  siblings: Relation[]
  spouses: Relation[]
  placeholder?: boolean
}

const PARENT_TYPE: Record<string, string> = {
  adoptive: 'adopted',
  foster: 'adopted',
  step: 'adopted',
}

/**
 * The family as relatives-tree's input: parents, children, siblings and spouses on both sides,
 * at most two parents a person (biological ones first), spouses' genders alternated (it puts
 * one on each side), and an unknown parent for siblings without recorded parents.
 */
export function treeInput(family: Genealogy): Draft[] {
  const people = new Map<string, Draft>(
    family.people.map((person) => [
      person.id,
      { id: person.id, gender: 'male', parents: [], children: [], siblings: [], spouses: [] },
    ]),
  )
  const parentEdges = family.edges
    .filter((edge) => edge.kind === 'parent')
    .sort((a, b) => Number(a.relation !== 'biological') - Number(b.relation !== 'biological'))
  for (const edge of parentEdges) {
    const parent = people.get(edge.source_id)
    const child = people.get(edge.target_id)
    if (!parent || !child || child.parents.length >= 2) continue
    if (child.parents.some((item) => item.id === parent.id)) continue
    const type = PARENT_TYPE[edge.relation ?? ''] ?? 'blood'
    child.parents.push({ id: parent.id, type })
    parent.children.push({ id: child.id, type })
  }
  for (const edge of family.edges) {
    const a = people.get(edge.source_id)
    const b = people.get(edge.target_id)
    if (!a || !b || a === b) continue
    if (edge.kind === 'spouse' && !a.spouses.some((item) => item.id === b.id)) {
      a.spouses.push({ id: b.id, type: 'married' })
      b.spouses.push({ id: a.id, type: 'married' })
    }
    if (edge.kind === 'sibling' && !a.siblings.some((item) => item.id === b.id)) {
      const type = edge.relation === 'half' ? 'half' : 'blood'
      a.siblings.push({ id: b.id, type })
      b.siblings.push({ id: a.id, type })
    }
  }
  // Siblings are drawn through their parents: a sibling without recorded parents joins the
  // other's (or, when neither has any, a shared unknown parent).
  let unknown = 0
  for (const person of people.values()) {
    for (const sibling of person.siblings) {
      const other = people.get(sibling.id)
      if (!other || other.parents.length > 0) continue
      if (person.parents.length === 0) {
        const placeholder: Draft = {
          id: `${UNKNOWN_PARENT}${unknown++}`,
          gender: 'male',
          parents: [],
          children: [],
          siblings: [],
          spouses: [],
          placeholder: true,
        }
        people.set(placeholder.id, placeholder)
        placeholder.children.push({ id: person.id, type: 'blood' })
        person.parents.push({ id: placeholder.id, type: 'blood' })
      }
      for (const parent of person.parents) {
        people.get(parent.id)?.children.push({ id: other.id, type: sibling.type })
        other.parents.push({ id: parent.id, type: sibling.type })
      }
    }
  }
  // Spouses on opposite sides: two-color the marriages.
  const colored = new Set<string>()
  for (const start of people.values()) {
    if (colored.has(start.id)) continue
    colored.add(start.id)
    const queue = [start]
    for (let person = queue.shift(); person; person = queue.shift()) {
      for (const spouse of person.spouses) {
        const other = people.get(spouse.id)
        if (!other || colored.has(other.id)) continue
        other.gender = person.gender === 'male' ? 'female' : 'male'
        colored.add(other.id)
        queue.push(other)
      }
    }
  }
  return [...people.values()]
}

/** Lays the family out around its root: generations top to bottom, spouses side by side. */
export function layoutGenealogy(family: Genealogy): GenealogyLayout {
  const input = treeInput(family)
  // The library's types are const enums; the values are the same strings.
  const data: RelData = calcTree(input as unknown as TreeNode[], { rootId: family.root_id })
  const placeholders = new Set(input.filter((node) => node.placeholder).map((node) => node.id))
  return {
    people: data.nodes.map((node) => ({
      id: node.id,
      x: node.left * CELL_X + (2 * CELL_X - NODE_WIDTH) / 2,
      y: node.top * CELL_Y + (2 * CELL_Y - NODE_HEIGHT) / 2,
      placeholder: placeholders.has(node.id),
    })),
    lines: data.connectors.map(
      ([x1, y1, x2, y2]) => [x1 * CELL_X, y1 * CELL_Y, x2 * CELL_X, y2 * CELL_Y] as const,
    ),
    width: data.canvas.width * CELL_X,
    height: data.canvas.height * CELL_Y,
  }
}
