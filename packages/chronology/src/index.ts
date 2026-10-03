/**
 * @lore/chronology: the TypeScript time engine (calendars, recurrence, correspondences,
 * viewport/tick math). Behavior is defined by docs/architecture/chronology-engine.md and the
 * shared conformance vectors in spec/chronology/conformance/.
 */

/** Version of the engine semantics. Placeholder until the engine lands (M1). */
export const ENGINE_VERSION = '0.0.0'

/** Chronology document types (calendar definitions, time points, rules, …), generated from the
 * Python models via spec/chronology/schema/bundle.json. Integers are decimal strings. */
export type * from './schema.gen'

export * from './numbers'
export * from './calendar'
export * from './recurrence'
export { PresetError, type PresetErrorCode, absoluteMoments, instantiatePreset } from './presets'
