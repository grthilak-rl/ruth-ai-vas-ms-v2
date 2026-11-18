import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useOutletContext } from 'react-router-dom';
import { useAdminSession } from '../admin/useAdminSession';
import { formatDateTime } from '../admin/format';
import {
  BRAND_IMAGE_SLOTS,
  MAX_BRAND_IMAGE_BYTES,
  activateBrandProfile,
  contrastOnWhite,
  createBrandProfile,
  deleteBrandImage,
  deleteBrandProfile,
  fetchBrandImageUrl,
  getProductBranding,
  updateBrandProfile,
  uploadBrandImage,
  type BrandFields,
  type BrandImageSlot,
  type BrandProfile,
  type ProductBranding,
} from '../../state/api/branding.api';
import { ACTIVE_BRAND_QUERY_KEY, useBrand } from '../../state/brand/brand';
import { InlineAdminSignIn } from './InlineAdminSignIn';
import type { SettingsOutletContext } from './SettingsLayout';
import '../admin/AdminPages.css';
import './ProductBrandingCard.css';

/**
 * Settings -> System -> Branding: whose product this is (white-label).
 *
 * Brand profiles (Visics, RuthLabs for investor demos, a licensee's), one
 * active, switched in one click. The active brand names the product in the
 * header, the sign-in page, the tab title and favicon, report covers and
 * footers, and export file names. Not the customer on report covers: that
 * is Settings -> Reports.
 *
 * Anyone can see which brand is active; changing anything is admin-only.
 */

const ACCEPTED = ['image/png', 'image/jpeg'];
const PROFILES_KEY = ['product-branding'] as const;

const SLOT_LABEL: Record<BrandImageSlot, string> = {
  logo_light: 'Logo for light backgrounds',
  logo_dark: 'Logo for dark backgrounds',
  icon: 'Icon (browser tab)',
};

const SLOT_HELP: Record<BrandImageSlot, string> = {
  logo_light: 'Header, sign-in page and report cover. A wide logo, up to 600 × 300 px.',
  logo_dark: 'For dark surfaces. Optional: the light logo is used when this is empty.',
  icon: 'Square, at least 64 × 64 px. Shown as the favicon.',
};

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function ProductBrandingCard() {
  const { isSignedIn } = useAdminSession();
  const { sessionExpired } = useOutletContext<SettingsOutletContext>();
  const brand = useBrand();

  if (!isSignedIn) {
    return (
      <section className="admin-card product-branding">
        <h2 className="admin-card__title">Branding</h2>
        <p className="admin-card__subtitle">
          Whose product this is: the name and logo in the header, on the sign-in page and on
          reports. Active now: <strong>{brand.ready ? brand.productName : '…'}</strong>.
        </p>
        <InlineAdminSignIn capability="switch or edit the product branding" expired={sessionExpired} />
      </section>
    );
  }
  return <BrandProfilesEditor />;
}

