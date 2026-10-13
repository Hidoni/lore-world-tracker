import { Link, useNavigate } from '@tanstack/react-router'
import { useCallback, useState } from 'react'

import { Button } from '@/components/ui/button'
import type { EntityViewProps } from '@/core/modules'

import { FamilyTree } from '../views/family-tree'

/**
 * The character page's Family tree panel: two generations each way, re-centered in place on a
 * click (with a way back), and a link to the full view.
 */
export function FamilyTreePanel({ vault, entityId }: EntityViewProps) {
  const navigate = useNavigate()
  // Re-centered on a relative of this character (a new character page starts on its own).
  const [recentered, setRecentered] = useState({ on: entityId, root: entityId })
  const centered = recentered.on === entityId ? recentered.root : entityId
  const setRoot = useCallback(
    (root: string) => {
      setRecentered({ on: entityId, root })
    },
    [entityId],
  )
  const open = useCallback(
    (id: string) => {
      void navigate({ to: '/v/$vault/e/$entity', params: { vault, entity: id } })
    },
    [navigate, vault],
  )
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-3 text-sm">
        <Link
          to="/v/$vault/m/$module/$"
          params={{ vault, module: 'characters', _splat: `${centered}/family-tree` }}
          className="text-primary underline-offset-2 hover:underline"
        >
          Open the family tree view
        </Link>
        {centered !== entityId && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setRoot(entityId)
            }}
          >
            Back to this character
          </Button>
        )}
      </div>
      <FamilyTree
        vault={vault}
        character={centered}
        initialDepth={2}
        onRecenter={setRoot}
        onOpen={open}
        className="h-80 rounded-md border"
      />
    </div>
  )
}
