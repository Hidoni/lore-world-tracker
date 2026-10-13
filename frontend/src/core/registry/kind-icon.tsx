import { createElement, type SVGProps } from 'react'

import type { Kind } from './kind-registry'

/**
 * An entity's icon: its kind's, or the one its `iconField` value picks (location types). Rendered
 * with `createElement`, as the icon component is looked up per value.
 */
export function KindIcon({
  kind,
  value,
  ...props
}: { kind: Kind; value?: string | null | undefined } & SVGProps<SVGSVGElement>) {
  const icon = kind.iconField === null || kind.groupBy !== null ? kind.icon : kind.iconFor(value)
  return createElement(icon, { 'aria-hidden': true, ...props })
}