function BrandProfilesEditor() {
  const queryClient = useQueryClient();
  const branding = useQuery({ queryKey: PROFILES_KEY, queryFn: getProductBranding });
  const [editing, setEditing] = useState<string | 'new' | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const apply = (data: ProductBranding) => {
    queryClient.setQueryData(PROFILES_KEY, data);
    // Every screen (this one included) re-reads the active brand.
    void queryClient.invalidateQueries({ queryKey: ACTIVE_BRAND_QUERY_KEY });
  };

  const run = async (action: () => Promise<ProductBranding>, fallback: string): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      apply(await action());
      return true;
    } catch (e: unknown) {
      setError(errorText(e, fallback));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const activate = (p: BrandProfile) => {
    const ok = window.confirm(
      `Switch the product brand to "${p.name}"?\n\n` +
        `Everyone using this server will see "${p.product_name}" in the header, on the sign-in ` +
        `page and in the browser tab, and reports generated from now on are prepared by ` +
        `${p.product_name}. Open screens follow within a minute.`
    );
    if (ok) void run(() => activateBrandProfile(p.id), 'Could not switch the brand');
  };

  const remove = (p: BrandProfile) => {
    if (!window.confirm(`Delete the brand profile "${p.name}" and its images?`)) return;
    void run(() => deleteBrandProfile(p.id), 'Could not delete the profile').then((ok) => {
      if (ok && editing === p.id) setEditing(null);
    });
  };

  if (branding.isLoading) return <section className="admin-card">Loading…</section>;
  if (branding.isError || !branding.data) {
    return (
      <section className="admin-card">
        <p className="admin-login__error">{errorText(branding.error, 'Could not load branding')}</p>
      </section>
    );
  }

  const data = branding.data;
  const editingProfile = data.profiles.find((p) => p.id === editing) ?? null;

  return (
    <section className="admin-card product-branding">
      <h2 className="admin-card__title">Branding</h2>
      <p className="admin-card__subtitle">
        Whose product this is: the name and logo in the header, on the sign-in page, in the
        browser tab and on reports ("Prepared by", footer). One profile is active. The customer
        named on report covers is set under Reports.
      </p>

      {error && (
        <p className="admin-login__error" role="alert">
          {error}
        </p>
      )}

      <ul className="product-branding__list" aria-label="Brand profiles">
        {data.profiles.map((p) => (
          <li
            key={p.id}
            className={`product-branding__item${p.active ? ' product-branding__item--active' : ''}`}
          >
            <BrandImage profile={p} slot="icon" className="product-branding__icon" />
            <div className="product-branding__names">
              <span className="product-branding__name">{p.name}</span>
              <span className="admin-muted">{p.product_name}</span>
            </div>
            <div className="product-branding__item-actions">
              {p.active ? (
                <span className="admin-badge admin-badge--uploaded">Active</span>
              ) : (
                <button type="button" className="admin-button" disabled={busy} onClick={() => activate(p)}>
                  Activate
                </button>
              )}
              <button
                type="button"
                className="admin-button admin-button--secondary"
                disabled={busy}
                onClick={() => setEditing(editing === p.id ? null : p.id)}
                aria-expanded={editing === p.id}
              >
                {editing === p.id ? 'Close' : 'Edit'}
              </button>
              <button
                type="button"
                className="admin-button admin-button--link"
                disabled={busy || p.active}
                title={p.active ? 'The active profile cannot be deleted' : undefined}
                onClick={() => remove(p)}
              >
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>

      {editing === null && (
        <div>
          <button
            type="button"
            className="admin-button admin-button--secondary"
            disabled={busy}
            onClick={() => setEditing('new')}
          >
            Add profile
          </button>
        </div>
      )}

      {editing === 'new' && (
        <ProfileForm
          key="new"
          profile={null}
          busy={busy}
          onCancel={() => setEditing(null)}
          onSave={async (fields) => {
            setBusy(true);
            setError(null);
            try {
              const before = new Set(data.profiles.map((p) => p.id));
              const next = await createBrandProfile(fields);
              apply(next);
              // Stay on the new profile so its images can be uploaded.
              setEditing(next.profiles.find((p) => !before.has(p.id))?.id ?? null);
            } catch (e: unknown) {
              setError(errorText(e, 'Could not add the profile'));
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {editingProfile && (
        <ProfileForm
          key={editingProfile.id}
          profile={editingProfile}
          busy={busy}
          onCancel={() => setEditing(null)}
          onSave={(fields) =>
            run(() => updateBrandProfile(editingProfile.id, fields), 'Could not save the profile').then(
              () => undefined
            )
          }
          onUpload={(slot, file) =>
            run(() => uploadBrandImage(editingProfile.id, slot, file), 'Could not upload the image')
          }
          onRemoveImage={(slot) =>
            run(() => deleteBrandImage(editingProfile.id, slot), 'Could not remove the image')
          }
        />
      )}

      {data.updated_at && (
        <p className="admin-muted">
          Last changed {formatDateTime(data.updated_at)}
          {data.updated_by ? ` by ${data.updated_by}` : ''}.
        </p>
      )}
    </section>
  );
}

/** An image of a profile, through the admin endpoint (a blob URL). */
function BrandImage({
  profile,
  slot,
  className,
}: {
  profile: BrandProfile;
  slot: BrandImageSlot;
  className?: string;
}) {
  const version = profile.images[slot];
  // The blob URL with the version it shows, so a stale one is never used.
  const [loaded, setLoaded] = useState<{ version: string; url: string | null } | null>(null);

  useEffect(() => {
    if (!version) return;
    let created: string | null = null;
    let cancelled = false;
    fetchBrandImageUrl(profile.id, slot).then((u) => {
      if (cancelled) {
        if (u) URL.revokeObjectURL(u);
        return;
      }
      created = u;
      setLoaded({ version, url: u });
    });
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [profile.id, slot, version]);

  const url = version && loaded?.version === version ? loaded.url : null;
  if (!url) return <span className={`${className ?? ''} product-branding__empty`} aria-hidden="true" />;
  return <img src={url} alt="" className={className} />;
}

function toFields(p: BrandProfile | null): BrandFields {
  return {
    name: p?.name ?? '',
    product_name: p?.product_name ?? '',
    short_name: p?.short_name ?? '',
    assistant_name: p?.assistant_name ?? '',
    accent: p?.accent ?? '',
    report_note: p?.report_note ?? '',
  };
}

function ProfileForm({
  profile,
  busy,
  onSave,
  onCancel,
  onUpload,
  onRemoveImage,
}: {
  profile: BrandProfile | null;
  busy: boolean;
  onSave: (fields: BrandFields) => Promise<void>;
  onCancel: () => void;
  onUpload?: (slot: BrandImageSlot, file: File) => Promise<boolean>;
  onRemoveImage?: (slot: BrandImageSlot) => Promise<boolean>;
}) {
  const [fields, setFields] = useState<BrandFields>(() => toFields(profile));
  const [localError, setLocalError] = useState<string | null>(null);

  const set = (key: keyof BrandFields) => (e: ChangeEvent<HTMLInputElement>) =>
    setFields((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = Object.fromEntries(
      Object.entries(fields).map(([k, v]) => [k, typeof v === 'string' && v.trim() ? v.trim() : null])
    ) as unknown as BrandFields;
    if (!trimmed.name || !trimmed.product_name) {
      setLocalError('A profile needs a label and a product name.');
      return;
    }
    if (trimmed.accent && !/^#[0-9a-fA-F]{6}$/.test(trimmed.accent)) {
      setLocalError('The accent must be a colour like #2a78d6.');
      return;
    }
    if (trimmed.accent && contrastOnWhite(trimmed.accent) < 3) {
      setLocalError(
        `The accent ${trimmed.accent} is too light to read on white ` +
          `(${contrastOnWhite(trimmed.accent).toFixed(1)}:1, needs 3:1). Pick a darker colour.`
      );
      return;
    }
    setLocalError(null);
    await onSave(trimmed);
  };

  return (
    <div className="product-branding__form">
      <h3 className="product-branding__form-title">
        {profile ? `Edit “${profile.name}”` : 'New brand profile'}
      </h3>
      {localError && (
        <p className="admin-login__error" role="alert">
          {localError}
        </p>
      )}
      <form className="product-branding__fields" onSubmit={submit}>
        <label className="admin-field">
          <span className="admin-field__label">Label (only shown here)</span>
          <input className="admin-field__input" value={fields.name} maxLength={60} onChange={set('name')} placeholder="e.g. RuthLabs (investor demo)" disabled={busy} />
        </label>
        <label className="admin-field">
          <span className="admin-field__label">Product name</span>
          <input className="admin-field__input" value={fields.product_name} maxLength={60} onChange={set('product_name')} placeholder="e.g. Ruth AI" disabled={busy} />
        </label>
        <label className="admin-field">
          <span className="admin-field__label">Short name (optional)</span>
          <input className="admin-field__input" value={fields.short_name ?? ''} maxLength={30} onChange={set('short_name')} disabled={busy} />
        </label>
        <label className="admin-field">
          <span className="admin-field__label">Assistant name (optional, “Ask …” on the Overview)</span>
          <input className="admin-field__input" value={fields.assistant_name ?? ''} maxLength={30} onChange={set('assistant_name')} placeholder="e.g. Ruth" disabled={busy} />
        </label>
        <label className="admin-field">
          <span className="admin-field__label">Accent colour (optional)</span>
          <span className="product-branding__accent">
            <input className="admin-field__input" value={fields.accent ?? ''} maxLength={7} onChange={set('accent')} placeholder="#2a78d6" disabled={busy} />
            {fields.accent && /^#[0-9a-fA-F]{6}$/.test(fields.accent) && (
              <span className="product-branding__swatch" style={{ background: fields.accent }} aria-hidden="true" />
            )}
          </span>
        </label>
        <label className="admin-field">
          <span className="admin-field__label">Report cover note (optional, beside “Prepared by”)</span>
          <input className="admin-field__input" value={fields.report_note ?? ''} maxLength={120} onChange={set('report_note')} disabled={busy} />
        </label>
        <div className="product-branding__form-actions">
          <button type="submit" className="admin-button" disabled={busy}>
            {profile ? 'Save' : 'Add profile'}
          </button>
          <button type="button" className="admin-button admin-button--secondary" onClick={onCancel} disabled={busy}>
            {profile ? 'Close' : 'Cancel'}
          </button>
        </div>
      </form>

      {profile && onUpload && onRemoveImage ? (
        <div className="product-branding__images">
          {BRAND_IMAGE_SLOTS.map((slot) => (
            <ImageSlot
              key={slot}
              profile={profile}
              slot={slot}
              busy={busy}
              onError={setLocalError}
              onUpload={(file) => onUpload(slot, file)}
              onRemove={() => onRemoveImage(slot)}
            />
          ))}
          <p className="admin-muted">
            PNG or JPEG, up to 1 MB. Images are checked and re-encoded on the server; SVG is not
            accepted.
          </p>
        </div>
      ) : (
        <p className="admin-muted">Logos and the icon can be uploaded once the profile is added.</p>
      )}
    </div>
  );
}

function ImageSlot({
  profile,
  slot,
  busy,
  onError,
  onUpload,
  onRemove,
}: {
  profile: BrandProfile;
  slot: BrandImageSlot;
  busy: boolean;
  onError: (message: string | null) => void;
  onUpload: (file: File) => Promise<boolean>;
  onRemove: () => Promise<boolean>;
}) {
  const input = useRef<HTMLInputElement>(null);
  const hasImage = Boolean(profile.images[slot]);
  const builtin = profile.builtin_images.includes(slot);

  const choose = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!ACCEPTED.includes(file.type)) {
      onError('Images must be PNG or JPEG.');
      return;
    }
    if (file.size > MAX_BRAND_IMAGE_BYTES) {
      onError('Images must be 1 MB or smaller.');
      return;
    }
    onError(null);
    void onUpload(file);
  };

  return (
    <div className="product-branding__slot">
      <span className="admin-field__label">{SLOT_LABEL[slot]}</span>
      <div className={`product-branding__preview product-branding__preview--${slot}`}>
        {hasImage ? (
          <BrandImage profile={profile} slot={slot} />
        ) : (
          <span className="admin-muted">None</span>
        )}
      </div>
      <p className="admin-muted">
        {SLOT_HELP[slot]}
        {builtin ? ' Built in.' : ''}
      </p>
      <div className="product-branding__slot-actions">
        <input ref={input} type="file" accept="image/png,image/jpeg" hidden onChange={choose} />
        <button type="button" className="admin-button admin-button--secondary" disabled={busy} onClick={() => input.current?.click()}>
          {hasImage ? 'Replace' : 'Upload'}
        </button>
        {hasImage && (
          <button type="button" className="admin-button admin-button--link" disabled={busy} onClick={() => void onRemove()}>
            Remove
          </button>
        )}
      </div>
    </div>
  );
}
