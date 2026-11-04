/**
 * Export Data Page
 * F2 Path: /analytics/export
 *
 * Per analytics-design.md §7:
 * - Format selection (CSV, XLSX, PDF)
 * - Time range selector
 * - Data scope filters
 * - Format-specific options
 * - Export generation and download
 *
 * Two kinds of export, chosen at the top:
 * - Customer report: the customer-facing PDF, built as a background job
 *   (CustomerReportPanel). Admin-only.
 * - Raw data: the CSV/XLSX/PDF table exports below, unchanged.
 *
 * Layout: Single viewport design with horizontal format cards
 * and two-column configuration layout.
 */

type ExportKind = 'report' | 'raw';

import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { CustomerReportPanel } from '../components/analytics/CustomerReportPanel';
import { TimeRangeSelector } from '../components/analytics/TimeRangeSelector';
import {
  exportAnalytics,
  downloadBlob,
  generateExportFilename,
  calculateTimeRange,
  validateTimeRange,
} from '../services/analyticsApi';
import type {
  ExportFormat,
  ExportRequest,
  TimeRangePreset,
} from '../types/analytics';
import './ExportDataPage.css';

export function ExportDataPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const kind: ExportKind = searchParams.get('type') === 'raw' ? 'raw' : 'report';
  const setKind = (next: ExportKind) =>
    setSearchParams(next === 'raw' ? { type: 'raw' } : {}, { replace: true });
  const [format, setFormat] = useState<ExportFormat>('csv');
  const [preset, setPreset] = useState<TimeRangePreset>('24h');
  const [customFrom, setCustomFrom] = useState<Date | undefined>();
  const [customTo, setCustomTo] = useState<Date | undefined>();
  const [scopeAll, setScopeAll] = useState(true);
  const [includeHeaders, setIncludeHeaders] = useState(true);
  const [includeTimestamps, setIncludeTimestamps] = useState(true);
  const [includeRawConfidence, setIncludeRawConfidence] = useState(false);
  const [includeEvidenceUrls, setIncludeEvidenceUrls] = useState(false);
  const [includeBoundingBoxes, setIncludeBoundingBoxes] = useState(false);

  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportSuccess, setExportSuccess] = useState(false);

  const handleGenerate = async () => {
    setIsExporting(true);
    setExportError(null);
    setExportSuccess(false);

    try {
      // Calculate time range
      let from: string;
      let to: string;

      if (preset === 'custom' && customFrom && customTo) {
        // Validate custom range
        const validationError = validateTimeRange(customFrom, customTo);
        if (validationError) {
          setExportError(validationError);
          setIsExporting(false);
          return;
        }
        from = customFrom.toISOString();
        to = customTo.toISOString();
      } else if (preset !== 'custom') {
        const range = calculateTimeRange(preset);
        from = range.from;
        to = range.to;
      } else {
        setExportError('Please select a time range');
        setIsExporting(false);
        return;
      }

      // Build export request
      const request: ExportRequest = {
        format,
        time_range: { from, to },
        scope: {
          all: scopeAll,
          camera_ids: [],
          violation_types: [],
          statuses: [],
        },
        options: {
          include_headers: includeHeaders,
          include_timestamps: includeTimestamps,
          include_raw_confidence: includeRawConfidence,
          include_evidence_urls: includeEvidenceUrls,
          include_bounding_boxes: includeBoundingBoxes,
        },
      };

      // Generate export
      const blob = await exportAnalytics(request);
      const filename = generateExportFilename(format);

      // Download file
      downloadBlob(blob, filename);
      setExportSuccess(true);
    } catch (error) {
      console.error('Export failed:', error);
      setExportError(
        error instanceof Error ? error.message : 'Export generation failed'
      );
    } finally {
      setIsExporting(false);
    }
  };

  // Get format-specific options label
  const getOptionsLabel = () => {
    switch (format) {
      case 'csv':
        return 'CSV Options';
      case 'xlsx':
        return 'Excel Options';
      case 'pdf':
        return 'PDF Options';
      default:
        return 'Options';
    }
  };

  return (
    <div className="export-page">
      {/* Header */}
      <Link to="/analytics" className="export-page__back">
        ← Back to Analytics
      </Link>

      <div className="export-page__header">
        <h1 className="export-page__title">Export Data</h1>
        <p className="export-page__subtitle">
          A customer-ready report, or the raw data for your own analysis.
        </p>
      </div>

      <div className="export-kind" role="tablist" aria-label="What to export">
        <button
          type="button"
          role="tab"
          aria-selected={kind === 'report'}
          className={`export-kind__option ${kind === 'report' ? 'export-kind__option--selected' : ''}`}
          onClick={() => setKind('report')}
          disabled={isExporting}
        >
          <span className="export-kind__name">Customer report (PDF)</span>
          <span className="export-kind__description">
            Summary, trends, areas, evidence and recommendations, ready to send
          </span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={kind === 'raw'}
          className={`export-kind__option ${kind === 'raw' ? 'export-kind__option--selected' : ''}`}
          onClick={() => setKind('raw')}
        >
          <span className="export-kind__name">Raw data</span>
          <span className="export-kind__description">
            Every detection as CSV, Excel or a PDF table
          </span>
        </button>
      </div>

      {kind === 'report' && <CustomerReportPanel />}

      {kind === 'raw' && (
      <>

      {/* Status Messages */}
      {exportSuccess && (
        <div className="export-page__message export-page__message--success">
          ✓ Export complete! Your download should begin shortly.
        </div>
      )}

      {exportError && (
        <div className="export-page__message export-page__message--error">
          ⚠ Export failed: {exportError}
        </div>
      )}

      {/* Format Selection - Horizontal Cards */}
      <div className="export-format-section">
        <h2 className="export-format-section__title">Format</h2>
        <div className="export-format-cards">
          <button
            type="button"
            className={`export-format-card ${format === 'csv' ? 'export-format-card--selected' : ''}`}
            onClick={() => setFormat('csv')}
            disabled={isExporting}
          >
            <span className="export-format-card__icon">📄</span>
            <span className="export-format-card__name">CSV</span>
            <span className="export-format-card__description">
              Raw data for analysis
            </span>
          </button>

          <button
            type="button"
            className={`export-format-card ${format === 'xlsx' ? 'export-format-card--selected' : ''}`}
            onClick={() => setFormat('xlsx')}
            disabled={isExporting}
          >
            <span className="export-format-card__icon">📊</span>
            <span className="export-format-card__name">XLSX</span>
            <span className="export-format-card__description">
              Formatted Excel with charts
            </span>
          </button>

          <button
            type="button"
            className={`export-format-card ${format === 'pdf' ? 'export-format-card--selected' : ''}`}
            onClick={() => setFormat('pdf')}
            disabled={isExporting}
          >
            <span className="export-format-card__icon">📕</span>
            <span className="export-format-card__name">PDF</span>
            <span className="export-format-card__description">
              Data table as PDF
            </span>
          </button>
        </div>
      </div>

      {/* Two-Column Layout: Configuration + Options */}
      <div className="export-config-row">
        {/* Left Column: Configuration */}
        <div className="export-config-card">
          <h2 className="export-config-card__title">Configuration</h2>

          <div className="export-config-card__section">
            <label className="export-config-card__label">Time Range</label>
            <TimeRangeSelector
              selectedPreset={preset}
              customFrom={customFrom}
              customTo={customTo}
              onPresetChange={setPreset}
              onCustomRangeApply={(from, to) => {
                setCustomFrom(from);
                setCustomTo(to);
                setPreset('custom');
              }}
              disabled={isExporting}
            />
          </div>

          <div className="export-config-card__section">
            <label className="export-config-card__label">Data Scope</label>
            <div className="export-scope-options">
              <label className="export-radio">
                <input
                  type="radio"
                  name="scope"
                  checked={scopeAll}
                  onChange={() => setScopeAll(true)}
                  disabled={isExporting}
                />
                <span className="export-radio__text">All violations</span>
              </label>
              <label className="export-radio">
                <input
                  type="radio"
                  name="scope"
                  checked={!scopeAll}
                  onChange={() => setScopeAll(false)}
                  disabled={isExporting}
                />
                <span className="export-radio__text">
                  Filtered (specific cameras, types, or statuses)
                </span>
              </label>
              {!scopeAll && (
                <div className="export-config-card__note">
                  Note: Filter options will be added in a future update
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right Column: Options */}
        <div className="export-config-card">
          <h2 className="export-config-card__title">{getOptionsLabel()}</h2>

          <div className="export-options-list">
            <label className="export-checkbox">
              <input
                type="checkbox"
                checked={includeHeaders}
                onChange={(e) => setIncludeHeaders(e.target.checked)}
                disabled={isExporting}
              />
              <span className="export-checkbox__text">Include headers</span>
            </label>

            <label className="export-checkbox">
              <input
                type="checkbox"
                checked={includeTimestamps}
                onChange={(e) => setIncludeTimestamps(e.target.checked)}
                disabled={isExporting}
              />
              <span className="export-checkbox__text">
                Include timestamps (ISO 8601)
              </span>
            </label>

            <label className="export-checkbox">
              <input
                type="checkbox"
                checked={includeRawConfidence}
                onChange={(e) => setIncludeRawConfidence(e.target.checked)}
                disabled={isExporting}
              />
              <span className="export-checkbox__text">
                Include raw confidence scores
              </span>
            </label>

            <label className="export-checkbox">
              <input
                type="checkbox"
                checked={includeEvidenceUrls}
                onChange={(e) => setIncludeEvidenceUrls(e.target.checked)}
                disabled={isExporting}
              />
              <span className="export-checkbox__text">
                Include evidence URLs
              </span>
            </label>

            <label className="export-checkbox">
              <input
                type="checkbox"
                checked={includeBoundingBoxes}
                onChange={(e) => setIncludeBoundingBoxes(e.target.checked)}
                disabled={isExporting}
              />
              <span className="export-checkbox__text">
                Include bounding box coordinates
              </span>
            </label>
          </div>
        </div>
      </div>

      {/* Footer Actions */}
      <div className="export-page__actions">
        <button
          type="button"
          className="export-page__btn export-page__btn--secondary"
          onClick={() => window.history.back()}
          disabled={isExporting}
        >
          Cancel
        </button>
        <button
          type="button"
          className="export-page__btn export-page__btn--primary"
          onClick={handleGenerate}
          disabled={isExporting}
        >
          {isExporting ? 'Generating...' : 'Generate Export'}
        </button>
      </div>
      </>
      )}
    </div>
  );
}
