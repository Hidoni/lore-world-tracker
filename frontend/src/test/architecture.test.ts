// @vitest-environment node
import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

// Module → module imports follow declared dependencies (modules.md §3, the frontend twin of
// backend/tests/test_architecture.py): module `a` may import `@/modules/b/public` only when `b` is
// in a's `dependsOn`. ESLint (`no-restricted-imports`) keeps them to `public.ts`.

const modulesDir = fileURLToPath(new URL('../modules/', import.meta.url))
const IMPORT = /from\s+['"]@\/modules\/([a-z][a-z0-9_]*)(\/[^'"]*)?['"]/g

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const file = path.join(dir, name)
    if (statSync(file).isDirectory()) return sources(file)
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [file] : []
  })
}

/** Undeclared imports: `<module> → <imported module>` for each one. */
export function undeclaredImports(
  files: Record<string, readonly string[]>,
  dependsOn: Record<string, readonly string[]>,
): string[] {
  const found: string[] = []
  for (const [module, texts] of Object.entries(files)) {
    for (const text of texts) {
      for (const match of text.matchAll(IMPORT)) {
        const imported = match[1] ?? ''
        if (imported !== module && !(dependsOn[module] ?? []).includes(imported)) {
          found.push(`${module} → ${imported}`)
        }
      }
    }
  }
  return found.sort()
}

describe('frontend module dependencies', () => {
  it('flags imports of undeclared modules', () => {
    const files = {
      characters: ["import { x } from '@/modules/groups/public'"],
      groups: ["import { y } from '@/modules/characters/public'"],
    }
    expect(undeclaredImports(files, { characters: ['groups'] })).toEqual(['groups → characters'])
  })

  it('holds for every module folder', async () => {
    // Loaded here, with a location for the API client the modules' imports reach (node env).
    const scope = globalThis as { location?: unknown }
    scope.location ??= new URL('http://localhost/')
    const { moduleDefinitions } = await import('@/modules')
    const folders = readdirSync(modulesDir).filter((name) =>
      statSync(path.join(modulesDir, name)).isDirectory(),
    )
    const files = Object.fromEntries(
      folders.map((id) => [
        id,
        sources(path.join(modulesDir, id)).map((file) => readFileSync(file, 'utf8')),
      ]),
    )
    const dependsOn = Object.fromEntries(
      moduleDefinitions.map((definition) => [definition.id, definition.dependsOn ?? []]),
    )
    expect(undeclaredImports(files, dependsOn)).toEqual([])
    // Every module folder is a listed definition.
    expect(folders.filter((id) => !(id in dependsOn))).toEqual([])
  })
})
