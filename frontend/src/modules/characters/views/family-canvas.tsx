import '@xyflow/react/dist/style.css'

import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import { ExternalLinkIcon } from 'lucide-react'
import { useEffect, useMemo } from 'react'

import type { Genealogy } from '@/data'
import { cn } from '@/lib/utils'

import { layoutGenealogy, NODE_HEIGHT, NODE_WIDTH, type GenealogyLayout } from './genealogy'
import type { PersonLife } from './lives'

type Person = Genealogy['people'][number]
// React Flow's node data is a record (an interface has no index signature).
// eslint-disable-next-line @typescript-eslint/consistent-type-definitions
type PersonData = {
  person: Person | null
  life: PersonLife | null
  root: boolean
  onOpen: (id: string) => void
}
// eslint-disable-next-line @typescript-eslint/consistent-type-definitions
type LinesData = { layout: GenealogyLayout }
type PersonNode = Node<PersonData, 'person'>
type LinesNode = Node<LinesData, 'lines'>

function PersonBox({ data }: NodeProps<PersonNode>) {
  const { person, life, root } = data
  if (person === null) {
    return (
      <div
        data-testid="family-unknown-parent"
        title="Unknown parent"
        className="flex items-center justify-center rounded-md border border-dashed text-xs text-muted-foreground"
        style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
      >
        Unknown parent
      </div>
    )
  }
  const state = life?.state ?? 'unknown'
  const muted = state === 'deceased' || state === 'unborn'
  return (
    <div
      data-testid="family-person"
      data-existence={state}
      title={person.name}
      className={cn(
        'flex cursor-pointer flex-col justify-center gap-0.5 rounded-md border bg-card px-3 shadow-sm',
        root && 'border-primary ring-2 ring-primary/40',
        muted && 'opacity-60',
        state === 'possible' && 'italic',
      )}
      style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
    >
      <div className="flex items-center gap-1">
        <span className="truncate text-sm font-medium">{person.name}</span>
        <button
          type="button"
          aria-label={`Open ${person.name}`}
          className="nodrag ml-auto text-muted-foreground hover:text-foreground"
          onClick={(event) => {
            event.stopPropagation()
            data.onOpen(person.id)
          }}
        >
          <ExternalLinkIcon className="size-3.5" />
        </button>
      </div>
      <span className="truncate text-xs text-muted-foreground" title={life?.note ?? undefined}>
        {[life?.lifespan, life?.note].filter(Boolean).join(' · ')}
      </span>
    </div>
  )
}

/** The family's lines (parents to children, spouses), drawn under the boxes. */
function Lines({ data }: NodeProps<LinesNode>) {
  const { layout } = data
  return (
    <svg
      width={layout.width}
      height={layout.height}
      className="pointer-events-none overflow-visible text-muted-foreground"
      aria-hidden
    >
      {layout.lines.map(([x1, y1, x2, y2], index) => (
        <line key={index} x1={x1} y1={y1} x2={x2} y2={y2} stroke="currentColor" strokeWidth={1.5} />
      ))}
    </svg>
  )
}

const NODE_TYPES = { person: PersonBox, lines: Lines }

function FitOnLayout({ layout }: { layout: unknown }) {
  const flow = useReactFlow()
  useEffect(() => {
    void flow.fitView({ padding: 0.15, maxZoom: 1.25 })
  }, [flow, layout])
  return null
}

/**
 * The family tree drawn with React Flow and laid out by relatives-tree (the #93 spike): the
 * generations top to bottom, spouses side by side (every marriage), the character highlighted.
 * Clicking a person re-centers on them; the icon opens their page. Each box shows the person's
 * lifespan, muted when they aren't alive at the time cursor. Loaded lazily.
 */
export default function FamilyCanvas({
  family,
  lives,
  onRecenter,
  onOpen,
}: {
  family: Genealogy
  /** Each person's lifespan and state at the time cursor (`lives.ts`). */
  lives: ReadonlyMap<string, PersonLife>
  onRecenter: (id: string) => void
  onOpen: (id: string) => void
}) {
  const layout = useMemo(() => layoutGenealogy(family), [family])
  const people = useMemo(
    () => new Map(family.people.map((person) => [person.id, person])),
    [family],
  )
  const nodes = useMemo<(PersonNode | LinesNode)[]>(
    () => [
      {
        id: '__lines',
        type: 'lines',
        position: { x: 0, y: 0 },
        data: { layout },
        draggable: false,
        selectable: false,
        focusable: false,
        zIndex: -1,
      },
      ...layout.people.map((placed): PersonNode => ({
        id: placed.id,
        type: 'person',
        position: { x: placed.x, y: placed.y },
        data: {
          person: people.get(placed.id) ?? null,
          life: lives.get(placed.id) ?? null,
          root: placed.id === family.root_id,
          onOpen,
        },
        draggable: false,
        connectable: false,
        ariaLabel: people.get(placed.id)?.name ?? 'Unknown parent',
      })),
    ],
    [layout, people, lives, family.root_id, onOpen],
  )
  return (
    <ReactFlowProvider>
      <ReactFlow
        nodes={nodes}
        edges={[]}
        nodeTypes={NODE_TYPES}
        nodesDraggable={false}
        nodesConnectable={false}
        minZoom={0.05}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => {
          if (node.type === 'person' && people.has(node.id) && node.id !== family.root_id) {
            onRecenter(node.id)
          }
        }}
      >
        <FitOnLayout layout={layout} />
        <Background gap={24} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </ReactFlowProvider>
  )
}
