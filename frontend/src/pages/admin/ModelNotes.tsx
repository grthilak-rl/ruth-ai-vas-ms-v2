import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AdminApiError,
  clearRecommendation,
  createModelNote,
  deleteModelNote,
  listModelNotes,
  listProjects,
  listRecommendations,
  setRecommendation,
  updateModelNote,
  type ModelNote,
  type ModelNoteInput,
  type StoreModelDetail,
} from './adminApi';

/**
 * Notes and the recommended-model flag on a model's page.
 *
 * Notes are dated observations ("HPCL: fires on scaffold planks"). The
 * newest one not marked internal is shown under the model in the camera
 * picker. A recommendation names, per violation type, the model operators
 * should prefer, with one of its notes as the reason.
 */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function formatObservedOn(isoDate: string): string {
  const [y, m, d] = isoDate.split('-').map(Number);
  if (!y || !m || !d) return isoDate;
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

function todayIso(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof AdminApiError ? error.message : fallback;
}

const notesKey = (modelPk: string) => ['admin', 'model-store', 'notes', modelPk];
const RECOMMENDATIONS_KEY = ['admin', 'model-store', 'recommendations'];

// ---------------------------------------------------------------------------
// Note form (add and edit)
// ---------------------------------------------------------------------------

interface NoteFormProps {
  initial?: ModelNote;
  projects: { id: string; name: string }[];
  saving: boolean;
  error: string | null;
  onSave: (note: ModelNoteInput) => void;
  onCancel: () => void;
}

function NoteForm({ initial, projects, saving, error, onSave, onCancel }: NoteFormProps) {
  const [observedOn, setObservedOn] = useState(initial?.observed_on ?? todayIso());
  const [projectId, setProjectId] = useState(initial?.project_id ?? '');
  const [body, setBody] = useState(initial?.body ?? '');
  const [source, setSource] = useState(initial?.source ?? '');
  const [internal, setInternal] = useState(initial?.internal ?? false);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!body.trim() || !observedOn) return;
    onSave({
      body: body.trim(),
      observed_on: observedOn,
      project_id: projectId || null,
      source: source.trim() || null,
      internal,
    });
  };

  return (
    <form className="model-notes__form" onSubmit={submit} aria-label={initial ? 'Edit note' : 'Add note'}>
      <div className="model-notes__form-row">
        <label className="admin-field">
          <span className="admin-field__label">Observed on</span>
          <input
            className="admin-field__input"
            type="date"
            value={observedOn}
            onChange={(e) => setObservedOn(e.target.value)}
            required
          />
        </label>
        <label className="admin-field">
          <span className="admin-field__label">Project (optional)</span>
          <select className="admin-field__input" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">None</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="admin-field">
        <span className="admin-field__label">Note</span>
        <textarea
          className="admin-field__input model-notes__textarea"
          value={body}
          maxLength={2000}
          rows={3}
          placeholder="e.g. Fires on scaffold planks; catches real bare hands at ~0.7"
          onChange={(e) => setBody(e.target.value)}
          required
        />
      </label>
      <label className="admin-field">
        <span className="admin-field__label">Source (optional)</span>
        <input
          className="admin-field__input"
          value={source}
          maxLength={500}
          placeholder="Where this comes from: an eval folder, a violation, a site visit"
          onChange={(e) => setSource(e.target.value)}
        />
      </label>
      <label className="model-notes__checkbox">
        <input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} />
        Internal: show on this page only, not in the camera picker
      </label>
      {error && (
        <p className="admin-login__error" role="alert">
          {error}
        </p>
      )}
      <div className="draft-edit__actions">
        <button type="submit" className="admin-button" disabled={saving || !body.trim()}>
          {saving ? 'Saving…' : 'Save note'}
        </button>
        <button type="button" className="admin-button admin-button--secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Notes section
// ---------------------------------------------------------------------------

