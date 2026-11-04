import { keepPreviousData, useQuery } from '@tanstack/react-query';
import {
  galleryThumbUrl,
  previewGallery,
  type CustomerReportRequest,
} from '../../state/api/customerReports';

/**
 * The evidence the report would print, chosen exactly as the build chooses
 * it, with a remove button on each. Removing adds the incident's key to
 * `excluded`; the server then returns the set with the next candidate in
 * its place. Each card links to the violation, so an exemption can be
 * dismissed there and drop out of the report altogether.
 */
export interface GalleryPickerProps {
  request: CustomerReportRequest;
  excluded: string[];
  onExclude: (key: string) => void;
  onReset: () => void;
  disabled: boolean;
}

export function GalleryPicker({ request, excluded, onExclude, onReset, disabled }: GalleryPickerProps) {
  const body = { ...request, gallery_exclude: excluded };
  const preview = useQuery({
    queryKey: ['gallery-preview', body],
    queryFn: () => previewGallery(body),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  const items = preview.data?.items ?? [];
  return (
    <div className="customer-report__card gallery-picker">
      <div className="gallery-picker__header">
        <h2 className="customer-report__card-title">Evidence in this report</h2>
        <span className="customer-report__muted">
          {preview.isFetching ? 'Updating…' : `${items.length} images`}
          {excluded.length > 0 && (
            <>
              {' · '}
              {excluded.length} removed{' '}
              <button type="button" className="customer-report__link" onClick={onReset} disabled={disabled}>
                Restore all
              </button>
            </>
          )}
        </span>
      </div>
      <p className="customer-report__hint">
        Remove any image that should not go to the customer; the next incident takes its place.
        For an exemption (e.g. a turban instead of a hard hat), open it and dismiss it as
        “Exempt / not required” so it is not counted either.
      </p>

      {preview.isError && (
        <div className="customer-report__message customer-report__message--error">
          Could not load the evidence: {preview.error instanceof Error ? preview.error.message : 'error'}
        </div>
      )}
      {preview.isLoading && <p className="customer-report__muted">Choosing evidence…</p>}
      {!preview.isLoading && items.length === 0 && !preview.isError && (
        <p className="customer-report__muted">No incidents in this period.</p>
      )}

      <ul className={`gallery-picker__grid ${preview.isFetching ? 'gallery-picker__grid--busy' : ''}`}>
        {items.map((c) => (
          <li key={c.key} className="gallery-picker__item">
            <div className="gallery-picker__thumb">
              {c.violation_id ? (
                <img src={galleryThumbUrl(c.violation_id)} alt={`${c.type_label}, ${c.area}`} loading="lazy" />
              ) : (
                <span className="customer-report__muted">No saved frame</span>
              )}
              <button
                type="button"
                className="gallery-picker__remove"
                aria-label={`Remove ${c.type_label} at ${c.area}, ${c.started}`}
                title="Remove from the report"
                onClick={() => onExclude(c.key)}
                disabled={disabled || preview.isFetching}
              >
                ×
              </button>
            </div>
            <div className="gallery-picker__caption">
              <strong>{c.type_label}</strong> · {c.area}
              <span className="customer-report__muted">
                {c.started} · {c.minutes} min
                {c.violation_id && (
                  <>
                    {' · '}
                    <a href={`/alerts/${c.violation_id}`} target="_blank" rel="noreferrer">
                      Open
                    </a>
                  </>
                )}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
