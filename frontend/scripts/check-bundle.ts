// The shell's initial JS budget (frontend.md §12: < 400 kB gzip): the scripts `dist/index.html`
// loads and preloads, gzipped. Run after `vite build` (`make check-frontend`).
//   node scripts/check-bundle.ts
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

const BUDGET_KB = 400

const dist = fileURLToPath(new URL('../dist/', import.meta.url))
const html = readFileSync(path.join(dist, 'index.html'), 'utf8')
const scripts = new Set(
  [...html.matchAll(/(?:src|href)="\/?(assets\/[^"]+\.js)"/g)].map((match) => match[1] ?? ''),
)
let total = 0
const sizes: [number, string][] = []
for (const file of scripts) {
  const size = gzipSync(readFileSync(path.join(dist, file)), { level: 9 }).length
  total += size
  sizes.push([size, file])
}
sizes.sort((a, b) => b[0] - a[0])
const kb = (bytes: number) => `${(bytes / 1024).toFixed(1)} kB`
for (const [size, file] of sizes.slice(0, 5)) console.log(`${kb(size).padStart(9)}  ${file}`)
console.log(
  `initial JS: ${kb(total)} gzip (${String(scripts.size)} files; budget ${String(BUDGET_KB)} kB)`,
)
if (total > BUDGET_KB * 1024) {
  console.error('The initial bundle is over budget: lazy-load what the shell does not need.')
  process.exit(1)
}
