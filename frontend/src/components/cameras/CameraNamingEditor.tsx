import { useState } from 'react';
import {
  useManwaysQuery,
  useUpdateDeviceNamingMutation,
} from '../../state/hooks/useDevicesQuery';
import { deriveDisplayName } from '../../state/api/devices.api';
import './CameraNamingEditor.css';

interface CameraNamingEditorProps {
  /** Ruth AI internal device UUID */
  deviceId: string;
  /** Stable identifier (e.g. CUG3PTZ10072) — never edited, always the suffix */
  identifier: string;
  /** Current grouping key, or null when unassigned */
  manway?: string | null;
  /** Current side, or null when unassigned */
  inOut?: 'IN' | 'OUT' | null;
  /** Name currently displayed (derived by VAS) */
  displayName: string;
}

/**
 * Inline structured-naming editor for a camera cell.
 *
 * VAS owns manway / in_out and derives display_name from them; this writes
 * through Ruth's proxy to VAS rather than storing anything locally.
 *
 * Read-only until the pencil is clicked, and nothing is sent until Save — a
 * stray click in the monitoring grid must not rename a camera. The preview
 * mirrors VAS's derivation so the operator sees the resulting name before
 * committing.
 */
export function CameraNamingEditor({
  deviceId,
  identifier,
  manway,
  inOut,
  displayName,
}: CameraNamingEditorProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [manwayDraft, setManwayDraft] = useState('');
  const [inOutDraft, setInOutDraft] = useState<'IN' | 'OUT' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: manways = [] } = useManwaysQuery();
  const mutation = useUpdateDeviceNamingMutation();

  const openEditor = () => {
    setManwayDraft(manway ?? '');
    setInOutDraft(inOut ?? null);
    setError(null);
    setIsEditing(true);
  };

  const closeEditor = () => {
    setIsEditing(false);
    setError(null);
  };

  /** Cycle IN -> OUT -> unset, matching the VAS Devices page control. */
  const cycleInOut = () => {
    setInOutDraft((prev) => (prev === 'IN' ? 'OUT' : prev === 'OUT' ? null : 'IN'));
  };

  const handleSave = () => {
    const nextManway = manwayDraft.trim().toUpperCase() || null;

    // Nothing changed — close without a pointless round trip.
    if (nextManway === (manway ?? null) && inOutDraft === (inOut ?? null)) {
      closeEditor();
      return;
    }

    setError(null);
    mutation.mutate(
      { deviceId, update: { manway: nextManway, in_out: inOutDraft } },
      {
        onSuccess: () => setIsEditing(false),
        // The mutation already rolled the cache back; keep the editor open
        // with the operator's input intact so they can retry.
        onError: (err: unknown) =>
          setError(err instanceof Error ? err.message : 'Failed to save — VAS rejected the change'),
      }
    );
  };

  if (!isEditing) {
    return (
      <span className="camera-naming">
        <span className="camera-naming__label" title={identifier}>
          {displayName}
        </span>
        <button
          type="button"
          className="camera-naming__edit"
          onClick={openEditor}
          title="Edit manway / in-out"
          aria-label={`Edit naming for ${identifier}`}
        >
          ✎
        </button>
      </span>
    );
  }

  const preview = deriveDisplayName(identifier, manwayDraft, inOutDraft);
  const isSaving = mutation.isPending;

  return (
    <div className="camera-naming camera-naming--editing">
      <div className="camera-naming__row">
        <input
          type="text"
          className="camera-naming__input"
          list={`manways-${deviceId}`}
          placeholder="Manway"
          aria-label="Manway"
          value={manwayDraft}
          disabled={isSaving}
          autoFocus
          onChange={(e) => setManwayDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleSave();
            if (e.key === 'Escape') closeEditor();
          }}
        />
        <datalist id={`manways-${deviceId}`}>
          {manways.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>

        <button
          type="button"
          className={`camera-naming__inout camera-naming__inout--${(inOutDraft ?? 'unset').toLowerCase()}`}
          onClick={cycleInOut}
          disabled={isSaving}
          title="Click to cycle: IN → OUT → not set"
        >
          {inOutDraft ?? 'Not set'}
        </button>
      </div>

      <div className="camera-naming__preview" title="Derived by VAS from Manway + In/Out + Device ID">
        {preview}
      </div>

      {error && <div className="camera-naming__error">{error}</div>}

      <div className="camera-naming__actions">
        <button
          type="button"
          className="camera-naming__save"
          onClick={handleSave}
          disabled={isSaving}
        >
          {isSaving ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          className="camera-naming__cancel"
          onClick={closeEditor}
          disabled={isSaving}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
