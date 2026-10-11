/**
 * An in-world moment on the wire: a non-negative decimal integer string (`format: bigint` in the
 * OpenAPI document, CLAUDE.md rule 1). The brand keeps it apart from other strings; the data layer
 * turns it into a `bigint` (`toDomain`), and back with `momentString`.
 */
export type MomentString = string & { readonly __moment: true }

/**
 * Where moments sit in a schema (`moments.gen.ts`, generated from the OpenAPI document):
 * `'m'` a moment, `{ a }` an array, `{ d }` a string-keyed map, `{ o }` object properties,
 * `{ r }` another schema, `{ u }` alternatives (each applied).
 */
export type MomentShape =
  | 'm'
  | { readonly a: MomentShape }
  | { readonly d: MomentShape }
  | { readonly o: Readonly<Record<string, MomentShape>> }
  | { readonly r: string }
  | { readonly u: readonly MomentShape[] }
