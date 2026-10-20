import type { EntityViewProps } from '@/core/modules'
import { useEntity } from '@/data'

import { SPECIMEN } from './font-field'
import { FONT, FONT_SCALE, SAMPLE, fontStyle, scaleOf, useFontFamily } from './fonts'

function fieldsOf(data: { fields: unknown } | undefined): Record<string, unknown> {
  return (data?.fields ?? {}) as Record<string, unknown>
}

/** Shown on writing systems with a font. */
export function useSampleShown({ vault, entityId }: EntityViewProps): boolean {
  const entity = useEntity(vault, entityId)
  const font = fieldsOf(entity.data)[FONT]
  return typeof font === 'string' && font !== ''
}

/** A writing system's sample (`scripts.sample`, else letters and digits) in its font. */
export function SamplePanel({ vault, entityId }: EntityViewProps) {
  const entity = useEntity(vault, entityId)
  const fields = fieldsOf(entity.data)
  const font = fields[FONT]
  if (typeof font !== 'string' || font === '') return null
  return <Sample vault={vault} media={font} fields={fields} />
}

function Sample({
  vault,
  media,
  fields,
}: {
  vault: string
  media: string
  fields: Record<string, unknown>
}) {
  const family = useFontFamily(vault, media)
  const sample =
    typeof fields[SAMPLE] === 'string' && fields[SAMPLE] !== '' ? fields[SAMPLE] : SPECIMEN
  const direction = fields.direction === 'rtl' ? 'rtl' : undefined
  return (
    <p
      className="text-2xl leading-relaxed whitespace-pre-wrap"
      style={fontStyle({ family, scale: scaleOf(fields[FONT_SCALE]) })}
      dir={direction}
      data-script-font={media}
    >
      {sample}
    </p>
  )
}
