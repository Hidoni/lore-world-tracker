import { ChevronDownIcon, GitBranchIcon, GitBranchPlusIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useMutations } from '@/data'

import { useBranching } from './branching'
import { CreateBranchDialog } from './create-branch-dialog'
import { formatIn } from './format'
import { useTimeContext } from './time-context'

/**
 * The top bar's timeline switcher (docs/modules/branches.md, UI): the dimension's timelines as a
 * tree, each branch with its branch point in the display calendar. The choice goes to the URL
 * (`tl`) and every view follows it. Authors can start a new branch of the viewed timeline here.
 * Hidden while a dimension has only its prime timeline and branches can't be created.
 */
export function TimelineSwitcher({ vault }: { vault: string }) {
  const time = useTimeContext(vault)
  const branching = useBranching(vault)
  const editable = useMutations() !== null && branching.enabled
  const [creating, setCreating] = useState(false)
  const shown = branching.timelines.filter(({ node }) => !node.trashed)
  if (shown.length === 0 || (shown.length === 1 && !editable)) return null
  const current = branching.current ?? shown[0]?.node ?? null
  const branchPoint = (t: bigint | null) => {
    if (t === null || time.dimension === null || time.lens === null) return null
    return formatIn(time.lens, { t, precision: 'base' }, time.dimension, time.lenses)
  }
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            aria-label={`Timeline: ${current?.name ?? 'none'}`}
            data-branch={branching.inBranch ? '' : undefined}
            className={branching.inBranch ? 'text-primary' : undefined}
          >
            <GitBranchIcon aria-hidden />
            <span className="max-w-40 truncate">{current?.name ?? 'Timeline'}</span>
            <ChevronDownIcon aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="min-w-64">
          <DropdownMenuLabel>Timelines</DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={current?.id ?? ''}
            onValueChange={(id) => {
              time.setTimeline(id)
            }}
          >
            {shown.map(({ node, depth }) => {
              const at = node.is_prime ? null : branchPoint(node.branch_t)
              return (
                <DropdownMenuRadioItem key={node.id} value={node.id}>
                  <span style={{ paddingLeft: `${depth * 0.75}rem` }} className="flex flex-col">
                    <span>{node.name}</span>
                    {at !== null && (
                      <span className="text-xs text-muted-foreground">branches at {at}</span>
                    )}
                  </span>
                </DropdownMenuRadioItem>
              )
            })}
          </DropdownMenuRadioGroup>
          {editable && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => {
                  setCreating(true)
                }}
              >
                <GitBranchPlusIcon aria-hidden />
                New branch…
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {creating && (
        <CreateBranchDialog
          vault={vault}
          onClose={() => {
            setCreating(false)
          }}
        />
      )}
    </>
  )
}
