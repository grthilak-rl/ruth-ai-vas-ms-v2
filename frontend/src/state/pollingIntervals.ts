/**
 * Polling Intervals
 *
 * Tuned for backend load (perf/polling-and-bulk-fetch). The base F6 §11.1
 * intervals over-poll for slow-changing data and over-poll the navbar
 * alerts badge in particular; the values below relax the slow paths
 * while keeping alert-list freshness at 10s where it matters.
 */

export const POLLING_INTERVALS = {
  /**
   * Health endpoint polling interval.
   * 60s — component states change on the order of minutes (containers,
   * VAS, runtime). 30s was over-polling the global health composite.
   */
  HEALTH: 60 * 1000,

  /**
   * Violations list polling interval (full alert list page).
   * 10s — alert timeliness on the page operators are actively reading.
   * The navbar badge uses ALERTS_BADGE instead.
   */
  VIOLATIONS: 10 * 1000,

  /**
   * Navbar alerts badge polling interval.
   * 30s — "are there unread alerts" only needs minute-ish freshness.
   * Avoids 6 requests/min on every open tab regardless of page.
   */
  ALERTS_BADGE: 30 * 1000,

  /**
   * Model status polling interval.
   * 60s — once models are loaded by the runtime they stay loaded.
   */
  MODELS_STATUS: 60 * 1000,

  /**
   * Devices list polling interval.
   * 120s — this endpoint composes Ruth-DB + VAS state per camera and
   * is by far the heaviest. Mutations (start/stop inference) invalidate
   * the query, so the poll only needs to catch out-of-band changes.
   */
  DEVICES: 120 * 1000,

  /**
   * Analytics summary polling interval.
   * 60s — analytics page bespoke setInterval still uses this cadence
   * (the useAnalyticsQuery hook itself is unused).
   */
  ANALYTICS: 60 * 1000,

  /**
   * Hardware monitoring polling interval.
   * 10s — live dashboard feel without burning 12 req/min just to keep
   * one card current.
   */
  HARDWARE: 10 * 1000,
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
