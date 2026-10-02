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
      },
    },
  },
})
