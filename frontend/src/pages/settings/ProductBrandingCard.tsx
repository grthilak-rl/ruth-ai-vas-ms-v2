import { useEffect, useId, useRef, useState, type ChangeEvent, type FormEvent, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useOutletContext } from 'react-router-dom';
import { useAdminSession } from '../admin/useAdminSession';
import { formatDateTime } from '../admin/format';
import {
  BRAND_IMAGE_SLOTS,
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
import { checkBrandImage, profileInitials, thumbSlot } from './productBrandingRules';
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
 *
 * One form per profile, one Save: text fields and images are edited
 * together, chosen images show as pending until Save, and the form closes
 * when everything is saved.
 */

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

/** What the open form is editing; `key` stays the same when Add creates the profile. */
interface Editing {
  key: string;
  id: string | null;
}

let formSerial = 0;

function BrandProfilesEditor() {
  const queryClient = useQueryClient();
  const branding = useQuery({ queryKey: PROFILES_KEY, queryFn: getProductBranding });
  const [editing, setEditing] = useState<Editing | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const apply = (data: ProductBranding) => {
    queryClient.setQueryData(PROFILES_KEY, data);
    // Every screen (this one included) re-reads the active brand.
    void queryClient.invalidateQueries({ queryKey: ACTIVE_BRAND_QUERY_KEY });
  };

  const run = async (action: () => Promise<ProductBranding>, fallback: string): Promise<boolean> => {
    setBusy(true);
    setError(null);
    setNotice(null);
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

  const open = (next: Editing | null) => {
    setNotice(null);
    setError(null);
    setEditing(next);
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
      if (ok && editing?.id === p.id) setEditing(null);
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
  const editingProfile = editing?.id ? (data.profiles.find((p) => p.id === editing.id) ?? null) : null;

  const saveFields = async (fields: BrandFields): Promise<string> => {
    if (editing?.id) {
      apply(await updateBrandProfile(editing.id, fields));
      return editing.id;
    }
    const before = new Set(data.profiles.map((p) => p.id));
    const next = await createBrandProfile(fields);
    apply(next);
    const created = next.profiles.find((p) => !before.has(p.id));
    if (!created) throw new Error('The profile was added, but could not be found. Reload the page.');
    // Same form (same key): a retry after a failed image saves, not adds again.
    setEditing((e) => (e ? { ...e, id: created.id } : e));
    return created.id;
  };

  const saveImage = async (id: string, slot: BrandImageSlot, change: File | 'remove') => {
    apply(await (change === 'remove' ? deleteBrandImage(id, slot) : uploadBrandImage(id, slot, change)));
  };

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
      {notice && (
        <p className="product-branding__notice" role="status">
          {notice}
        </p>
      )}

      <ul className="product-branding__list" aria-label="Brand profiles">
        {data.profiles.map((p) => (
          <li
            key={p.id}
            className={`product-branding__item${p.active ? ' product-branding__item--active' : ''}`}
          >
            <ProfileThumb profile={p} />
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
                onClick={() => open(editing?.id === p.id ? null : { key: p.id, id: p.id })}
                aria-expanded={editing?.id === p.id}
              >
                {editing?.id === p.id ? 'Close' : 'Edit'}
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
            onClick={() => open({ key: `new-${++formSerial}`, id: null })}
          >
            Add profile
          </button>
        </div>
      )}

      {editing && (
        <ProfileForm
          key={editing.key}
          profile={editingProfile}
          adding={editing.key.startsWith('new-')}
          busy={busy}
          onBusy={setBusy}
          onCancel={() => open(null)}
          onSaveFields={saveFields}
          onSaveImage={saveImage}
          onDone={(message) => {
            setEditing(null);
            setNotice(message);
          }}
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

function ProfileThumb({ profile }: { profile: BrandProfile }) {
  const slot = thumbSlot(profile);
  const initials = (
    <span className="product-branding__thumb product-branding__thumb--initials" aria-hidden="true">
      {profileInitials(profile)}
    </span>
  );
  if (!slot) return initials;
  return (
    <BrandImage
      profile={profile}
      slot={slot}
      className={`product-branding__thumb product-branding__thumb--${slot}`}
      fallback={initials}
    />
  );
}

/**
 * An image of a profile, through the admin endpoint (a blob URL). The
 * version is part of the profile, so a new upload shows at once.
 */
function BrandImage({
  profile,
  slot,
  className,
  fallback = null,
}: {
  profile: BrandProfile;
  slot: BrandImageSlot;
  className?: string;
  fallback?: ReactNode;
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
  if (!url) return <>{fallback}</>;
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

/** An image chosen in the form, saved with the form. */
type PendingImage = { kind: 'file'; file: File; preview: string } | { kind: 'remove' };
type PendingImages = Partial<Record<BrandImageSlot, PendingImage>>;

function ProfileForm({
  profile,
  adding,
  busy,
  onBusy,
  onSaveFields,
  onSaveImage,
  onDone,
  onCancel,
}: {
  /** The saved profile; null while adding (until Add has created it). */
  profile: BrandProfile | null;
  adding: boolean;
  busy: boolean;
  onBusy: (busy: boolean) => void;
  onSaveFields: (fields: BrandFields) => Promise<string>;
  onSaveImage: (id: string, slot: BrandImageSlot, change: File | 'remove') => Promise<void>;
  onDone: (message: string) => void;
  onCancel: () => void;
}) {
  const [fields, setFields] = useState<BrandFields>(() => toFields(profile));
  const [pending, setPending] = useState<PendingImages>({});
  const [localError, setLocalError] = useState<string | null>(null);
  const formId = useId();

  // Preview URLs of chosen files, released when the form closes.
  const previews = useRef(new Set<string>());
  useEffect(() => {
    const urls = previews.current;
    return () => urls.forEach((u) => URL.revokeObjectURL(u));
  }, []);

  const setSlot = (slot: BrandImageSlot, next: PendingImage | undefined) =>
    setPending((p) => {
      const old = p[slot];
      if (old?.kind === 'file') {
        URL.revokeObjectURL(old.preview);
        previews.current.delete(old.preview);
      }
      const copy = { ...p };
      if (next) copy[slot] = next;
      else delete copy[slot];
      return copy;
    });

  const choose = async (slot: BrandImageSlot, file: File) => {
    const problem = await checkBrandImage(slot, file);
    if (problem) {
      setLocalError(`${SLOT_LABEL[slot]}: ${problem}`);
      return;
    }
    setLocalError(null);
    const preview = URL.createObjectURL(file);
    previews.current.add(preview);
    setSlot(slot, { kind: 'file', file, preview });
  };

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
    onBusy(true);
    let id: string;
    try {
      id = await onSaveFields(trimmed);
    } catch (e: unknown) {
      setLocalError(errorText(e, adding ? 'Could not add the profile' : 'Could not save the profile'));
      onBusy(false);
      return;
    }
    let images = 0;
    for (const slot of BRAND_IMAGE_SLOTS) {
      const change = pending[slot];
      if (!change) continue;
      try {
        await onSaveImage(id, slot, change.kind === 'file' ? change.file : 'remove');
      } catch (e: unknown) {
        // What is saved stays saved; what failed stays pending, so Save retries it.
        setLocalError(
          `“${trimmed.name}” is saved, but the ${SLOT_LABEL[slot].toLowerCase()} is not: ` +
            `${errorText(e, 'the server refused it')}`
        );
        onBusy(false);
        return;
      }
      setSlot(slot, undefined);
      images += 1;
    }
    onBusy(false);
    const what = images === 0 ? '' : images === 1 ? ' with 1 image change' : ` with ${images} image changes`;
    onDone(`${adding ? 'Added' : 'Saved'} “${trimmed.name}”${what}.`);
  };

  const pendingCount = Object.keys(pending).length;

  return (
    <form className="product-branding__form" onSubmit={submit} aria-label="Brand profile">
      <h3 className="product-branding__form-title">
        {adding ? 'New brand profile' : `Edit “${profile?.name ?? ''}”`}
      </h3>
      {localError && (
        <p className="admin-login__error" role="alert">
          {localError}
        </p>
      )}
      <div className="product-branding__fields">
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
      </div>

      <div className="product-branding__images" role="group" aria-labelledby={`${formId}-images`}>
        <h4 id={`${formId}-images`} className="product-branding__images-title">
          Logos and icon
        </h4>
        {BRAND_IMAGE_SLOTS.map((slot) => (
          <ImageSlot
            key={slot}
            profile={profile}
            slot={slot}
            pending={pending[slot]}
            busy={busy}
            onChoose={(file) => void choose(slot, file)}
            onRemove={() => setSlot(slot, { kind: 'remove' })}
            onUndo={() => setSlot(slot, undefined)}
          />
        ))}
        <p className="admin-muted">
          PNG or JPEG, up to 1 MB. Chosen images are saved with the profile. They are checked and
          re-encoded on the server; SVG is not accepted.
        </p>
      </div>

      <div className="product-branding__form-actions">
        <button type="submit" className="admin-button" disabled={busy}>
          {busy ? 'Saving…' : adding && !profile ? 'Add profile' : 'Save'}
        </button>
        <button type="button" className="admin-button admin-button--secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        {pendingCount > 0 && (
          <span className="admin-muted">
            {pendingCount === 1 ? '1 image change' : `${pendingCount} image changes`} not saved yet
          </span>
        )}
      </div>
    </form>
  );
}

function ImageSlot({
  profile,
  slot,
  pending,
  busy,
  onChoose,
  onRemove,
  onUndo,
}: {
  profile: BrandProfile | null;
  slot: BrandImageSlot;
  pending: PendingImage | undefined;
  busy: boolean;
  onChoose: (file: File) => void;
  onRemove: () => void;
  onUndo: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const saved = Boolean(profile?.images[slot]);
  const builtin = Boolean(profile?.builtin_images.includes(slot));

  const picked = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) onChoose(file);
  };

  let preview: ReactNode;
  let status: ReactNode = null;
  if (pending?.kind === 'file') {
    preview = <img src={pending.preview} alt="" />;
    status = <span className="admin-badge product-branding__badge--pending">Will be saved</span>;
  } else if (pending?.kind === 'remove') {
    preview = <span className="admin-muted">Removed when you save</span>;
    status = <span className="admin-badge product-branding__badge--pending">Will be removed</span>;
  } else if (saved && profile) {
    preview = <BrandImage profile={profile} slot={slot} />;
    status = <span className="admin-badge admin-badge--uploaded">{builtin ? 'Built in' : 'Saved'}</span>;
  } else {
    preview = <span className="admin-muted">None</span>;
  }

  return (
    <div className="product-branding__slot" data-slot={slot}>
      <span className="product-branding__slot-head">
        <span className="admin-field__label">{SLOT_LABEL[slot]}</span>
        {status}
      </span>
      <div className={`product-branding__preview product-branding__preview--${slot}`}>{preview}</div>
      <p className="admin-muted">{SLOT_HELP[slot]}</p>
      <div className="product-branding__slot-actions">
        <input
          ref={input}
          type="file"
          accept="image/png,image/jpeg"
          hidden
          onChange={picked}
          aria-label={SLOT_LABEL[slot]}
        />
        <button type="button" className="admin-button admin-button--secondary" disabled={busy} onClick={() => input.current?.click()}>
          {saved || pending?.kind === 'file' ? 'Replace' : 'Choose file'}
        </button>
        {pending ? (
          <button type="button" className="admin-button admin-button--link" disabled={busy} onClick={onUndo}>
            {pending.kind === 'file' && !saved ? 'Remove' : 'Undo'}
          </button>
        ) : (
          saved && (
            <button type="button" className="admin-button admin-button--link" disabled={busy} onClick={onRemove}>
              Remove
            </button>
          )
        )}
      </div>
    </div>
  );
}
