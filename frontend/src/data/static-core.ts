/** What the static export's handlers share (`static.ts`, ADR 0016). */

/** Loads a recorded answer (`data/<route>.json`); a file the export lacks rejects with `NotInExport`. */
export type Load = (route: string) => Promise<unknown>

/** A read with free parameters, answered from recorded files. */
export type Handler = (
  load: Load,
  route: string,
  params: URLSearchParams,
  /** The route pattern's groups (`[vault, id]`). */
  groups: readonly string[],
) => Promise<unknown>

/** A failed read, as the server would answer it (`422` for a parameter it refuses, `404`…). */
export class StaticProblem extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly title: string,
    detail: string,
  ) {
    super(detail)
  }
}

/** A file the export doesn't hold. */
export class NotInExport extends Error {}
