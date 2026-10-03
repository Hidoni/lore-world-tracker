/**
 * `@lore/chronology/presets`: the preset calendars of spec/chronology/presets/ (chronology-engine.md
 * §13), bundled at build time. The JSON files are imported statically, so Vite (and Vitest) inline
 * them into whichever chunk imports this entry point; the engine entry point (`@lore/chronology`)
 * doesn't, which keeps ≈7 kB of gzipped presets out of pages that never create a calendar.
 * Instantiate them with `instantiatePreset`. The server reads the same files at runtime
 * (`LORE_SPEC_DIR`), so both sides always offer the same presets.
 */
import alternatingYears from '../../../spec/chronology/presets/alternating-years.json'
import gregorian from '../../../spec/chronology/presets/gregorian.json'
import julianGregorian from '../../../spec/chronology/presets/julian-gregorian.json'
import julian from '../../../spec/chronology/presets/julian.json'
import lunisolarMetonic from '../../../spec/chronology/presets/lunisolar-metonic.json'
import mayan from '../../../spec/chronology/presets/mayan.json'
import shireReckoning from '../../../spec/chronology/presets/shire-reckoning.json'
import simple360 from '../../../spec/chronology/presets/simple-360.json'
import type { Preset } from './schema.gen'

// The JSON is validated against the Preset schema by the Python tests (and compiled by the TS
// tests); TypeScript infers plain strings where the schema has literal unions, hence the cast.
const ALL = [
  alternatingYears,
  gregorian,
  julian,
  julianGregorian,
  lunisolarMetonic,
  mayan,
  shireReckoning,
  simple360,
] as unknown[] as Preset[]

/** Every preset, by id, in id order (like the server's `load_presets`). */
export const PRESETS: ReadonlyMap<string, Preset> = new Map(
  [...ALL].sort((a, b) => (a.id < b.id ? -1 : 1)).map((preset) => [preset.id, preset]),
)

export { absoluteMoments, instantiatePreset, PresetError, type PresetErrorCode } from './presets'
