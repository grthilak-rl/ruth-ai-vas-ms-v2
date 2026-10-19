// @vitest-environment jsdom
/**
 * Evidence player clip controls.
 *
 * Regression: every ready clip's "Play Evidence" did nothing — the clip URL
 * returned JSON, <video> errored, and the error handler closed the player
 * before its message could show. With the Request button (correctly) hidden
 * for ready clips, a ready-but-unplayable clip looked like "no clip and no
 * way to get one".
 */

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ViolationEvidence } from '../../../state/api';
import { EvidenceViewer } from '../EvidenceViewer';
import { clipFilename } from '../clipFilename';

vi.mock('../../../state/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../state/api')>()),
  fetchClipAvailability: vi.fn(async () => ({ available: true })),
  requestViolationClip: vi.fn(async () => ({ status: 'pending', reused: null, bookmark_id: null })),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const CLIP_URL = '/api/v1/bookmarks/3b069b07-8c57-4d9b-b82b-4df1c8f2db95/video';
const TIMESTAMP = '2026-10-19T09:19:52.341Z';

function evidence(over: Partial<ViolationEvidence> = {}): ViolationEvidence {
  return {
    frame_url: '/api/v1/violations/v1/frame/image',
    frame_status: 'ready',
    snapshot_id: null,
    snapshot_url: null,
    snapshot_status: 'ready',
    bookmark_id: null,
    bookmark_url: null,
    bookmark_status: null,
    ...over,
  } as ViolationEvidence;
}

const READY = { bookmark_status: 'ready', bookmark_id: 'b1', bookmark_url: CLIP_URL } as const;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  // jsdom has no canvas; the overlay only draws after the image loads.
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function render(ev: ViolationEvidence) {
  await act(async () => {
    root.render(
      <EvidenceViewer
        evidence={ev}
        cameraName="Dock 2"
        timestamp={TIMESTAMP}
        violationId="v1"
        boundingBoxes={[{ x: 0.1, y: 0.1, width: 0.2, height: 0.2, label: 'missing_gloves', confidence: 0.8 }]}
        clipTypeSlug="missing_gloves"
      />
    );
  });
}

const byText = (text: string) =>
  Array.from(container.querySelectorAll('button, a, span')).find((el) => el.textContent?.includes(text));
const playButton = () => byText('Play Evidence') as HTMLButtonElement | undefined;
const requestButton = () => byText('Request clip') as HTMLButtonElement | undefined;
const downloadClip = () => byText('Download clip') as HTMLAnchorElement | undefined;

describe('the four clip states render the right control', () => {
  it('no clip (null): Request clip, nothing to play or download', async () => {
    await render(evidence());
    expect(requestButton()).toBeDefined();
    expect(requestButton()!.disabled).toBe(false); // availability resolved: available
    expect(playButton()).toBeUndefined();
    expect(downloadClip()).toBeUndefined();
  });

  it.each(['pending', 'processing'] as const)('%s: Preparing clip…, no play/request/download', async (s) => {
    await render(evidence({ bookmark_status: s, bookmark_id: 'b1' }));
    expect(container.textContent).toContain('Preparing clip…');
    expect(requestButton()).toBeUndefined();
    expect(playButton()).toBeUndefined();
    expect(downloadClip()).toBeUndefined();
  });

  it('ready: Play Evidence and Download clip, no Request clip', async () => {
    await render(evidence(READY));
    expect(playButton()).toBeDefined();
    expect(downloadClip()).toBeDefined();
    expect(requestButton()).toBeUndefined();
  });

  it('failed: Request clip again, with the failure noted', async () => {
    await render(evidence({ bookmark_status: 'failed', bookmark_id: 'b1' }));
    expect(requestButton()).toBeDefined();
    expect(container.textContent).toContain('Last attempt failed');
    expect(playButton()).toBeUndefined();
    expect(downloadClip()).toBeUndefined();
  });
});

describe('playing the clip', () => {
  it('Play opens a video on the clip URL', async () => {
    await render(evidence(READY));
    expect(container.querySelector('video')).toBeNull();

    await act(async () => playButton()!.click());

    const video = container.querySelector('video');
    expect(video).not.toBeNull();
    expect(video!.getAttribute('src')).toBe(CLIP_URL);
    expect(playButton()).toBeUndefined();
  });

  it('a playback error keeps the player open with Retry, instead of silently closing', async () => {
    await render(evidence(READY));
    await act(async () => playButton()!.click());

    await act(async () => {
      container.querySelector('video')!.dispatchEvent(new Event('error'));
    });
    expect(container.textContent).toContain('Video playback failed');

    await act(async () => (byText('Retry') as HTMLButtonElement).click());
    expect(container.querySelector('video')!.getAttribute('src')).toBe(CLIP_URL);
  });

  it('Play is drawn inside the image, not on the controls bar', async () => {
    await render(evidence(READY));
    const overlay = playButton()!.closest('.evidence-viewer__play-overlay')!;
    expect(overlay.parentElement!.classList.contains('snapshot-overlay__stage')).toBe(true);
  });
});

describe('Download clip', () => {
  it('points at the clip and names the file <camera>_<type>_<timestamp>.mp4', async () => {
    await render(evidence(READY));
    const link = downloadClip()!;
    expect(link.getAttribute('href')).toBe(CLIP_URL);
    expect(link.getAttribute('download')).toBe('Dock-2_missing_gloves_20261019T091952Z.mp4');
    // Next to "Download annotated", in the controls bar.
    expect(link.closest('.snapshot-overlay__actions')?.textContent).toContain('Download annotated');
  });

  it('still offered, in the footer, when there is no image to put controls under', async () => {
    await render(evidence({ ...READY, frame_status: null, frame_url: null, snapshot_status: 'failed' }));
    expect(downloadClip()!.closest('.evidence-viewer__footer')).not.toBeNull();
    expect(playButton()).toBeDefined();
  });

  it('builds filename-safe names', () => {
    expect(clipFilename('Gate 3 / North', 'fall_detected', '2026-01-02T03:04:05Z')).toBe(
      'Gate-3-North_fall_detected_20260102T030405Z.mp4'
    );
    expect(clipFilename('  ', 'x', 'not a date')).toBe('unknown_x_not-a-date.mp4');
  });
});
