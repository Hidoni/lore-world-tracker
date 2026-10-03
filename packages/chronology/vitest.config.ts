import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['src/**/*.test.ts', 'test/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.ts'],
      exclude: ['src/**/*.test.ts', 'src/**/*.gen.ts'],
      thresholds: {
        // Issue #9: the numeric foundation is fully covered.
        'src/numbers.ts': { lines: 100, branches: 100, functions: 100, statements: 100 },
        // testing.md §1: the engine is covered to at least 95%.
        'src/calendar/**': { lines: 95, branches: 95, functions: 95, statements: 95 },
        'src/presets.ts': { lines: 95, branches: 95, functions: 95, statements: 95 },
        'src/recurrence/**': { lines: 95, branches: 95, functions: 95, statements: 95 },
        'src/viewport/**': { lines: 95, branches: 95, functions: 95, statements: 95 },
      },
    },
  },
})
