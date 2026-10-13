import type { EntityViewProps } from '@/core/modules'

import { Lexicon } from '../lexicon/lexicon'

/** The language page's Lexicon panel. */
export function LexiconPanel({ vault, entityId }: EntityViewProps) {
  return <Lexicon vault={vault} language={entityId} />
}
