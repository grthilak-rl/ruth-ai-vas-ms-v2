/**
 * Polling Intervals (F6-Compliant)
 *
 * Per F6 §11.1 Polling Intervals:
 * - /health: 30 seconds
 * - /models/status: 30 seconds
 * - /violations (list): 10 seconds
 * - /violations/{id}: On-demand only (no polling)
 * - /analytics/summary: 60 seconds
 * - /devices: 60 seconds
 */

export const POLLING_INTERVALS = {
  /**
   * Health endpoint polling interval
   * F6 §11.1: 30 seconds - Balance freshness with overhead
   */
  HEALTH: 30 * 1000,

  /**
   * Violations list polling interval
   * F6 §11.1: 10 seconds - Alert timeliness
   */
  VIOLATIONS: 10 * 1000,

  /**
   * Model status polling interval
   * F6 §11.1: 30 seconds - Same as health
   */
  MODELS_STATUS: 30 * 1000,

  /**
   * Devices list polling interval
   * F6 §11.1: 60 seconds - Camera status changes rarely
   */
  DEVICES: 60 * 1000,

  /**
   * Analytics summary polling interval
   * F6 §11.1: 60 seconds - Analytics can be stale
   */
  ANALYTICS: 60 * 1000,

  /**
   * Hardware monitoring polling interval
   * 5 seconds - Real-time resource monitoring for dashboard
   */
  HARDWARE: 5 * 1000,
} as const;

/**
 * Staleness thresholds (F6 §6.3)
 */
export const STALENESS_THRESHOLDS = {
  /**
   * Data age < 60 seconds: Display normally
   */
  FRESH: 60 * 1000,

  /**
   * Data age 60-300 seconds: Display with "Last updated: X ago"
   */
  STALE: 300 * 1000,

  /**
   * Data age > 300 seconds: Display with "Data may be outdated" warning
   */
  VERY_STALE: 300 * 1000,
} as const;
