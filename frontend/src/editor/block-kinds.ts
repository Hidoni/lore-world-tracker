// The callout tones and visibility block levels (kept apart from the TipTap nodes in
// `blocks.tsx`, so code outside the editor doesn't load TipTap).
export const CALLOUT_TONES = ['note', 'warning', 'quote'] as const
export type CalloutTone = (typeof CALLOUT_TONES)[number]
export const BLOCK_LEVELS = ['spoiler', 'private'] as const
export type BlockLevel = (typeof BLOCK_LEVELS)[number]
