/**
 * One model list from two sources.
 *
 * Built-in and uploaded models used to be shown on two different pages,
 * each holding half the truth about an uploaded model: Settings knew its
 * health and camera count but rendered its raw id and never said it was
 * uploaded; Model Management knew its files, size and runtime state but
 * nothing about whether it was actually detecting anything. This merges
 * them.
 *
 * The two sources:
 *
 *   GET /api/v1/models/status            open; built-in + store models,
 *                                        store ones marked source:'store'
 *   GET /api/v1/admin/model-store/models admin-only; the upload records
 *
 * **Union, never an inner join.** A row missing from either side is a real
 * state an operator needs to see, not a row to drop:
 *
 *   in both                        -> Installed, with full detail
 *   upload record only             -> NOT INSTALLED (uploaded, never
 *                                     installed into enabled/, so the
 *                                     runtime has never seen it)
 *   /models/status only, source=store -> INSTALLED OUTSIDE MANAGEMENT
 *                                     (someone ran install_enabled.py by
 *                                     hand; it is running, but there is no
 *                                     upload record to manage it from)
 *   store runtime unreachable      -> RUNTIME UNREACHABLE on every
 *                                     uploaded row; we cannot know their
 *                                     real state, and saying "not
 *                                     installed" would be a guess
 *
 * Signed out, only the first source is available, so upload-only rows are
 * invisible and the rest render without their manage affordances. That is
 * a smaller list, never a wrong one.
 */

import type { ModelStatusInfo, StoreRuntimeStatus } from '../../state/api/types';
import type { StoreModelSummary } from '../admin/adminApi';

/** Where a row's information came from, and what can be done with it. */
export type ModelOrigin = 'builtin' | 'uploaded';

export type UploadedState =
  /** Upload record + the runtime reports it: the normal healthy case. */
  | 'installed'
  /** Uploaded but never installed into enabled/. Needs the CLI step. */
  | 'not_installed'
  /** Running, but with no upload record to manage it from. */
  | 'installed_outside_management'
  /** Store runtime did not answer; its real state is unknown. */
  | 'runtime_unreachable';

export interface MergedModel {
  /** Stable key for React and for lookups. */
  key: string;
  model_id: string;
  origin: ModelOrigin;
  /** Best available name: the upload record's, then the status entry's,
   *  then a humanized id. Never the raw slug when something better exists. */
  displayName: string;

  /** From /models/status. Absent for an upload that is not installed. */
  status?: ModelStatusInfo;

  /** From the admin API. Absent when signed out, or when installed by CLI. */
  store?: StoreModelSummary;

  /** Only meaningful when origin === 'uploaded'. */
  uploadedState?: UploadedState;
}

/** Title-case a model id, as the old Settings list did. Last resort only. */
function humanizeId(modelId: string): string {
  return modelId
    .split('_')
    .map((part) => (part ? part.charAt(0).toUpperCase() + part.slice(1) : part))
    .join(' ');
}

function nameFor(
  modelId: string,
  store?: StoreModelSummary,
  status?: ModelStatusInfo
): string {
  // The upload record's display_name is what an admin typed, so it wins.
  // The status entry's display_name comes from the installed manifest,
  // which is the same string for a model installed through the UI but can
  // lag behind a rename.
  return store?.display_name || status?.display_name || humanizeId(modelId);
}

export interface MergeInput {
  /** `models` from GET /models/status. Empty while loading or on error. */
  statusModels: ModelStatusInfo[];
  /** `store_runtime` from the same response; undefined = not configured. */
  storeRuntime?: StoreRuntimeStatus;
  /** Admin model-store rows. Undefined when signed out or not yet loaded. */
  storeModels?: StoreModelSummary[];
}

export interface MergeResult {
  builtIn: MergedModel[];
  uploaded: MergedModel[];
  /** True when a store runtime is configured but did not answer. */
  runtimeUnreachable: boolean;
  /** True when no store runtime is configured in this deployment at all. */
  storeRuntimeConfigured: boolean;
}

