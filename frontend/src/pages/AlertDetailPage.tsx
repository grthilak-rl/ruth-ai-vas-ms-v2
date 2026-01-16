import { useParams } from 'react-router-dom';
import { useViolationQuery } from '../state';
import {
  ViolationDetailView,
  ViolationDetailSkeleton,
  ViolationNotFound,
} from '../components/violation-detail';

/**
 * Alert/Violation Detail Page (F2 Path: /alerts/:id)
 *
 * Full violation information with evidence and actions.
 *
 * Per F3 Flow 2:
 * - Key information displays immediately
 * - Evidence loads progressively
 * - Actions available even if evidence missing
 *
 * States (F4):
 * - Loading: Skeleton placeholder
 * - Error/Not Found: ViolationNotFound
 * - Success: ViolationDetailView
 */
export function AlertDetailPage() {
  const { id } = useParams<{ id: string }>();

  const {
    data: violation,
    isLoading,
    isError,
    refetch,
  } = useViolationQuery(id ?? '');

  // Loading state
  if (isLoading) {
    return <ViolationDetailSkeleton />;
  }

  // Error or not found state
  if (isError || !violation) {
    return <ViolationNotFound />;
  }

  // Success state
  return (
    <ViolationDetailView
      violation={violation}
      onRefetch={refetch}
    />
  );
}
