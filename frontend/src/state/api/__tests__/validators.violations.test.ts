import { describe, expect, it } from 'vitest';
import {
  isViolation,
  isViolationEvidence,
  isViolationsListResponse,
} from '../validators';

/**
 * The Violations page went blank — "Couldn't load alerts" — while the
 * backend was returning 200. The cause was the validator, not the data:
 * the backend began sending `bookmark_status: null` to mean "no clip was
 * ever requested" (as distinct from 'pending', "one is coming"), and
 * `isEvidenceStatus` rejected null. That failed `isViolationEvidence`,
 * which failed `isViolation`, which failed `items.every(...)` — so ONE
 * row without a clip blacked out the entire page.
 *
 * These samples are copied from a real `GET /api/v1/violations` response,
 * not hand-written, because the hand-written fixtures are exactly what
 * missed this.
 */

/** Real row: frame saved, snapshot ready, clip in progress. */
const WITH_CLIP = {
  id: 'cb7fe7ea-5a17-423a-aadd-eb55fa0fbb8d',
  type: 'ppe_violation',
  status: 'open',
  camera_id: 'cb63650f-0d33-4daa-818f-68f1afd5f8a3',
  camera_name: '75098',
  confidence: 0.7689,
  timestamp: '2026-10-19T05:16:15.463596Z',
  model_id: 'gloves_2',
  model_version: '1.0.0',
  bounding_boxes: [
    {
      x: 256, y: 241, label: 'missing_gloves', width: 23, height: 30,
      confidence: 0.7689, frame_width: 1280, frame_height: 720,
    },
  ],
  reviewed_by: null,
  reviewed_at: null,
  resolution_notes: null,
  evidence: {
    frame_url: '/api/v1/violations/cb7fe7ea-5a17-423a-aadd-eb55fa0fbb8d/frame/image',
    frame_status: 'ready',
    snapshot_id: 'd665703f-a2e8-497f-b2fd-7ef10524c02a',
    snapshot_url: '/api/v1/violations/cb7fe7ea-5a17-423a-aadd-eb55fa0fbb8d/snapshot/image',
    snapshot_status: 'ready',
    bookmark_id: '84f372e0-67ee-4b97-9423-1be3f3680a9f',
    bookmark_url: '/api/v1/violations/cb7fe7ea-5a17-423a-aadd-eb55fa0fbb8d/video',
    bookmark_status: 'processing',
    bookmark_duration_seconds: 10,
  },
  created_at: '2026-10-19T05:16:15.465279Z',
  updated_at: '2026-10-19T05:16:15.465289Z',
};

/** The row that broke the page: no clip requested, so null not 'pending'. */
const NO_CLIP = {
  ...WITH_CLIP,
  id: 'd0e01015-489b-4674-ad02-0410228c621d',
  camera_name: '75081',
  evidence: {
    frame_url: '/api/v1/violations/d0e01015-489b-4674-ad02-0410228c621d/frame/image',
    frame_status: 'ready',
    snapshot_id: 'aa11bb22-cc33-dd44-ee55-ff6677889900',
    snapshot_url: '/api/v1/violations/d0e01015-489b-4674-ad02-0410228c621d/snapshot/image',
    snapshot_status: 'ready',
    bookmark_id: null,
    bookmark_url: null,
    bookmark_status: null,
    bookmark_duration_seconds: null,
  },
};

/** A violation from before frames existed: no frame keys at all. */
const LEGACY = {
  ...WITH_CLIP,
  id: '11111111-2222-3333-4444-555555555555',
  evidence: {
    snapshot_id: 'd665703f-a2e8-497f-b2fd-7ef10524c02a',
    snapshot_url: '/api/v1/violations/11111111-2222-3333-4444-555555555555/snapshot/image',
    snapshot_status: 'ready',
    bookmark_id: null,
    bookmark_url: null,
    bookmark_status: null,
  },
};

// ---------------------------------------------------------------------------
// The regression
// ---------------------------------------------------------------------------

describe('bookmark_status: null', () => {
  it('is accepted — it means no clip was requested, not bad data', () => {
    expect(isViolationEvidence(NO_CLIP.evidence)).toBe(true);
    expect(isViolation(NO_CLIP)).toBe(true);
  });

  it('does not black out the whole list', () => {
    // items.every(...) means one bad row rejects every row. This is the
    // shape of response that emptied the page.
    expect(
      isViolationsListResponse({ items: [WITH_CLIP, NO_CLIP], total: 2 })
    ).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// The new frame fields
// ---------------------------------------------------------------------------

describe('frame evidence', () => {
  it('accepts frame_url and frame_status', () => {
    expect(isViolationEvidence(WITH_CLIP.evidence)).toBe(true);
  });

  it('accepts a violation with no frame saved', () => {
    expect(
      isViolationEvidence({ ...NO_CLIP.evidence, frame_url: null, frame_status: null })
    ).toBe(true);
  });

  it('accepts a legacy payload with the frame keys absent entirely', () => {
    expect(isViolationEvidence(LEGACY.evidence)).toBe(true);
    expect(isViolation(LEGACY)).toBe(true);
  });

  it('still rejects a frame_status that is not a status', () => {
    expect(
      isViolationEvidence({ ...WITH_CLIP.evidence, frame_status: 'nonsense' })
    ).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Still strict where it matters
// ---------------------------------------------------------------------------

describe('the validator has not simply been loosened', () => {
  it('rejects a bad bookmark_status string', () => {
    expect(
      isViolationEvidence({ ...WITH_CLIP.evidence, bookmark_status: 'almost' })
    ).toBe(false);
  });

  it('rejects a violation missing a core field', () => {
    const { confidence: _dropped, ...withoutConfidence } = WITH_CLIP;
    expect(isViolation(withoutConfidence)).toBe(false);
  });

  it('rejects a non-object evidence value', () => {
    expect(isViolation({ ...WITH_CLIP, evidence: 'ready' })).toBe(false);
  });

  it('accepts evidence being absent', () => {
    const { evidence: _dropped, ...withoutEvidence } = WITH_CLIP;
    expect(isViolation(withoutEvidence)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// The exact live response
// ---------------------------------------------------------------------------

describe('a real list response', () => {
  it('validates as returned by the backend today', () => {
    expect(
      isViolationsListResponse({
        items: [WITH_CLIP, NO_CLIP, LEGACY],
        total: 3,
        page: 1,
        limit: 50,
      })
    ).toBe(true);
  });
});