export function mergeModels({
  statusModels,
  storeRuntime,
  storeModels,
}: MergeInput): MergeResult {
  const storeRuntimeConfigured = storeRuntime !== undefined;
  const runtimeUnreachable = storeRuntime !== undefined && !storeRuntime.reachable;

  const builtIn: MergedModel[] = [];
  const uploadedByModelId = new Map<string, MergedModel>();

  // Pass 1: everything the runtime reports.
  for (const status of statusModels) {
    if (status.source === 'store') {
      uploadedByModelId.set(status.model_id, {
        key: `status:${status.model_id}`,
        model_id: status.model_id,
        origin: 'uploaded',
        displayName: nameFor(status.model_id, undefined, status),
        status,
      });
    } else {
      builtIn.push({
        key: `builtin:${status.model_id}`,
        model_id: status.model_id,
        origin: 'builtin',
        displayName: nameFor(status.model_id, undefined, status),
        status,
      });
    }
  }

  // Pass 2: fold in the upload records, adding rows the runtime never
  // mentioned. Only possible when signed in.
  if (storeModels) {
    for (const store of storeModels) {
      const existing = uploadedByModelId.get(store.model_id);
      if (existing) {
        existing.store = store;
        existing.key = `store:${store.id}`;
        existing.displayName = nameFor(store.model_id, store, existing.status);
      } else {
        uploadedByModelId.set(store.model_id, {
          key: `store:${store.id}`,
          model_id: store.model_id,
          origin: 'uploaded',
          displayName: nameFor(store.model_id, store, undefined),
          store,
        });
      }
    }
  }

  // Pass 3: classify every uploaded row. `storeModels !== undefined` is
  // what makes "no upload row" a fact rather than an absence of evidence —
  // see classifyUploaded.
  const adminListAvailable = storeModels !== undefined;
  const uploaded = [...uploadedByModelId.values()].map((model) => ({
    ...model,
    uploadedState: classifyUploaded(model, runtimeUnreachable, adminListAvailable),
  }));

  const byName = (a: MergedModel, b: MergedModel) =>
    a.displayName.localeCompare(b.displayName);

  return {
    builtIn: builtIn.sort(byName),
    uploaded: uploaded.sort(byName),
    runtimeUnreachable,
    storeRuntimeConfigured,
  };
}

function classifyUploaded(
  model: MergedModel,
  runtimeUnreachable: boolean,
  adminListAvailable: boolean
): UploadedState {
  // An unreachable runtime makes every other verdict a guess: a model we
  // cannot see might be installed and fine. Report the uncertainty.
  //
  // Checked first, and deliberately not for rows that ARE in the status
  // list — if the runtime answered for this model, it is reachable, and a
  // stale unreachable flag should not override direct evidence.
  if (runtimeUnreachable && !model.status) {
    return 'runtime_unreachable';
  }

  if (model.status) {
    if (model.store) return 'installed';

    // Running, with no upload row. Whether that is noteworthy depends
    // entirely on whether we could see the upload rows at all:
    //
    //   signed in  -> the admin list is authoritative. No row means the
    //                 model really was installed outside Model Management,
    //                 which an admin needs to know: it cannot be managed
    //                 or deleted from here.
    //   signed out -> we never fetched the list. "No row" is our own
    //                 blindness, not a fact about the deployment, and
    //                 telling an operator the model is irregular would be
    //                 a claim we have not earned.
    //
    // So signed out this collapses to the neutral "Installed", which is
    // true and is all the open endpoint supports.
    return adminListAvailable ? 'installed_outside_management' : 'installed';
  }

  return 'not_installed';
}

/** Operator-facing label for each state. */
export const UPLOADED_STATE_LABEL: Record<UploadedState, string> = {
  installed: 'Installed',
  not_installed: 'Not installed',
  installed_outside_management: 'Installed outside Model Management',
  runtime_unreachable: 'Runtime unreachable',
};

/** One sentence saying what the state means and what to do about it. */
export const UPLOADED_STATE_HINT: Record<UploadedState, string> = {
  installed: '',
  not_installed:
    'Uploaded but not yet installed into the store runtime, so nothing is ' +
    'running it. Installing is currently an ops step.',
  installed_outside_management:
    'The store runtime is serving this model, but there is no upload record ' +
    'for it here — it was installed directly on the server. Files and size ' +
    'cannot be shown, and it cannot be deleted from this page.',
  runtime_unreachable:
    'The store runtime did not respond, so the real state of this model is ' +
    'unknown. It may still be running.',
};
