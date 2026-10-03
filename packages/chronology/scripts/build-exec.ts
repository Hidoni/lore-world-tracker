// Bundles the differential-testing CLI bin/chrono-exec.ts into dist/chrono-exec.mjs, which plain
// Node can run (the engine source uses extensionless imports and JSON modules). Uses rolldown, the
// workspace's bundler (Vite's).
//   node scripts/build-exec.ts   (`npm run build:exec -w @lore/chronology`)
import { fileURLToPath } from 'node:url'

import { build } from 'rolldown'

const packageDir = fileURLToPath(new URL('..', import.meta.url))

await build({
  cwd: packageDir,
  input: 'bin/chrono-exec.ts',
  platform: 'node',
  logLevel: 'warn',
  output: { file: 'dist/chrono-exec.mjs', format: 'esm' },
})
