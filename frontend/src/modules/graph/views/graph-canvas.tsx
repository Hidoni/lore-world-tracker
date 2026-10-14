import Graph from 'graphology'
import forceAtlas2 from 'graphology-layout-forceatlas2'
import FA2Layout from 'graphology-layout-forceatlas2/worker'
import { PauseIcon, PlayIcon, SnowflakeIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import Sigma from 'sigma'

import { Button } from '@/components/ui/button'

import type { Positions } from '../filters'
import { LinkDrag, RecentDrag } from '../link-drag'

export interface CanvasNode {
  id: string
  label: string
  color: string
  size: number
}

export interface CanvasEdge {
  source: string
  target: string
  color: string
  size: number
}

const DIMMED = '#cbd5e1'
/**
 * Above this many edges a graph is large: hovering highlights the neighborhood without dimming the
 * rest, so that only the neighborhood is redrawn (dimming means running the reducers over every
 * node and edge: a visible stall at 10k nodes). Edges stay drawn while the camera moves: sigma's
 * `hideEdgesOnMove` fully refreshes the graph after every drag, a worse stall.
 */
const LARGE_GRAPH_EDGES = 2000

/** Where a node starts without a cached position: on a spiral, so the layout untangles fast. */
function seed(index: number): [number, number] {
  const angle = index * 2.399963 // the golden angle
  const radius = 10 * Math.sqrt(index + 1)
  return [radius * Math.cos(angle), radius * Math.sin(angle)]
}

/** Why the graph can't be drawn here (no WebGL), or `null`. */
function webglMissing(): string | null {
  try {
    const canvas = document.createElement('canvas')
    const context: unknown = canvas.getContext('webgl2') ?? canvas.getContext('webgl')
    return context ? null : 'this browser has no WebGL'
  } catch {
    return 'this browser has no WebGL'
  }
}

/** How long a fresh layout runs before it stops by itself (bigger graphs take longer). */
function layoutBudget(nodes: number): number {
  return Math.min(2000 + nodes, 15_000)
}

/**
 * The graph drawn with sigma.js (WebGL) over a graphology graph, laid out by ForceAtlas2 in a web
 * worker (docs/modules/graph.md, UI). Positions come from `positions` when known; otherwise the
 * layout runs for a while and reports where it left the nodes (`onPositions`). Hovering a node
 * highlights its neighbors, `highlighted` (search) dims the rest, a click selects, a double click
 * opens. Loaded lazily with the graph page.
 */
export default function GraphCanvas({
  nodes,
  edges,
  positions,
  highlighted,
  selected,
  onSelect,
  onOpen,
  onPositions,
  onLink,
}: {
  nodes: readonly CanvasNode[]
  edges: readonly CanvasEdge[]
  positions: Positions
  highlighted: ReadonlySet<string> | null
  selected: string | null
  onSelect: (id: string | null) => void
  onOpen: (id: string) => void
  onPositions: (positions: Positions) => void
  /** `Alt`+drag from a node to another (visual linking); off without it. */
  onLink?: (source: string, target: string) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const sigma = useRef<Sigma | null>(null)
  const layout = useRef<FA2Layout | null>(null)
  const state = useRef({
    hovered: null as string | null,
    linking: null as string | null,
    highlighted,
    selected,
  })
  const callbacks = useRef({ onSelect, onOpen, onPositions, onLink })
  useEffect(() => {
    callbacks.current = { onSelect, onOpen, onPositions, onLink }
  })
  const [running, setRunning] = useState(false)
  const [failed] = useState(webglMissing)

  const save = (): void => {
    const graph = sigma.current?.getGraph()
    if (graph === undefined) return
    const found: Positions = {}
    graph.forEachNode((node, attributes) => {
      found[node] = [attributes.x as number, attributes.y as number]
    })
    callbacks.current.onPositions(found)
  }

  const stop = (): void => {
    if (layout.current?.isRunning() === true) {
      layout.current.stop()
      save()
    }
    setRunning(false)
  }

  // A new graph: rebuilt, drawn, and laid out unless every node has a position.
  useEffect(() => {
    if (container.current === null) return
    const graph = new Graph({ multi: true, type: 'directed', allowSelfLoops: false })
    let missing = 0
    nodes.forEach((node, index) => {
      const known = positions[node.id]
      if (known === undefined) missing += 1
      const [x, y] = known ?? seed(index)
      graph.addNode(node.id, { x, y, size: node.size, color: node.color, label: node.label })
    })
    for (const edge of edges) {
      if (graph.hasNode(edge.source) && graph.hasNode(edge.target)) {
        graph.addEdge(edge.source, edge.target, { color: edge.color, size: edge.size })
      }
    }
    const large = graph.size > LARGE_GRAPH_EDGES
    let renderer: Sigma
    try {
      renderer = new Sigma(graph, container.current, {
        labelRenderedSizeThreshold: 6,
        zIndex: true,
        nodeReducer: (node, data) => {
          const { hovered, highlighted, selected } = state.current
          const near = hovered === null || node === hovered || graph.areNeighbors(node, hovered)
          const found = highlighted === null || highlighted.has(node)
          if (node === selected || node === state.current.linking) {
            return { ...data, highlighted: true, zIndex: 2 }
          }
          if ((!near && !large) || !found) return { ...data, color: DIMMED, label: '', zIndex: 0 }
          return { ...data, zIndex: 1, forceLabel: hovered !== null && near }
        },
        edgeReducer: (edge, data) => {
          const { hovered } = state.current
          if (hovered === null) return data
          if (graph.hasExtremity(edge, hovered)) return { ...data, size: Number(data.size) + 1 }
          return large ? data : { ...data, hidden: true }
        },
      })
    } catch (error) {
      console.error('the graph could not be drawn', error)
      return
    }
    sigma.current = renderer
    // A large graph redraws only the neighborhoods the hover leaves and enters.
    const hover = (node: string | null): void => {
      const previous = state.current.hovered
      state.current.hovered = node
      if (!large) {
        renderer.refresh({ skipIndexation: true })
        return
      }
      const nodes = new Set<string>()
      const edges = new Set<string>()
      for (const center of [previous, node]) {
        if (center === null || !graph.hasNode(center)) continue
        nodes.add(center)
        graph.forEachNeighbor(center, (neighbor) => nodes.add(neighbor))
        graph.forEachEdge(center, (edge) => edges.add(edge))
      }
      renderer.refresh({
        partialGraph: { nodes: [...nodes], edges: [...edges] },
        skipIndexation: true,
      })
    }
    renderer.on('enterNode', ({ node }) => {
      hover(node)
    })
    renderer.on('leaveNode', () => {
      hover(null)
    })
    renderer.on('clickNode', ({ node }) => {
      callbacks.current.onSelect(node)
    })
    renderer.on('clickStage', () => {
      callbacks.current.onSelect(null)
    })
    // Alt+drag from a node to another: the camera holds still, and the release asks for a link.
    const drag = new LinkDrag()
    const endDrag = (): void => {
      state.current.linking = null
      renderer.getCamera().enable()
      if (container.current !== null) container.current.style.cursor = ''
      renderer.refresh({ skipIndexation: true })
    }
    renderer.on('downNode', ({ node, event }) => {
      if (callbacks.current.onLink !== undefined && drag.down(node, event.original.altKey)) {
        state.current.linking = node
        renderer.getCamera().disable()
        if (container.current !== null) container.current.style.cursor = 'crosshair'
        renderer.refresh({ skipIndexation: true })
      }
    })
    renderer.on('upNode', ({ node }) => {
      if (!drag.active) return
      const ends = drag.up(node)
      endDrag()
      if (ends !== null) callbacks.current.onLink?.(...ends)
    })
    renderer.getMouseCaptor().on('mouseup', () => {
      // Released off a node (upNode, when it fires, comes first).
      setTimeout(() => {
        if (drag.active) {
          drag.up(null)
          endDrag()
        }
      }, 0)
    })
    const recent = new RecentDrag()
    renderer.getMouseCaptor().on('mousemovebody', (event) => {
      recent.move('buttons' in event.original && event.original.buttons !== 0, performance.now())
    })
    renderer.on('doubleClickNode', (event) => {
      event.preventSigmaDefault()
      // Two quick drag releases aren't a double click.
      if (!recent.dragged(performance.now())) callbacks.current.onOpen(event.node)
    })
    const timers: ReturnType<typeof setTimeout>[] = []
    if (graph.order > 1 && graph.size > 0) {
      const fa2 = new FA2Layout(graph, { settings: forceAtlas2.inferSettings(graph) })
      layout.current = fa2
      if (missing > 0) {
        // Started after this render; stopped by itself after a while, keeping the positions.
        timers.push(
          setTimeout(() => {
            fa2.start()
            setRunning(true)
          }, 0),
          setTimeout(() => {
            if (fa2.isRunning()) {
              fa2.stop()
              setRunning(false)
              save()
            }
          }, layoutBudget(graph.order)),
        )
      }
    }
    return () => {
      timers.forEach(clearTimeout)
      layout.current?.kill()
      layout.current = null
      renderer.kill()
      sigma.current = null
      setRunning(false)
    }
    // Positions are read when the graph changes, not on every report of them.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges])

  // Search highlights and the selection redraw without a new layout; one match is centered.
  useEffect(() => {
    state.current.highlighted = highlighted
    state.current.selected = selected
    const renderer = sigma.current
    if (renderer === null) return
    renderer.refresh({ skipIndexation: true })
    const focus = selected ?? (highlighted?.size === 1 ? [...highlighted][0] : undefined)
    if (focus !== undefined && renderer.getGraph().hasNode(focus)) {
      const display = renderer.getNodeDisplayData(focus)
      if (display !== undefined) {
        void renderer
          .getCamera()
          .animate({ x: display.x, y: display.y, ratio: 0.5 }, { duration: 400 })
      }
    }
  }, [highlighted, selected])

  if (failed !== null) {
    return (
      <p role="alert" className="p-4 text-sm text-muted-foreground">
        The graph can’t be drawn: {failed}. “As a list” shows it as text.
      </p>
    )
  }
  return (
    <div className="relative h-full w-full">
      <div ref={container} className="h-full w-full" data-testid="graph-canvas" />
      <div className="absolute top-2 right-2 flex gap-1 rounded-md border bg-background/90 p-1">
        <Button
          variant="ghost"
          size="sm"
          aria-label={running ? 'Stop the layout' : 'Run the layout'}
          onClick={() => {
            if (running) {
              stop()
            } else if (layout.current !== null) {
              layout.current.start()
              setRunning(true)
            }
          }}
        >
          {running ? <PauseIcon aria-hidden /> : <PlayIcon aria-hidden />}
          {running ? 'Stop' : 'Layout'}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          title="Stop the layout and keep these positions for next time"
          onClick={() => {
            stop()
            save()
          }}
        >
          <SnowflakeIcon aria-hidden /> Freeze
        </Button>
      </div>
    </div>
  )
}
