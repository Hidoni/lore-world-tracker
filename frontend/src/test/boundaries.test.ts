// @vitest-environment node
import { fileURLToPath } from 'node:url'

import { ESLint } from 'eslint'
import { describe, expect, it } from 'vitest'

// Lints synthetic source against the real repository ESLint config to prove the module
// boundaries (modules.md §3) are enforced, not just configured.

const repoRoot = fileURLToPath(new URL('../../../', import.meta.url))
const eslint = new ESLint({ cwd: repoRoot })

async function ruleErrors(rule: string, filePath: string, code: string): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath })
  return (result?.messages ?? [])
    .filter((message) => message.ruleId === rule)
    .map((message) => message.message)
}

function boundaryErrors(filePath: string, code: string): Promise<string[]> {
  return ruleErrors('boundaries/dependencies', filePath, code)
}

describe('frontend module boundaries', { timeout: 60_000 }, () => {
  it('rejects core importing modules', async () => {
    const errors = await boundaryErrors(
      'frontend/src/core/registry/index.ts',
      "import { moduleDefinitions } from '@/modules'\nexport const count = moduleDefinitions.length\n",
    )
    expect(errors).toHaveLength(1)
    expect(errors[0]).toContain('core must not import modules')
  })

  it('allows modules importing core', async () => {
    const errors = await boundaryErrors(
      'frontend/src/modules/index.ts',
      "import { ShellLayout } from '@/core/shell/shell-layout'\nexport const layout = ShellLayout\n",
    )
    expect(errors).toEqual([])
  })

  it('rejects components and core importing the API client', async () => {
    const code = "import { api } from '@/api'\nexport const client = api\n"
    // Paths no other test lints: eslint-plugin-boundaries caches its analysis per file.
    for (const filePath of [
      'frontend/src/core/search/index.ts',
      'frontend/src/components/theme-toggle.tsx',
    ]) {
      const errors = await boundaryErrors(filePath, code)
      expect(errors).toHaveLength(1)
      expect(errors[0]).toContain('use the data layer')
    }
    expect(await boundaryErrors('frontend/src/data/meta.ts', code)).toEqual([])
  })
})

describe('lore/no-number-moment', { timeout: 60_000 }, () => {
  const FILE = 'frontend/src/core/time/index.ts'

  it('rejects converting moments to numbers', async () => {
    const errors = await ruleErrors(
      'lore/no-number-moment',
      FILE,
      [
        "import type { MomentString } from '@/api/moment'",
        'declare const start: bigint',
        'declare const wire: MomentString | null',
        'export const a = Number(start)',
        'export const b = parseInt(wire ?? "0", 10)',
        'export const c = Number.parseFloat(wire as MomentString)',
        'export const d = +start',
        '',
      ].join('\n'),
    )
    expect(errors).toHaveLength(4)
    expect(errors[0]).toContain('Number() on a moment loses precision')
  })

  it('allows numbers that are not moments', async () => {
    const errors = await ruleErrors(
      'lore/no-number-moment',
      FILE,
      "declare const px: string\nexport const a = Number(px) + parseInt('3', 10) + +px\n",
    )
    expect(errors).toEqual([])
  })
})
