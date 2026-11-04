import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useOutletContext } from 'react-router-dom';
import { useAdminSession } from '../admin/useAdminSession';
import { formatDateTime } from '../admin/format';
import {
  MAX_LOGO_BYTES,
  deleteLogo,
  fetchLogoUrl,
  getReportBranding,
  setCustomerName,
  uploadLogo,
} from '../../state/api/customerReports';
import { InlineAdminSignIn } from './InlineAdminSignIn';
import type { SettingsOutletContext } from './SettingsLayout';
import '../admin/AdminPages.css';
import './SettingsBrandingTab.css';

/**
 * Settings -> Report branding. Path: /settings/branding.
 *
 * The customer name and logo on the customer report's cover and page
 * headers. Admin-only; the whole tab is gated inline because there is
 * nothing to show signed out. The logo is checked here (type, size) for a
 * quick answer, and again on the server, which re-encodes it.
 */

const ACCEPTED = ['image/png', 'image/jpeg'];

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function SettingsBrandingTab() {
  const { isSignedIn } = useAdminSession();
  const { sessionExpired } = useOutletContext<SettingsOutletContext>();

  if (!isSignedIn) {
    return (
      <section className="admin-card">
        <h2 className="admin-card__title">Report branding</h2>
        <p className="admin-card__subtitle">
          The customer name and logo shown on customer reports.
        </p>
        <InlineAdminSignIn capability="change the report branding" expired={sessionExpired} />
      </section>
    );
  }
  return <BrandingForm />;
}

function BrandingForm() {
  const queryClient = useQueryClient();
  const branding = useQuery({ queryKey: ['report-branding'], queryFn: getReportBranding });

  const [name, setName] = useState('');
  const [nameSaved, setNameSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logoUrl, setLogoUrl] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (branding.data) setName(branding.data.customer_name ?? '');
  }, [branding.data]);

  // The logo endpoint needs the admin header, so the preview is a blob URL.
  const hasLogo = branding.data?.has_logo ?? false;
  const updatedAt = branding.data?.updated_at;
  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    if (hasLogo) {
      fetchLogoUrl().then((u) => {
        if (cancelled) {
          if (u) URL.revokeObjectURL(u);
          return;
        }
        url = u;
        setLogoUrl(u);
      });
    } else {
      setLogoUrl(null);
    }
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [hasLogo, updatedAt]);

  const refresh = (data: Awaited<ReturnType<typeof getReportBranding>>) =>
    queryClient.setQueryData(['report-branding'], data);

  const saveName = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNameSaved(false);
    try {
      refresh(await setCustomerName(name.trim()));
      setNameSaved(true);
    } catch (e: unknown) {
      setError(errorText(e, 'Could not save the name'));
    } finally {
      setBusy(false);
    }
  };

  const chooseLogo = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setError(null);
    if (!ACCEPTED.includes(file.type)) {
      setError('The logo must be a PNG or JPEG image.');
      return;
    }
    if (file.size > MAX_LOGO_BYTES) {
      setError('The logo must be 1 MB or smaller.');
      return;
    }
    setBusy(true);
    try {
      refresh(await uploadLogo(file));
    } catch (e: unknown) {
      setError(errorText(e, 'Could not upload the logo'));
    } finally {
      setBusy(false);
    }
  };

  const removeLogo = async () => {
    setBusy(true);
    setError(null);
    try {
      refresh(await deleteLogo());
    } catch (e: unknown) {
      setError(errorText(e, 'Could not remove the logo'));
    } finally {
      setBusy(false);
    }
  };

  if (branding.isLoading) {
    return <section className="admin-card">Loading…</section>;
  }
  if (branding.isError) {
    return (
      <section className="admin-card">
        <p className="admin-login__error">{errorText(branding.error, 'Could not load branding')}</p>
      </section>
    );
  }

  return (
    <section className="admin-card branding">
      <h2 className="admin-card__title">Report branding</h2>
      <p className="admin-card__subtitle">
        Shown on the cover and in the page headers of every customer report generated from now
        on. Reports already generated keep the branding they were built with.
      </p>

      {error && <p className="admin-login__error" role="alert">{error}</p>}

      <form className="branding__row" onSubmit={saveName}>
        <label className="admin-field">
          <span className="admin-field__label">Customer name</span>
          <input
            className="admin-field__input"
            value={name}
            maxLength={120}
            placeholder="e.g. the client's company name"
            onChange={(e) => {
              setName(e.target.value);
              setNameSaved(false);
            }}
            disabled={busy}
          />
        </label>
        <button type="submit" className="admin-button" disabled={busy}>
          Save name
        </button>
        {nameSaved && <span className="admin-muted">Saved.</span>}
      </form>

      <div className="branding__logo">
        <span className="admin-field__label">Logo</span>
        <div className="branding__preview">
          {logoUrl ? (
            <img src={logoUrl} alt="Customer logo" />
          ) : (
            <span className="admin-muted">
              No logo. The cover shows the customer name instead.
            </span>
          )}
        </div>
        <p className="admin-muted">
          PNG or JPEG, up to 1 MB. A wide logo on a transparent or white background prints best;
          it is scaled to fit 170 × 64 points on the cover.
        </p>
        <div className="branding__actions">
          <input
            ref={fileInput}
            type="file"
            accept="image/png,image/jpeg"
            hidden
            onChange={chooseLogo}
          />
          <button
            type="button"
            className="admin-button"
            onClick={() => fileInput.current?.click()}
            disabled={busy}
          >
            {hasLogo ? 'Replace logo' : 'Upload logo'}
          </button>
          {hasLogo && (
            <button
              type="button"
              className="admin-button admin-button--secondary"
              onClick={removeLogo}
              disabled={busy}
            >
              Remove logo
            </button>
          )}
        </div>
      </div>

      {branding.data?.updated_at && (
        <p className="admin-muted">
          Last changed {formatDateTime(branding.data.updated_at)}
          {branding.data.updated_by ? ` by ${branding.data.updated_by}` : ''}.
        </p>
      )}
    </section>
  );
}
