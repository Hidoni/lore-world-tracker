import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { useMutations, usePublish, usePublishStatus } from '@/data'

import { Section } from './shared'

/**
 * Publishing (visibility-and-sharing.md §4): a sanitized snapshot of the vault, private data
 * removed, written into the server's publish directory for a read-only server to share.
 */
export function PublishSettings({ vault }: { vault: string }) {
  const editable = useMutations() !== null
  const status = usePublishStatus(vault)
  const publish = usePublish(vault)
  const publishedAt = status.data?.published_at ?? null
  return (
    <Section
      title="Publish snapshot"
      description="A copy of the vault for readers: private entities, fields, blocks, notes, history and findings are removed, and a leak check runs before anything is written. Serve the publish directory with a read-only server."
    >
      {status.isPending && <p className="text-sm text-muted-foreground">Loading…</p>}
      {status.data && !status.data.available && (
        <p className="text-sm text-muted-foreground">
          Publishing isn’t set up on this server: set <code>LORE_PUBLISH_DIR</code> to the data
          directory of the read-only server, or run <code>lore vault publish</code>.
        </p>
      )}
      {status.data?.available && (
        <div className="flex flex-wrap items-center gap-3">
          {editable && (
            <Button
              disabled={publish.isPending}
              onClick={() => {
                publish.mutate(undefined, {
                  onSuccess: () => {
                    toast.success('Snapshot published')
                  },
                })
              }}
            >
              {publish.isPending ? 'Publishing…' : 'Publish snapshot'}
            </Button>
          )}
          <p className="text-sm text-muted-foreground">
            {publishedAt === null ? (
              'Not published yet.'
            ) : (
              <>
                Last published{' '}
                <time dateTime={publishedAt}>{new Date(publishedAt).toLocaleString()}</time>.
              </>
            )}
          </p>
        </div>
      )}
    </Section>
  )
}