export function ModelNotesSection({ model }: { model: StoreModelDetail }) {
  const queryClient = useQueryClient();
  const notes = useQuery({ queryKey: notesKey(model.id), queryFn: () => listModelNotes(model.id) });
  const projects = useQuery({ queryKey: ['admin', 'projects', 'list'], queryFn: listProjects });
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: notesKey(model.id) });
    queryClient.invalidateQueries({ queryKey: RECOMMENDATIONS_KEY });
    queryClient.invalidateQueries({ queryKey: ['models', 'status'] });
  };

  const create = useMutation({
    mutationFn: (note: ModelNoteInput) => createModelNote(model.id, note),
    onSuccess: () => {
      setAdding(false);
      refresh();
    },
  });
  const update = useMutation({
    mutationFn: ({ id, note }: { id: string; note: ModelNoteInput }) => updateModelNote(id, note),
    onSuccess: () => {
      setEditingId(null);
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteModelNote(id),
    onSettled: refresh,
  });

  const projectList = (projects.data?.items ?? []).map((p) => ({ id: p.id, name: p.name }));
  const confirmDelete = (note: ModelNote) => {
    if (window.confirm(`Delete the note from ${formatObservedOn(note.observed_on)}?`)) remove.mutate(note.id);
  };

  return (
    <section className="admin-card model-notes">
      <div className="model-notes__header">
        <h2 className="admin-card__title">Notes</h2>
        {!adding && (
          <button type="button" className="admin-button admin-button--secondary" onClick={() => setAdding(true)}>
            Add note
          </button>
        )}
      </div>
      <p className="admin-muted model-notes__intro">
        What this model does on site. The newest note not marked internal is shown under the model in
        the camera picker.
      </p>

      {adding && (
        <NoteForm
          projects={projectList}
          saving={create.isPending}
          error={create.isError ? errorText(create.error, 'Could not save the note') : null}
          onSave={(note) => create.mutate(note)}
          onCancel={() => setAdding(false)}
        />
      )}

      {remove.isError && (
        <p className="admin-login__error" role="alert">
          {errorText(remove.error, 'Could not delete the note')}
        </p>
      )}

      {notes.isPending ? (
        <p className="admin-muted">Loading…</p>
      ) : notes.isError ? (
        <p className="admin-login__error" role="alert">Could not load the notes.</p>
      ) : notes.data.length === 0 ? (
        <p className="admin-muted">No notes yet.</p>
      ) : (
        <ul className="model-notes__list">
          {notes.data.map((note) =>
            editingId === note.id ? (
              <li key={note.id} className="model-notes__item">
                <NoteForm
                  initial={note}
                  projects={projectList}
                  saving={update.isPending}
                  error={update.isError ? errorText(update.error, 'Could not save the note') : null}
                  onSave={(changes) => update.mutate({ id: note.id, note: changes })}
                  onCancel={() => setEditingId(null)}
                />
              </li>
            ) : (
              <li key={note.id} className="model-notes__item">
                <div className="model-notes__meta">
                  <strong>{formatObservedOn(note.observed_on)}</strong>
                  {note.project_name && <span> · {note.project_name}</span>}
                  <span className="admin-muted"> · {note.created_by}</span>
                  {note.internal && <span className="model-notes__tag">Internal</span>}
                  {note.reason_for.length > 0 && (
                    <span className="model-notes__tag model-notes__tag--reason">Recommendation reason</span>
                  )}
                </div>
                <p className="model-notes__body">{note.body}</p>
                {note.source && <p className="admin-muted model-notes__source">Source: {note.source}</p>}
                <div className="model-notes__actions">
                  <button type="button" className="admin-button admin-button--link" onClick={() => setEditingId(note.id)}>
                    Edit
                  </button>
                  <button
                    type="button"
                    className="admin-button admin-button--link"
                    onClick={() => confirmDelete(note)}
                    disabled={remove.isPending || note.reason_for.length > 0}
                    title={
                      note.reason_for.length > 0
                        ? 'The reason for a recommendation: change or clear the recommendation first'
                        : undefined
                    }
                  >
                    Delete
                  </button>
                </div>
              </li>
            )
          )}
        </ul>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Recommendation section
// ---------------------------------------------------------------------------

export function ModelRecommendationSection({ model }: { model: StoreModelDetail }) {
  const queryClient = useQueryClient();
  const recs = useQuery({ queryKey: RECOMMENDATIONS_KEY, queryFn: listRecommendations });
  const notes = useQuery({ queryKey: notesKey(model.id), queryFn: () => listModelNotes(model.id) });
  const [choosing, setChoosing] = useState<string | null>(null);
  const [reasonId, setReasonId] = useState('');

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: RECOMMENDATIONS_KEY });
    queryClient.invalidateQueries({ queryKey: notesKey(model.id) });
    queryClient.invalidateQueries({ queryKey: ['admin', 'model-store'] });
    queryClient.invalidateQueries({ queryKey: ['models', 'status'] });
  };
  const recommend = useMutation({
    mutationFn: ({ type, noteId }: { type: string; noteId: string }) => setRecommendation(type, model.id, noteId),
    onSuccess: () => {
      setChoosing(null);
      setReasonId('');
      refresh();
    },
  });
  const clear = useMutation({ mutationFn: (type: string) => clearRecommendation(type), onSuccess: refresh });

  const types = model.violation_types ?? [];
  const byType = new Map((recs.data ?? []).map((r) => [r.violation_type, r]));
  const error = recommend.error ?? clear.error;

  return (
    <section className="admin-card model-notes">
      <h2 className="admin-card__title">Recommended model</h2>
      {!model.installed ? (
        <p className="admin-muted">Install the model to recommend it.</p>
      ) : types.length === 0 ? (
        <p className="admin-muted">This model raises no violation types.</p>
      ) : (
        <ul className="model-notes__list">
          {types.map((type) => {
            const rec = byType.get(type);
            const label = rec?.label ?? type;
            const mine = rec?.model_pk === model.id;
            return (
              <li key={type} className="model-notes__item">
                <div className="model-notes__meta">
                  <strong>{label}</strong>
                  {mine && <span className="model-notes__tag model-notes__tag--reason">Recommended</span>}
                </div>
                <p className="model-notes__body">
                  {!rec
                    ? 'No model is recommended for this yet.'
                    : mine
                      ? `This model is recommended. Reason (${formatObservedOn(rec.note.observed_on)}): ${rec.note.body}`
                      : `${rec.display_name} is recommended${rec.active ? '' : ' (not installed, so not shown)'}.`}
                </p>
                {choosing === type ? (
                  <div className="model-notes__form">
                    <label className="admin-field">
                      <span className="admin-field__label">Reason: one of this model's notes</span>
                      <select
                        className="admin-field__input"
                        value={reasonId}
                        onChange={(e) => setReasonId(e.target.value)}
                      >
                        <option value="">Choose a note…</option>
                        {(notes.data ?? []).map((n) => (
                          <option key={n.id} value={n.id}>
                            {formatObservedOn(n.observed_on)}: {n.body.slice(0, 90)}
                            {n.body.length > 90 ? '…' : ''}
                          </option>
                        ))}
                      </select>
                    </label>
                    {(notes.data ?? []).length === 0 && (
                      <p className="admin-muted">Add a note explaining why first.</p>
                    )}
                    <div className="draft-edit__actions">
                      <button
                        type="button"
                        className="admin-button"
                        disabled={!reasonId || recommend.isPending}
                        onClick={() => recommend.mutate({ type, noteId: reasonId })}
                      >
                        Recommend
                      </button>
                      <button
                        type="button"
                        className="admin-button admin-button--secondary"
                        onClick={() => setChoosing(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="model-notes__actions">
                    {!mine && (
                      <button
                        type="button"
                        className="admin-button admin-button--link"
                        onClick={() => {
                          setChoosing(type);
                          setReasonId('');
                        }}
                      >
                        {rec ? 'Recommend this model instead' : 'Recommend this model'}
                      </button>
                    )}
                    {mine && (
                      <button
                        type="button"
                        className="admin-button admin-button--link"
                        disabled={clear.isPending}
                        onClick={() => {
                          if (window.confirm(`Stop recommending ${model.display_name} for ${label}?`)) {
                            clear.mutate(type);
                          }
                        }}
                      >
                        Stop recommending
                      </button>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {error && (
        <p className="admin-login__error" role="alert">
          {errorText(error, 'Could not change the recommendation')}
        </p>
      )}
    </section>
  );
}
