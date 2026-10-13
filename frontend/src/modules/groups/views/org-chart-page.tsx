import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { lazy, Suspense, useState } from 'react'

import { Label } from '@/components/ui/label'
import { useTimeContext } from '@/core/time'
import { useEntity, useGroupOrgChart, type OrgChart } from '@/data'

import { leadersText, membersText } from './org-canvas'

const OrgCanvas = lazy(() => import('./org-canvas'))

const SELECT_CLASS =
  'h-8 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'

/** The org chart as an indented list: each unit with its leaders and member count. */
function OrgList({ vault, chart }: { vault: string; chart: OrgChart }) {
  return (
    <ul aria-label="Units" className="flex flex-col gap-1">
      {chart.units.map((unit) => {
        const leaders = leadersText(unit)
        return (
          <li
            key={unit.id}
            data-testid="org-item"
            className="text-sm"
            style={{ paddingLeft: `${unit.depth * 1.5}rem` }}
          >
            <Link
              to="/v/$vault/e/$entity"
              params={{ vault, entity: unit.id }}
              className="text-primary underline-offset-2 hover:underline"
            >
              {unit.name}
            </Link>
            <span className="text-muted-foreground">
              {unit.via === 'part_of' && ' (part)'}
              {leaders && ` · led by ${leaders}`} · {membersText(unit.member_count)}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

/**
 * The org chart view of a group (`/m/groups/<group>/org-chart`): its sub-groups and parts with
 * their leaders and member counts, as of the time cursor (once links carry validity, M7).
 */
export default function OrgChartPage() {
  // Module routes aren't in the router's generated types.
  const params: { vault?: string; group?: string } = useParams({ strict: false })
  const vault = params.vault ?? ''
  const group = params.group ?? ''
  const navigate = useNavigate()
  const entity = useEntity(vault, group)
  const { timelineId, moment } = useTimeContext(vault)
  const [depth, setDepth] = useState(3)
  const [asList, setAsList] = useState(false)
  const chart = useGroupOrgChart(vault, group, {
    depth,
    ...(timelineId !== null && moment !== null
      ? { timeline: timelineId, at: moment.toString() }
      : {}),
  })
  const data = chart.data?.root_id === group ? chart.data : undefined
  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">
          Org chart{entity.data ? ` of ${entity.data.name}` : ''}
        </h1>
        {entity.data && (
          <Link
            to="/v/$vault/e/$entity"
            params={{ vault, entity: group }}
            className="text-sm text-primary underline-offset-2 hover:underline"
          >
            Back to {entity.data.name}
          </Link>
        )}
      </header>
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <div className="flex flex-col gap-1">
          <Label htmlFor="org-depth">Levels</Label>
          <select
            id="org-depth"
            className={SELECT_CLASS}
            value={depth}
            onChange={(event) => {
              setDepth(Number(event.target.value))
            }}
          >
            {[1, 2, 3, 4, 5, 6].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
        <label className="flex h-8 items-center gap-2">
          <input
            type="checkbox"
            checked={asList}
            onChange={(event) => {
              setAsList(event.target.checked)
            }}
          />
          As a list
        </label>
      </div>
      {entity.isError || chart.isError ? (
        <p className="text-muted-foreground">This group was not found.</p>
      ) : data === undefined ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : asList ? (
        <OrgList vault={vault} chart={data} />
      ) : (
        <figure aria-label="Org chart" className="h-[70vh] rounded-md border">
          <Suspense fallback={<p className="p-3 text-sm text-muted-foreground">Loading…</p>}>
            <OrgCanvas
              chart={data}
              onOpen={(id) => {
                void navigate({ to: '/v/$vault/e/$entity', params: { vault, entity: id } })
              }}
            />
          </Suspense>
        </figure>
      )}
      {data?.truncated && (
        <p className="text-sm text-muted-foreground">
          The chart is larger than the view: lower the levels to see all of it.
        </p>
      )}
    </div>
  )
}
