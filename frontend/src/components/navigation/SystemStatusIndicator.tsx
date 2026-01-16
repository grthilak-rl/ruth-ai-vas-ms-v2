import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  useHealthQuery,
  deriveGlobalStatus,
  getGlobalStatusDisplay,
  useIsAdmin,
  type GlobalStatus,
} from '../../state';
import { SystemStatusModal } from './SystemStatusModal';
import './SystemStatusIndicator.css';

/**
 * Visual indicator configuration per F4 wireframes
 *
 * | Backend State | Frontend Display | Visual Indicator |
 * |---------------|------------------|------------------|
 * | healthy       | "All Systems OK" | Green dot (●)    |
 * | degraded      | "Degraded"       | Yellow dot (◐)   |
 * | offline       | "Offline"        | Red dot (○)      |
 */
const STATUS_CONFIG: Record<GlobalStatus, { dot: string; className: string }> = {
  healthy: { dot: '●', className: 'system-status--healthy' },
  degraded: { dot: '◐', className: 'system-status--degraded' },
  offline: { dot: '○', className: 'system-status--offline' },
};

/**
 * Global System Status Indicator (F4/F6-aligned)
 *
 * Displays system health status derived ONLY from /api/v1/health.
 *
 * HARD RULES (F6 §4.2):
 * - MUST derive status only from /api/v1/health
 * - MUST NOT infer health from latency, errors, or missing data
 * - Click behavior varies by role (F3 Flow 4)
 *
 * Click Behavior (F4):
 * - Operator/Supervisor: Opens modal with summary
 * - Admin: Deep link to Settings > System Health
 */
export function SystemStatusIndicator() {
  const navigate = useNavigate();
  const isAdmin = useIsAdmin();
  const [isModalOpen, setIsModalOpen] = useState(false);

  // Health query with 30s polling (F6 §11.1)
  const { data, isError } = useHealthQuery();

  // Derive global status per F6 §4.2
  const status = deriveGlobalStatus(data, isError);
  const displayText = getGlobalStatusDisplay(status);
  const config = STATUS_CONFIG[status];

  const handleClick = useCallback(() => {
    if (isAdmin) {
      // Admin: Navigate to system health page (F3 Flow 4)
      navigate('/settings/health');
    } else {
      // Operator/Supervisor: Open status modal
      setIsModalOpen(true);
    }
  }, [isAdmin, navigate]);

  const handleCloseModal = useCallback(() => {
    setIsModalOpen(false);
  }, []);

  return (
    <>
      <button
        type="button"
        className={`system-status ${config.className}`}
        onClick={handleClick}
        aria-label={`System status: ${displayText}. Click for details.`}
      >
        <span className="system-status__dot" aria-hidden="true">
          {config.dot}
        </span>
        <span className="system-status__text">{displayText}</span>
      </button>

      {!isAdmin && (
        <SystemStatusModal
          isOpen={isModalOpen}
          onClose={handleCloseModal}
          status={status}
        />
      )}
    </>
  );
}
