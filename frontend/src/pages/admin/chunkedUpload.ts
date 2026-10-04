/**
 * Chunked, resumable upload of one file into a model-store draft.
 *
 * - init returns the server's upload (or the in-progress one for the same
 *   filename + size, with the chunks it already has): that is the resume
 * - only missing chunks are sent, a few in parallel, each retried with backoff
 * - the server hashes the assembled file on complete; nothing is hashed here
 */

import {
  AdminApiError,
  completeUpload,
  initUpload,
  putChunk,
  type StoreFile,
  type StoreUpload,
} from './adminApi';

export const MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024;
export const ALLOWED_EXTENSION = '.pt';

const PARALLEL_CHUNKS = 3;
const RETRY_DELAYS_MS = [1_000, 3_000, 9_000];
const RETRYABLE_STATUS = new Set([0, 408, 429, 500, 502, 503, 504]);

export interface UploadProgress {
  phase: 'starting' | 'uploading' | 'verifying';
  uploadedBytes: number;
  totalBytes: number;
}

/** Client-side check before contacting the server (the server re-checks). */
export function fileProblem(file: File): string | null {
  if (!file.name.toLowerCase().endsWith(ALLOWED_EXTENSION)) {
    return 'Only .pt files are accepted';
  }
  if (file.size === 0) return 'File is empty';
  if (file.size > MAX_FILE_BYTES) return 'Files are limited to 2 GiB';
  return null;
}

function chunkLength(upload: StoreUpload, index: number): number {
  return index < upload.total_chunks - 1
    ? upload.chunk_size
    : upload.size_bytes - upload.chunk_size * (upload.total_chunks - 1);
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timer);
        reject(new AdminApiError(0, 'Cancelled'));
      },
      { once: true }
    );
  });
}

export async function uploadFile(
  modelPk: string,
  file: File,
  onProgress: (progress: UploadProgress) => void,
  onStarted: (uploadId: string) => void,
  signal: AbortSignal
): Promise<StoreFile> {
  onProgress({ phase: 'starting', uploadedBytes: 0, totalBytes: file.size });
  const upload = await initUpload(modelPk, file);
  onStarted(upload.id);

  const received = new Set(upload.received_chunks);
  let doneBytes = upload.received_chunks.reduce((sum, i) => sum + chunkLength(upload, i), 0);
  const inFlight = new Map<number, number>();
  const report = () => {
    let partial = 0;
    inFlight.forEach((loaded) => (partial += loaded));
    onProgress({
      phase: 'uploading',
      uploadedBytes: Math.min(file.size, doneBytes + partial),
      totalBytes: file.size,
    });
  };
  report();

  const queue: number[] = [];
  for (let i = 0; i < upload.total_chunks; i++) {
    if (!received.has(i)) queue.push(i);
  }

  // One failing chunk stops the others.
  const local = new AbortController();
  const stop = () => local.abort();
  signal.addEventListener('abort', stop, { once: true });

  const sendChunk = async (index: number) => {
    const start = index * upload.chunk_size;
    const blob = file.slice(start, start + chunkLength(upload, index));
    for (let attempt = 0; ; attempt++) {
      try {
        await putChunk(
          upload.id,
          index,
          blob,
          (loaded) => {
            inFlight.set(index, loaded);
            report();
          },
          local.signal
        );
        inFlight.delete(index);
        doneBytes += blob.size;
        report();
        return;
      } catch (err) {
        inFlight.delete(index);
        const status = err instanceof AdminApiError ? err.status : 0;
        if (local.signal.aborted || !RETRYABLE_STATUS.has(status) || attempt >= RETRY_DELAYS_MS.length) {
          throw err;
        }
        await sleep(RETRY_DELAYS_MS[attempt], local.signal);
      }
    }
  };

  const worker = async () => {
    while (queue.length > 0 && !local.signal.aborted) {
      await sendChunk(queue.shift() as number);
    }
  };

  try {
    await Promise.all(
      Array.from({ length: Math.min(PARALLEL_CHUNKS, queue.length) }, () =>
        worker().catch((err) => {
          stop();
          throw err;
        })
      )
    );
  } finally {
    signal.removeEventListener('abort', stop);
  }
  if (signal.aborted) throw new AdminApiError(0, 'Cancelled');

  onProgress({ phase: 'verifying', uploadedBytes: file.size, totalBytes: file.size });
  const completed = await completeUpload(upload.id);
  return completed.file;
}
