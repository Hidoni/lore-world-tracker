import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { useCallback } from 'react'

import { useEntity } from '@/data'

import { FamilyTree } from './family-tree'

/** The family tree view of a character (`/m/characters/<character>/family-tree`). */
export default function FamilyTreePage() {
  // Module routes aren't in the router's generated types.
  const params: { vault?: string; character?: string } = useParams({ strict: false })
  const vault = params.vault ?? ''
  const character = params.character ?? ''
  const navigate = useNavigate()
  const entity = useEntity(vault, character)
  const recenter = useCallback(
    (id: string) => {
      void navigate({
        to: '/v/$vault/m/$module/$',
        params: { vault, module: 'characters', _splat: `${id}/family-tree` },
      })
    },
    [navigate, vault],
  )
  const open = useCallback(
    (id: string) => {
      void navigate({ to: '/v/$vault/e/$entity', params: { vault, entity: id } })
    },
    [navigate, vault],
  )
  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">
          Family tree{entity.data ? ` of ${entity.data.name}` : ''}
        </h1>
        {entity.data && (
          <Link
            to="/v/$vault/e/$entity"
            params={{ vault, entity: character }}
            className="text-sm text-primary underline-offset-2 hover:underline"
          >
            Back to {entity.data.name}
          </Link>
        )}
      </header>
      {entity.isError ? (
        <p className="text-muted-foreground">This character was not found.</p>
      ) : (
        <FamilyTree
          vault={vault}
          character={character}
          initialDepth={3}
          onRecenter={recenter}
          onOpen={open}
        />
      )}
    </div>
  )
}
