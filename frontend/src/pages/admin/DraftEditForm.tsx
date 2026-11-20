import { useState, type FormEvent } from 'react';
import { useMutation } from '@tanstack/react-query';
import { AdminApiError, updateStoreModel, type StoreModelDetail } from './adminApi';
import { modelIdFromName, modelIdProblem } from './modelIds';

interface DraftEditFormProps {
  model: StoreModelDetail;
  onSaved: (model: StoreModelDetail) => void;
  onCancel: () => void;
}

/**
 * Rename a draft: display name always, model ID until the model is
 * installed. Files stay where they are (stored by the draft's internal id),
 * so nothing is re-uploaded.
 */
export function DraftEditForm({ model, onSaved, onCancel }: DraftEditFormProps) {
  const [displayName, setDisplayName] = useState(model.display_name);
  const [modelId, setModelId] = useState(model.model_id);

  const name = displayName.trim();
  const idChanged = model.model_id_editable && modelId !== model.model_id;
  const nameProblem = name ? null : 'Display name is required';
  const idProblem = idChanged ? modelIdProblem(modelId) : null;
  const changed = name !== model.display_name || idChanged;

  const save = useMutation({
    mutationFn: () =>
      updateStoreModel(model.id, {
        ...(name !== model.display_name ? { display_name: name } : {}),
        ...(idChanged ? { model_id: modelId } : {}),
      }),
    onSuccess: (saved) => onSaved(saved),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!changed || nameProblem || idProblem) return;
    save.mutate();
  };

  const suggested = modelIdFromName(name);

  return (
    <form className="admin-card draft-edit" onSubmit={submit} aria-label="Edit draft">
      <h2 className="admin-card__title">Edit draft</h2>

      <label className="admin-field">
        <span className="admin-field__label">Display name</span>
        <input
          className="admin-field__input"
          value={displayName}
          maxLength={128}
          onChange={(e) => setDisplayName(e.target.value)}
          autoFocus
        />
        <span className="admin-muted draft-edit__hint">
          What operators see in the camera picker, e.g. "Harness v3".
        </span>
        {nameProblem && <span className="draft-edit__problem">{nameProblem}</span>}
      </label>

      <label className="admin-field">
        <span className="admin-field__label">Model ID</span>
        <input
          className="admin-field__input admin-mono"
          value={modelId}
          maxLength={48}
          onChange={(e) => setModelId(e.target.value)}
          disabled={!model.model_id_editable}
          spellCheck={false}
          autoCapitalize="off"
          aria-invalid={idProblem ? true : undefined}
        />
        {model.model_id_editable ? (
          <span className="admin-muted draft-edit__hint">
            Lowercase letters, digits and underscores. Cannot change once the model is installed.
            {suggested && suggested !== modelId && (
              <>
                {' '}
                <button
                  type="button"
                  className="admin-button admin-button--link"
                  onClick={() => setModelId(suggested)}
                >
                  Use "{suggested}"
                </button>
              </>
            )}
          </span>
        ) : (
          <span className="admin-muted draft-edit__hint">
            Locked: this model is installed, and cameras and saved violations refer to it by this ID.
          </span>
        )}
        {idProblem && <span className="draft-edit__problem">{idProblem}</span>}
      </label>

      {save.isError && (
        <p className="admin-login__error" role="alert">
          {save.error instanceof AdminApiError ? save.error.message : 'Save failed'}
        </p>
      )}

      <div className="draft-edit__actions">
        <button
          type="submit"
          className="admin-button"
          disabled={!changed || !!nameProblem || !!idProblem || save.isPending}
        >
          {save.isPending ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className="admin-button admin-button--secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
