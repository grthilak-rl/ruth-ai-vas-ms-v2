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
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
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

  return (
    <div className="export-data-page">
      <div className="export-data-page__header">
        <Link to="/analytics" className="export-data-page__back">
          ← Back to Analytics
        </Link>
        <h1>Export Data</h1>
        <p className="export-data-page__subtitle">
          Configure your export settings and download analytics data.
        </p>
      </div>

      {exportSuccess && (
        <div className="export-data-page__success">
          ✓ Export complete! Your download should begin shortly.
        </div>
      )}

      {exportError && (
        <div className="export-data-page__error">
          ⚠ Export failed: {exportError}
        </div>
      )}

      <div className="export-data-page__section">
        <h2 className="export-data-page__section-title">1. Select Format</h2>
        <div className="export-data-page__formats">
          <button
            type="button"
            className={`export-format-card ${format === 'csv' ? 'export-format-card--selected' : ''}`}
            onClick={() => setFormat('csv')}
          >
            <div className="export-format-card__icon">📄</div>
            <div className="export-format-card__title">CSV</div>
            <div className="export-format-card__description">
              Raw data for analysis
            </div>
          </button>
          <button
            type="button"
            className={`export-format-card ${format === 'xlsx' ? 'export-format-card--selected' : ''}`}
            onClick={() => setFormat('xlsx')}
          >
            <div className="export-format-card__icon">📊</div>
            <div className="export-format-card__title">XLSX</div>
            <div className="export-format-card__description">
              Formatted Excel with charts
            </div>
          </button>
          <button
            type="button"
            className={`export-format-card ${format === 'pdf' ? 'export-format-card--selected' : ''}`}
            onClick={() => setFormat('pdf')}
          >
            <div className="export-format-card__icon">📋</div>
            <div className="export-format-card__title">PDF</div>
            <div className="export-format-card__description">
              Presentation-ready report
            </div>
          </button>
        </div>
      </div>

      <div className="export-data-page__section">
        <h2 className="export-data-page__section-title">2. Select Time Range</h2>
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

      <div className="export-data-page__section">
        <h2 className="export-data-page__section-title">3. Select Data Scope</h2>
        <div className="export-data-page__scope">
          <label className="export-data-page__checkbox">
            <input
              type="radio"
              checked={scopeAll}
              onChange={() => setScopeAll(true)}
              disabled={isExporting}
            />
            All violations
          </label>
          <label className="export-data-page__checkbox">
            <input
              type="radio"
              checked={!scopeAll}
              onChange={() => setScopeAll(false)}
              disabled={isExporting}
            />
            Filtered (specific cameras, types, or statuses)
          </label>
          {!scopeAll && (
            <div className="export-data-page__filters-note">
              Note: Filter options will be added in a future update
            </div>
          )}
        </div>
      </div>

      {format === 'csv' && (
        <div className="export-data-page__section">
          <h2 className="export-data-page__section-title">4. CSV Options</h2>
          <div className="export-data-page__options">
            <label className="export-data-page__checkbox">
              <input
                type="checkbox"
                checked={includeHeaders}
                onChange={(e) => setIncludeHeaders(e.target.checked)}
                disabled={isExporting}
              />
              Include headers
            </label>
            <label className="export-data-page__checkbox">
              <input
                type="checkbox"
                checked={includeTimestamps}
                onChange={(e) => setIncludeTimestamps(e.target.checked)}
                disabled={isExporting}
              />
              Include timestamps (ISO 8601)
            </label>
            <label className="export-data-page__checkbox">
              <input
                type="checkbox"
                checked={includeRawConfidence}
                onChange={(e) => setIncludeRawConfidence(e.target.checked)}
                disabled={isExporting}
              />
              Include raw confidence scores
            </label>
            <label className="export-data-page__checkbox">
              <input
                type="checkbox"
                checked={includeEvidenceUrls}
                onChange={(e) => setIncludeEvidenceUrls(e.target.checked)}
                disabled={isExporting}
              />
              Include evidence URLs
            </label>
            <label className="export-data-page__checkbox">
              <input
                type="checkbox"
                checked={includeBoundingBoxes}
                onChange={(e) => setIncludeBoundingBoxes(e.target.checked)}
                disabled={isExporting}
              />
              Include bounding box coordinates
            </label>
          </div>
        </div>
      )}

      <div className="export-data-page__actions">
        <button
          type="button"
          className="export-data-page__cancel"
          onClick={() => window.history.back()}
          disabled={isExporting}
        >
          Cancel
        </button>
        <button
          type="button"
          className="export-data-page__generate"
          onClick={handleGenerate}
          disabled={isExporting}
        >
          {isExporting ? 'Generating...' : 'Generate Export'}
        </button>
      </div>
    </div>
  );
}
