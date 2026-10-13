import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { lazy, Suspense, useState } from 'react'

import { useTimeContext } from '@/core/time'
import { useSpeciesDescentTree, type DescentTree } from '@/data'

const DescentCanvas = lazy(() => import('./descent-canvas'))

const RELATION: Record<string, string> = {
  descended_from: 'descended from',
  subspecies: 'subspecies of',
}

/** The descent graph as text (the accessible alternative to the drawing). */
function DescentList({ vault, tree }: { vault: string; tree: DescentTree }) {
  const names = new Map(tree.nodes.map((node) => [node.id, node.name]))
  return (
    <ul aria-label="Species" className="flex flex-col gap-1">
      {tree.nodes.map((node) => {
        const relations = tree.edges
          .filter((edge) => edge.source_id === node.id)
          .map((edge) => `${RELATION[edge.kind] ?? edge.kind} ${names.get(edge.target_id) ?? '?'}`)
        return (
          <li key={node.id} data-testid="descent-item" className="text-sm">
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
 * The species descent tree view (`/m/species/descent-tree`): the species of the time context's
 * dimension (and multiversal ones), laid out by descent, with a list alternative.
 */
export default function DescentTreePage() {
  const vault = useParams({ strict: false }).vault ?? ''
  const navigate = useNavigate()
  const { dimensionId } = useTimeContext(vault)
  const tree = useSpeciesDescentTree(vault, dimensionId)
  const [asList, setAsList] = useState(false)
  const data = tree.data
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-6">
      <h1 className="text-2xl font-semibold">Species descent</h1>
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
        <p className="text-sm text-muted-foreground">No species yet.</p>
      ) : asList ? (
        <DescentList vault={vault} tree={data} />
      ) : (
        <figure aria-label="Species descent tree" className="h-[70vh] rounded-md border">
          <Suspense fallback={<p className="p-3 text-sm text-muted-foreground">Loading…</p>}>
            <DescentCanvas
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
