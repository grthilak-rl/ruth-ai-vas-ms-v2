import { describe, expect, it } from 'vitest';
import {
  cameraHeadline,
  cameraNumber,
  formatIncidentSpan,
  isSeverity,
  severityLabel,
  severityOrDefault,
} from '../violationDisplay';

describe('camera naming on cards', () => {
  it('leads with area · side, number shown separately', () => {
    const cam = { camera_name: '75081', camera_display_name: 'REFORMER1_OUT_75081', camera_area: 'REFORMER1', camera_in_out: 'OUT' };
    expect(cameraHeadline(cam)).toBe('REFORMER1 · OUT');
    expect(cameraNumber(cam)).toBe('75081');
  });

  it('falls back to the display name, then the number', () => {
    expect(cameraHeadline({ camera_name: '75081', camera_display_name: 'Gate 3' })).toBe('Gate 3');
    expect(cameraHeadline({ camera_name: '75081', camera_display_name: '  ' })).toBe('75081');
    expect(cameraHeadline({ camera_name: '74004', camera_area: 'MW01 PF COLUMN' })).toBe('MW01 PF COLUMN');
  });
});

describe('severity', () => {
  it('labels known levels and defaults the rest to medium', () => {
    expect(severityLabel('critical')).toBe('Critical');
    expect(isSeverity('high')).toBe(true);
    expect(isSeverity('urgent')).toBe(false);
    expect(severityOrDefault(undefined)).toBe('medium');
    expect(severityLabel(null)).toBe('Medium');
  });
});

describe('incident span', () => {
  it('one moment, a same-day span, and a span across midnight', () => {
    const t = (iso: string) => new Date(iso).toISOString();
    expect(formatIncidentSpan(t('2026-10-19T10:02:00'), t('2026-10-19T10:02:30'))).toBe('10:02 AM');
    expect(formatIncidentSpan(t('2026-10-19T10:02:00'), t('2026-10-19T10:31:00'))).toBe('10:02 AM – 10:31 AM');
    expect(formatIncidentSpan(t('2026-10-19T23:50:00'), t('2026-10-20T00:20:00'))).toBe(
      'Oct 19 11:50 PM – Oct 20 12:20 AM'
    );
    expect(formatIncidentSpan('nope', 'nope')).toBe('');
  });
});
