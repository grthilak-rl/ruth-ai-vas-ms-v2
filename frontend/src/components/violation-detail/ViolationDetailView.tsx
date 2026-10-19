import { useState, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { DismissReason, Violation } from '../../state/api';
import {
  useAcknowledgeViolation,
  useBulkViolationAction,
  useDismissViolation,
  getConfidenceCategory,
  getConfidenceDisplay,
  useIsSupervisor,
  useIsAdmin,
} from '../../state';
import { EvidenceViewer } from './EvidenceViewer';
import { ViolationMetadata } from './ViolationMetadata';
import { ViolationActions } from './ViolationActions';
import { DismissReasonDialog } from '../alerts/DismissReasonDialog';
import { summarizeBulkResult } from '../alerts/bulkResult';
import { Toast, type ToastType } from '../alerts/Toast';
import { alertsListPath } from '../../utils/alertsListMemory';
import './ViolationDetailView.css';

interface ViolationDetailViewProps {
  violation: Violation;
  onRefetch: () => void;
}

/**
 * Violation Detail View (F3 Flow 2, F4 §6)
 *
 * Deep inspection of a single violation with evidence.
 *
 * Per F3 Flow 2:
 * - Key information displays immediately
 * - Snapshot displays with detection overlay
 * - Video loads on demand (never auto-load)
 * - Actions available even if evidence is missing
 *
 * HARD RULES:
 * - F3 §Explicit Non-Goals: No event IDs, raw timestamps, model versions
 * - F3: No blocking while evidence loads
 * - Evidence missing MUST NOT block actions
 */
export function ViolationDetailView({
  violation,
  onRefetch,
}: ViolationDetailViewProps) {
  const navigate = useNavigate();
  const isSupervisorOrAdmin = useIsSupervisor() || useIsAdmin();

  // Action mutations
  const acknowledgeMutation = useAcknowledgeViolation();
  const dismissMutation = useDismissViolation();
  const bulk = useBulkViolationAction();

  // Action state
  const [pendingAction, setPendingAction] = useState<'acknowledge' | 'dismiss' | 'escalate' | 'resolve' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Dismiss dialog state
  const [isDismissDialogOpen, setIsDismissDialogOpen] = useState(false);

  // Toast state
  const [toast, setToast] = useState<{
    message: string;
    type: ToastType;
    isVisible: boolean;
  }>({ message: '', type: 'success', isVisible: false });

  // Confidence for display
  const confidenceCategory = getConfidenceCategory(violation.confidence);
  const confidenceLabel = getConfidenceDisplay(violation.confidence);

  // Handle acknowledge
  const handleAcknowledge = useCallback(async () => {
    setActionError(null);
    setPendingAction('acknowledge');

    try {
      await acknowledgeMutation.acknowledge(violation.id);
      setToast({
        message: 'Violation marked as reviewed',
        type: 'success',
        isVisible: true,
      });
      onRefetch();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Couldn\'t save. Please try again.';
      setActionError(message);
    } finally {
      setPendingAction(null);
    }
  }, [acknowledgeMutation, violation.id, onRefetch]);

  // Handle dismiss click (opens dialog)
  const handleDismissClick = useCallback(() => {
    setIsDismissDialogOpen(true);
  }, []);

  // Handle dismiss confirm: always with a reason, through the same bulk
  // endpoint as the list, so a false alarm reaches the labelling export.
  const handleDismissConfirm = useCallback(
    async (reason: DismissReason, note: string | undefined) => {
      setActionError(null);
      setPendingAction('dismiss');

      try {
        const result = await bulk({ ids: [violation.id], action: 'dismiss', dismiss_reason: reason, note });
        setIsDismissDialogOpen(false);
        if (result.updated.length === 0) {
          setActionError('This violation was already reviewed or dismissed elsewhere.');
          onRefetch();
          return;
        }
        setToast({
          message: summarizeBulkResult(result, 'dismiss'),
          type: (result.labelling?.failed ?? 0) > 0 ? 'error' : 'success',
          isVisible: true,
        });
        // Back to the list the operator came from
        setTimeout(() => navigate(alertsListPath()), 1500);
      } catch (err) {
        setIsDismissDialogOpen(false);
        const message = err instanceof Error ? err.message : 'Couldn\'t dismiss. Please try again.';
        setActionError(message);
      } finally {
        setPendingAction(null);
      }
    },
    [bulk, violation.id, navigate, onRefetch]
  );

  // Handle dismiss cancel
  const handleDismissCancel = useCallback(() => {
    setIsDismissDialogOpen(false);
  }, []);

  // Handle escalate (placeholder - not fully implemented per API)
  const handleEscalate = useCallback(() => {
    setToast({
      message: 'Escalation sent to supervisor',
      type: 'info',
      isVisible: true,
    });
  }, []);

  // Handle resolve (Supervisor/Admin only)
  const handleResolve = useCallback(async () => {
    setActionError(null);
    setPendingAction('resolve');

    try {
      // Use dismiss mutation with 'resolved' status
      await dismissMutation.mutateAsync({
        id: violation.id,
        update: { status: 'resolved' },
      });
      setToast({
        message: 'Violation resolved',
        type: 'success',
        isVisible: true,
      });
      setTimeout(() => navigate(alertsListPath()), 1500);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Couldn\'t resolve. Please try again.';
      setActionError(message);
    } finally {
      setPendingAction(null);
    }
  }, [dismissMutation, violation.id, navigate]);

  // Handle toast dismiss
  const handleToastDismiss = useCallback(() => {
    setToast((prev) => ({ ...prev, isVisible: false }));
  }, []);

  // Determine available actions based on status
  const canAcknowledge = violation.status === 'open';
  const canDismiss = violation.status === 'open' || violation.status === 'reviewed';
  const canEscalate = violation.status === 'open' || violation.status === 'reviewed';
  const canResolve = isSupervisorOrAdmin && violation.status === 'reviewed';

  return (
    <>
      <div className="violation-detail">
        {/* Back navigation */}
        <nav className="violation-detail__nav">
          <Link to={alertsListPath()} className="violation-detail__back">
            ← Back to Alerts
          </Link>
        </nav>

        {/* Main content */}
        <div className="violation-detail__content">
          {/* Evidence section */}
          <section className="violation-detail__evidence">
            <EvidenceViewer
              evidence={violation.evidence}
              cameraName={violation.camera_name}
              clipTypeSlug={violation.type_detail || violation.type}
              timestamp={violation.timestamp}
              violationId={violation.id}
              boundingBoxes={violation.bounding_boxes}
            />
          </section>

          {/* Metadata sidebar */}
          <aside className="violation-detail__sidebar">
            <ViolationMetadata
              violation={violation}
              confidenceCategory={confidenceCategory}
              confidenceLabel={confidenceLabel}
            />

            {/* Context links */}
            <div className="violation-detail__links">
              <Link
                to={`/cameras/${violation.camera_id}`}
                className="violation-detail__link"
              >
                View Camera
              </Link>
              <Link
                to="/alerts"
                className="violation-detail__link"
              >
                All Violations
              </Link>
            </div>
          </aside>
        </div>

        {/* Error display */}
        {actionError && (
          <div className="violation-detail__error" role="alert">
            {actionError}
          </div>
        )}

        {/* Actions section */}
        <section className="violation-detail__actions">
          <ViolationActions
            canAcknowledge={canAcknowledge}
            canDismiss={canDismiss}
            canEscalate={canEscalate}
            canResolve={canResolve}
            onAcknowledge={handleAcknowledge}
            onDismiss={handleDismissClick}
            onEscalate={handleEscalate}
            onResolve={handleResolve}
            pendingAction={pendingAction}
          />
        </section>
      </div>

      {/* Dismiss with a reason */}
      <DismissReasonDialog
        isOpen={isDismissDialogOpen}
        count={1}
        onConfirm={handleDismissConfirm}
        onCancel={handleDismissCancel}
        isPending={pendingAction === 'dismiss'}
      />

      {/* Toast notifications */}
      <Toast
        message={toast.message}
        type={toast.type}
        isVisible={toast.isVisible}
        onDismiss={handleToastDismiss}
      />
    </>
  );
}
