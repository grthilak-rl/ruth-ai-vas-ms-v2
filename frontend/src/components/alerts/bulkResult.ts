import type { ViolationBulkResponse } from '../../state/api';

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

/** "12 dismissed · 12 frames sent to labelling · 2 had no saved frame" */
export function summarizeBulkResult(result: ViolationBulkResponse, action: 'review' | 'dismiss'): string {
  const parts = [`${plural(result.updated.length, 'violation')} ${action === 'review' ? 'marked as reviewed' : 'dismissed'}`];
  const l = result.labelling;
  if (l) {
    if (l.exported) parts.push(`${plural(l.exported, 'frame')} sent to labelling`);
    if (l.no_frame) parts.push(`${l.no_frame} had no saved frame`);
    if (l.capped) parts.push(`${l.capped} over the per-incident limit`);
    if (l.failed) parts.push(`${l.failed} couldn't be copied`);
  }
  if (result.skipped.length) parts.push(`${result.skipped.length} skipped (already changed)`);
  return parts.join(' · ');
}
