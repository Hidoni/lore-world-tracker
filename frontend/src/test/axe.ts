import axe from 'axe-core'

/**
 * Rules jsdom can't judge: it lays nothing out and paints nothing, so contrast and target sizes
 * are checked in a real browser instead (the e2e accessibility check, frontend.md §11).
 */
const NOT_IN_JSDOM = ['color-contrast', 'color-contrast-enhanced', 'target-size']

/** A test running axe on a whole page: axe takes a second or two on a large one in CI. */
export const AXE_TIMEOUT = 20_000

/** Impacts that fail a test (R-NFR-3: no serious violations). */
const FAILING = new Set(['serious', 'critical'])

/** The serious and critical axe violations on the page, one line each (rule, then the nodes). */
export async function axeViolations(root: Element = document.body): Promise<string[]> {
  const results = await axe.run(root, {
    rules: Object.fromEntries(NOT_IN_JSDOM.map((rule) => [rule, { enabled: false }])),
    resultTypes: ['violations'],
  })
  return results.violations
    .filter((violation) => FAILING.has(violation.impact ?? ''))
    .map(
      (violation) =>
        `${violation.id} (${violation.impact ?? '?'}): ${violation.help} — ` +
        violation.nodes.map((node) => node.target.join(' ')).join(', '),
    )
}

/** The page has no serious or critical axe violations (the error lists them). */
export async function expectAccessible(root?: Element): Promise<void> {
  const found = await axeViolations(root)
  if (found.length > 0) throw new Error(`accessibility violations:\n${found.join('\n')}`)
}
