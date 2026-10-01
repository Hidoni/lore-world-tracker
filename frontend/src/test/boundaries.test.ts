// @vitest-environment node
import { fileURLToPath } from 'node:url'

import { ESLint } from 'eslint'
import { describe, expect, it } from 'vitest'

// Lints synthetic source against the real repository ESLint config to prove the module
// boundaries (modules.md §3) are enforced, not just configured.

const repoRoot = fileURLToPath(new URL('../../../', import.meta.url))
const eslint = new ESLint({ cwd: repoRoot })

async function boundaryErrors(filePath: string, code: string): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath })
  return (result?.messages ?? [])
    .filter((message) => message.ruleId === 'boundaries/dependencies')
    .map((message) => message.message)
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
})
