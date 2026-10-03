/** Recurrence: occurrences of recurring events, computed on demand (recurrence.md).
 *
 * Occurrences are never stored in bulk (ADR-0009). Every function jumps straight to the periods it
 * needs with ordinal arithmetic; nothing iterates from the series start. */
export {
  type Expansion,
  type SeriesBounds,
  type WindowCount,
  countInWindow,
  expand,
  expansionToJson,
  nextOccurrences,
  occurrence,
  occurrenceAt,
  occurrenceNumber,
  seriesBounds,
  seriesBoundsToJson,
  validateRule,
} from './engine'
export {
  type Occurrence,
  type RecurrenceContext,
  RecurrenceError,
  type RecurrenceErrorCode,
  type RuleValidationError,
  occurrenceToJson,
} from './plan'
