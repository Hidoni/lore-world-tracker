import { Link } from '@tanstack/react-router'
import { lazy, Suspense, useState } from 'react'

import { Label } from '@/components/ui/label'
import { useAsOf, useTimeContext } from '@/core/time'
import { useCharacterFamilyTree, type FamilyTreeQuery, type Genealogy } from '@/data'
import { cn } from '@/lib/utils'

import type { PersonLife } from './lives'
import { usePeopleLives } from './lives'

const FamilyCanvas = lazy(() => import('./family-canvas'))

const SELECT_CLASS =
  'h-8 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
const DEPTHS = [0, 1, 2, 3, 4, 5, 6]

/** The family as text, by generation: each person with their lifespan, parents and spouses. */
export function FamilyList({
  vault,
  family,
  lives,
}: {
  vault: string
  family: Genealogy
  lives: ReadonlyMap<string, PersonLife>
}) {
  const names = new Map(family.people.map((person) => [person.id, person.name]))
  const generations = [...new Set(family.people.map((person) => person.generation))].sort(
    (a, b) => a - b,
  )
  const label = (generation: number) =>
    generation === 0
      ? 'Same generation'
      : `${Math.abs(generation)} ${Math.abs(generation) === 1 ? 'generation' : 'generations'} ${generation < 0 ? 'up' : 'down'}`
  return (
    <div className="flex flex-col gap-3">
      {generations.map((generation) => (
        <section key={generation} aria-label={label(generation)}>
          <h3 className="text-sm font-medium">{label(generation)}</h3>
          <ul className="flex flex-col gap-0.5">
            {family.people
              .filter((person) => person.generation === generation)
              .map((person) => {
                const parents = family.edges
                  .filter((edge) => edge.kind === 'parent' && edge.target_id === person.id)
                  .map((edge) => names.get(edge.source_id))
                const spouses = family.edges
                  .filter(
                    (edge) =>
                      edge.kind === 'spouse' &&
                      (edge.source_id === person.id || edge.target_id === person.id),
                  )
                  .map((edge) =>
                    names.get(edge.source_id === person.id ? edge.target_id : edge.source_id),
                  )
                const life = lives.get(person.id)
                const details =
                  life === undefined || life.state === 'unknown'
                    ? ''
                    : [life.lifespan, life.note].filter(Boolean).join(', ')
                return (
                  <li
                    key={person.id}
                    data-testid="family-list-person"
                    data-existence={life?.state}
                    className={cn(
                      'text-sm',
                      (life?.state === 'deceased' || life?.state === 'unborn') && 'opacity-60',
                      life?.state === 'possible' && 'italic',
                    )}
                  >
                    <Link
                      to="/v/$vault/e/$entity"
                      params={{ vault, entity: person.id }}
                      className="text-primary underline-offset-2 hover:underline"
                    >
                      {person.name}
                    </Link>
                    {details !== '' && <span className="text-muted-foreground"> ({details})</span>}
                    {parents.length > 0 && (
                      <span className="text-muted-foreground">
                        {' '}
                        · child of {parents.join(' and ')}
                      </span>
                    )}
                    {spouses.length > 0 && (
                      <span className="text-muted-foreground">
                        {' '}
                        · spouse of {spouses.join(', ')}
                      </span>
                    )}
                  </li>
                )
              })}
          </ul>
        </section>
      ))}
    </div>
  )
}

/**
 * A character's family tree with its controls (generations up and down, spouses, siblings, "As
 * a list"): the drawing or the list, with lifespans and who is alive at the time cursor. `onRecenter` follows a click on a relative; the controls
 * stay as they are when `character` changes.
 */
export function FamilyTree({
  vault,
  character,
  initialDepth,
  onRecenter,
  onOpen,
  className,
}: {
  vault: string
  character: string
  initialDepth: number
  onRecenter: (id: string) => void
  onOpen: (id: string) => void
  className?: string
}) {
  const { timelineId } = useTimeContext(vault)
  const asOf = useAsOf(vault)
  const [up, setUp] = useState(initialDepth)
  const [down, setDown] = useState(initialDepth)
  const [spouses, setSpouses] = useState(true)
  const [siblings, setSiblings] = useState(true)
  const [asList, setAsList] = useState(false)
  const query: FamilyTreeQuery = {
    up,
    down,
    include_spouses: spouses,
    include_siblings: siblings,
    ...(timelineId === null ? {} : { timeline: timelineId }),
    // At a moment of the cursor: who is alive then.
    ...(asOf ?? {}),
  }
  const tree = useCharacterFamilyTree(vault, character, query)
  const family = tree.data?.root_id === character ? tree.data : undefined
  const lives = usePeopleLives(vault, family)
  const only = (family?.people.length ?? 0) <= 1
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <div className="flex flex-col gap-1">
          <Label htmlFor={`family-up-${character}`}>Generations up</Label>
          <select
            id={`family-up-${character}`}
            className={SELECT_CLASS}
            value={up}
            onChange={(event) => {
              setUp(Number(event.target.value))
            }}
          >
            {DEPTHS.map((depth) => (
              <option key={depth} value={depth}>
                {depth}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor={`family-down-${character}`}>Generations down</Label>
          <select
            id={`family-down-${character}`}
            className={SELECT_CLASS}
            value={down}
            onChange={(event) => {
              setDown(Number(event.target.value))
            }}
          >
            {DEPTHS.map((depth) => (
              <option key={depth} value={depth}>
                {depth}
              </option>
            ))}
          </select>
        </div>
        {(
          [
            ['Spouses', spouses, setSpouses],
            ['Siblings', siblings, setSiblings],
            ['As a list', asList, setAsList],
          ] as const
        ).map(([label, checked, set]) => (
          <label key={label} className="flex h-8 items-center gap-2">
            <input
              type="checkbox"
              checked={checked}
              onChange={(event) => {
                set(event.target.checked)
              }}
            />
            {label}
          </label>
        ))}
      </div>
      {family === undefined ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : only ? (
        <p className="text-sm text-muted-foreground">No family recorded yet.</p>
      ) : asList ? (
        <FamilyList vault={vault} family={family} lives={lives} />
      ) : (
        <figure aria-label="Family tree" className={className ?? 'h-[70vh] rounded-md border'}>
          <Suspense fallback={<p className="p-3 text-sm text-muted-foreground">Loading…</p>}>
            <FamilyCanvas family={family} lives={lives} onRecenter={onRecenter} onOpen={onOpen} />
          </Suspense>
        </figure>
      )}
      {family?.truncated && (
        <p className="text-sm text-muted-foreground">
          The family is larger than the view: lower the generations to see all of it.
        </p>
      )}
    </div>
  )
}
