import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react';
import { AdminApiError, abortUpload, type StoreUpload } from './adminApi';
import { fileProblem, uploadFile, type UploadProgress } from './chunkedUpload';
import { formatBytes } from './format';

type ItemStatus = 'queued' | 'uploading' | 'verifying' | 'done' | 'error' | 'invalid';

interface QueueItem {
  key: string;
  file: File;
  status: ItemStatus;
  uploadedBytes: number;
  message?: string;
  uploadId?: string;
}

interface ModelUploaderProps {
  modelPk: string;
  /** Server-side in-progress uploads (survive a page reload). */
  activeUploads: StoreUpload[];
  onChanged: () => void;
}

let nextKey = 0;

function errorText(err: unknown): string {
  if (err instanceof AdminApiError) {
    if (err.status === 0) return err.message;
    return `${err.message} (HTTP ${err.status})`;
  }
  return 'Upload failed';
}

/**
 * Drag-and-drop uploader. Files go one at a time (each sends a few chunks in
 * parallel). Retry re-initialises the same upload, so only missing chunks are
 * re-sent; the same happens after a page reload when the file is chosen again.
 */
export function ModelUploader({ modelPk, activeUploads, onChanged }: ModelUploaderProps) {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const controllers = useRef(new Map<string, AbortController>());
  const inputRef = useRef<HTMLInputElement>(null);

  const patch = useCallback((key: string, change: Partial<QueueItem>) => {
    setItems((prev) => prev.map((item) => (item.key === key ? { ...item, ...change } : item)));
  }, []);

  const addFiles = (files: FileList | File[]) => {
    const added: QueueItem[] = Array.from(files).map((file) => {
      const problem = fileProblem(file);
      return {
        key: `f${nextKey++}`,
        file,
        status: problem ? 'invalid' : 'queued',
        uploadedBytes: 0,
        message: problem ?? undefined,
      };
    });
    setItems((prev) => [...prev, ...added]);
  };

  // Start the next queued file when nothing is uploading.
  useEffect(() => {
    if (items.some((i) => i.status === 'uploading' || i.status === 'verifying')) return;
    const next = items.find((i) => i.status === 'queued');
    if (!next) return;

    const controller = new AbortController();
    controllers.current.set(next.key, controller);
    patch(next.key, { status: 'uploading', message: undefined, uploadedBytes: 0 });

    uploadFile(
      modelPk,
      next.file,
      (progress: UploadProgress) =>
        patch(next.key, {
          status: progress.phase === 'verifying' ? 'verifying' : 'uploading',
          uploadedBytes: progress.uploadedBytes,
        }),
      (uploadId) => patch(next.key, { uploadId }),
      controller.signal
    )
      .then((stored) => {
        patch(next.key, {
          status: 'done',
          uploadedBytes: next.file.size,
          message: `sha256 ${stored.sha256}`,
        });
        onChanged();
      })
      .catch((err) => {
        if (controller.signal.aborted) return; // cancel handled the item
        patch(next.key, { status: 'error', message: errorText(err) });
        onChanged();
      })
      .finally(() => controllers.current.delete(next.key));
  }, [items, modelPk, onChanged, patch]);

  // Abort in-flight requests when leaving the page; the server keeps the
  // upload so it can be resumed later.
  useEffect(() => {
    const active = controllers.current;
    return () => active.forEach((c) => c.abort());
  }, []);

  const retry = (key: string) => patch(key, { status: 'queued', message: undefined });

  const cancel = async (item: QueueItem) => {
    controllers.current.get(item.key)?.abort();
    setItems((prev) => prev.filter((i) => i.key !== item.key));
    if (item.uploadId) {
      try {
        await abortUpload(item.uploadId);
      } catch {
        // Stale staging is cleaned up server-side after 24h anyway.
      }
    }
    onChanged();
  };

  const dismiss = (key: string) => setItems((prev) => prev.filter((i) => i.key !== key));

  const discardInterrupted = async (upload: StoreUpload) => {
    try {
      await abortUpload(upload.id);
    } finally {
      onChanged();
    }
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length) addFiles(event.dataTransfer.files);
  };

  // In-progress server uploads not being worked on in this tab.
  const busyIds = new Set(items.map((i) => i.uploadId).filter(Boolean));
  const interrupted = activeUploads.filter((u) => !busyIds.has(u.id));

  return (
    <section className="admin-card admin-uploader">
      <h2 className="admin-card__title">Upload weights</h2>
      <div
        className={`admin-dropzone ${dragging ? 'admin-dropzone--active' : ''}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click();
        }}
      >
        <p className="admin-dropzone__text">
          Drop <strong>.pt</strong> files here, or click to choose
        </p>
        <p className="admin-dropzone__hint">Up to 2 GiB each, 16 files per model</p>
        <input
          ref={inputRef}
          type="file"
          accept=".pt"
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files);
            e.target.value = '';
          }}
        />
      </div>

      {interrupted.length > 0 && (
        <div className="admin-interrupted">
          <p className="admin-interrupted__title">Interrupted uploads</p>
          {interrupted.map((u) => (
            <div key={u.id} className="admin-interrupted__row">
              <span>
                <strong>{u.filename}</strong> — {u.received_chunks.length}/{u.total_chunks} chunks
                received. Choose the same file again to resume.
              </span>
              <button
                type="button"
                className="admin-button admin-button--link"
                onClick={() => discardInterrupted(u)}
              >
                Discard
              </button>
            </div>
          ))}
        </div>
      )}

      {items.length > 0 && (
        <ul className="admin-queue">
          {items.map((item) => {
            const pct = item.file.size ? Math.floor((item.uploadedBytes / item.file.size) * 100) : 0;
            return (
              <li key={item.key} className={`admin-queue__item admin-queue__item--${item.status}`}>
                <div className="admin-queue__head">
                  <span className="admin-queue__name">{item.file.name}</span>
                  <span className="admin-queue__size">{formatBytes(item.file.size)}</span>
                  <span className="admin-queue__state">
                    {item.status === 'queued' && 'Queued'}
                    {item.status === 'uploading' && `${pct}%`}
                    {item.status === 'verifying' && 'Verifying…'}
                    {item.status === 'done' && 'Uploaded'}
                    {item.status === 'error' && 'Failed'}
                    {item.status === 'invalid' && 'Rejected'}
                  </span>
                  <span className="admin-queue__actions">
                    {item.status === 'error' && (
                      <button type="button" className="admin-button admin-button--link" onClick={() => retry(item.key)}>
                        Retry
                      </button>
                    )}
                    {(item.status === 'uploading' || item.status === 'queued') && (
                      <button type="button" className="admin-button admin-button--link" onClick={() => cancel(item)}>
                        Cancel
                      </button>
                    )}
                    {(item.status === 'done' || item.status === 'invalid' || item.status === 'error') && (
                      <button type="button" className="admin-button admin-button--link" onClick={() => dismiss(item.key)}>
                        Dismiss
                      </button>
                    )}
                  </span>
                </div>
                {(item.status === 'uploading' || item.status === 'verifying') && (
                  <div className="admin-progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                    <div className="admin-progress__bar" style={{ width: `${pct}%` }} />
                  </div>
                )}
                {item.message && <p className="admin-queue__message">{item.message}</p>}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
