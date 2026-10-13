import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { lazy, Suspense, useState } from 'react'

import { useTimeContext } from '@/core/time'
import { useLanguageFamilyTree, type FamilyTree } from '@/data'

const FamilyCanvas = lazy(() => import('./family-canvas'))

const RELATION: Record<string, string> = {
  descended_from: 'descended from',
  borrowed_from: 'borrows from',
  dialect: 'dialect of',
}

/** The family graph as text: each language with what it descends from, borrows from or is a
 * dialect of (the accessible alternative to the drawing). */
function FamilyList({ vault, tree }: { vault: string; tree: FamilyTree }) {
  const names = new Map(tree.nodes.map((node) => [node.id, node.name]))
  return (
    <ul aria-label="Languages" className="flex flex-col gap-1">
      {tree.nodes.map((node) => {
        const relations = tree.edges
          .filter((edge) => edge.source_id === node.id)
          .map((edge) => `${RELATION[edge.kind] ?? edge.kind} ${names.get(edge.target_id) ?? '?'}`)
        return (
          <li key={node.id} data-testid="family-item" className="text-sm">
            <Link
              to="/v/$vault/e/$entity"
              params={{ vault, entity: node.id }}
              className="text-primary underline-offset-2 hover:underline"
            >
              {node.name}
            </Link>
            {relations.length > 0 && (
              <span className="text-muted-foreground"> · {relations.join(' · ')}</span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

/**
 * The language family tree view (`/m/languages/family-tree`): the languages of the time
 * context's dimension (and multiversal ones), laid out by descent, with a list alternative.
 */
export default function FamilyTreePage() {
  const vault = useParams({ strict: false }).vault ?? ''
  const navigate = useNavigate()
  const { dimensionId } = useTimeContext(vault)
  const tree = useLanguageFamilyTree(vault, dimensionId)
  const [asList, setAsList] = useState(false)
  const data = tree.data
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-6">
      <h1 className="text-2xl font-semibold">Language family tree</h1>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={asList}
          onChange={(event) => {
            setAsList(event.target.checked)
          }}
        />
        As a list
      </label>
      {data === undefined ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : data.nodes.length === 0 ? (
        <p className="text-sm text-muted-foreground">No languages yet.</p>
      ) : asList ? (
        <FamilyList vault={vault} tree={data} />
      ) : (
        <figure aria-label="Language family tree" className="h-[70vh] rounded-md border">
          <Suspense fallback={<p className="p-3 text-sm text-muted-foreground">Loading…</p>}>
            <FamilyCanvas
              tree={data}
              onOpen={(id) => {
                void navigate({ to: '/v/$vault/e/$entity', params: { vault, entity: id } })
              }}
            />
          </Suspense>
        </figure>
      )}
      {data?.truncated && (
        <p className="text-xs text-muted-foreground">Showing the first {data.nodes.length}.</p>
      )}
    </div>
  )
}
