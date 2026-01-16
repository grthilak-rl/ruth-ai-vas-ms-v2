# Ruth AI Analytics API Test Report

**Date:** 2026-01-16
**Backend:** ruth-ai-backend
**Base URL:** http://localhost:8090
**Tester:** API Tester Agent

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Total Endpoints Tested | 4 |
| Tests Passed | 4 |
| Tests Failed | 0 |
| Overall Status | **PASS** |

All analytics endpoints are functioning correctly. Export functionality successfully generates CSV, XLSX, and PDF files.

---

## Environment Setup

### Dependencies Verified
| Package | Status | Purpose |
|---------|--------|---------|
| openpyxl | Installed | Excel export |
| reportlab | Installed | PDF export |
| sqlalchemy | Installed | Database ORM |
| fastapi | Installed | API framework |

### Database Configuration
- **Connection:** postgresql+asyncpg://ruth:ruth_dev_password@ruth-ai-vas-postgres:5432/ruth_ai
- **Container:** ruth-ai-vas-postgres (Docker)
- **Network:** ruth-ai-vas-internal

---

## Endpoint Test Results

### 1. GET /api/v1/analytics/summary

| # | Scenario | Input | Expected | Actual | Status |
|---|----------|-------|----------|--------|--------|
| 1 | Default params | No params | 200 + summary data | 200 + complete summary | PASS |
| 2 | With time range | from_time, to_time | 200 + filtered data | 200 + filtered data | PASS |

**Sample Response:**
```json
{
  "time_range": {"from": "2026-01-15T06:52:58Z", "to": "2026-01-16T06:52:58Z"},
  "totals": {
    "violations_total": 1,
    "violations_open": 0,
    "violations_reviewed": 1,
    "cameras_active": 1,
    "cameras_total": 2
  },
  "by_camera": [...],
  "by_type": [{"type": "fall_detected", "count": 1, "percentage": 100.0}],
  "by_status": [{"status": "reviewed", "count": 1, "percentage": 100.0}],
  "time_series": [...]
}
```

**Notes:** Returns comprehensive analytics summary with breakdowns by camera, type, status, and time series.

---

### 2. GET /api/v1/analytics/violations/trends

| # | Scenario | Input | Expected | Actual | Status |
|---|----------|-------|----------|--------|--------|
| 1 | Day granularity | granularity=day | 200 + daily buckets | 200 + daily buckets | PASS |
| 2 | Hour granularity | granularity=hour | 200 + hourly buckets | 200 + hourly buckets | PASS |

**Sample Response:**
```json
{
  "time_range": {"from": "2026-01-15T06:53:05Z", "to": "2026-01-16T06:53:05Z"},
  "granularity": "day",
  "data": [
    {
      "bucket": "2026-01-15T00:00:00Z",
      "total": 1,
      "by_type": {"fall_detected": 1},
      "by_status": {"reviewed": 1}
    }
  ]
}
```

**Notes:** Returns time-bucketed violation trends with both type and status breakdowns per bucket.

---

### 3. GET /api/v1/analytics/devices/status

| # | Scenario | Input | Expected | Actual | Status |
|---|----------|-------|----------|--------|--------|
| 1 | Default params | No params | 200 + device list | 200 + device analytics | PASS |
| 2 | With time range | from_time, to_time | 200 + filtered | 200 + filtered | PASS |

**Sample Response:**
```json
{
  "time_range": {"from": "2026-01-15T06:53:12Z", "to": "2026-01-16T06:53:12Z"},
  "devices": [
    {
      "camera_id": "e7818a99-2d75-4215-8506-6d309fa4551b",
      "camera_name": "Auto-created Device e3f1b688",
      "violations_total": 1,
      "violations_by_status": {"reviewed": 1},
      "violations_by_type": {"fall_detected": 1},
      "avg_confidence": 0.92,
      "last_violation_at": "2026-01-15T10:25:00Z"
    }
  ],
  "summary": {
    "total_violations": 1,
    "total_cameras": 2,
    "active_cameras": 1
  }
}
```

**Notes:** Returns per-device analytics with average confidence scores and last violation timestamps.

---

### 4. POST /api/v1/analytics/export

| # | Scenario | Input | Expected | Actual | Status |
|---|----------|-------|----------|--------|--------|
| 1 | CSV format | format=csv | 200 + CSV file | 200 + valid CSV | PASS |
| 2 | XLSX format | format=xlsx | 200 + XLSX file | 200 + Excel 2007+ | PASS |
| 3 | PDF format | format=pdf | 200 + PDF file | 200 + 2-page PDF | PASS |
| 4 | With raw confidence | options.include_raw_confidence=true | CSV with decimal | 0.920 in column | PASS |
| 5 | Time range > 90 days | Large range | 400 error | 400 INVALID_EXPORT_CONFIG | PASS |

**CSV Export Sample:**
```csv
id,type,camera_name,status,confidence_category,timestamp,created_at,reviewed_by,reviewed_at,model_id,model_version
18d45a32-7ec9-4e81-b63d-fb65be415d7a,fall_detected,Auto-created Device e3f1b688,reviewed,High,2026-01-15T10:25:00+00:00,2026-01-15T10:27:03.080025+00:00,,2026-01-16T05:24:10.429256+00:00,fall_detection,1.0.0
```

**Request Schema:**
```json
{
  "format": "csv|xlsx|pdf",
  "time_range": {"from": "ISO8601", "to": "ISO8601"},
  "scope": {
    "all": true,
    "camera_ids": [],
    "violation_types": [],
    "statuses": []
  },
  "options": {
    "include_headers": true,
    "include_timestamps": true,
    "include_raw_confidence": false,
    "include_evidence_urls": false,
    "include_bounding_boxes": false
  }
}
```

**Notes:**
- CSV: Plain text with configurable columns
- XLSX: Includes Summary sheet with statistics + Violations sheet with formatted data
- PDF: Professional 2-page report with title, metadata, summary, and data table

---

## Validation Results

### Input Validation
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| Missing time_range | 400 | 400 VALIDATION_ERROR | PASS |
| Time range > 90 days | 400 | 400 INVALID_EXPORT_CONFIG | PASS |
| Invalid format | 422 | 422 Validation Error | PASS |

### Response Schema Validation
| Endpoint | Schema Valid | Notes |
|----------|--------------|-------|
| /analytics/summary | Yes | All required fields present |
| /analytics/violations/trends | Yes | Proper time bucket structure |
| /analytics/devices/status | Yes | Per-device analytics complete |
| /analytics/export | Yes | Proper Content-Type headers |

---

## File Generation Results

| Format | File Size | Content Type | Validation |
|--------|-----------|--------------|------------|
| CSV | 346 bytes | text/csv | Valid UTF-8 |
| XLSX | ~8KB | application/vnd.openxmlformats-officedocument.spreadsheetml.sheet | Microsoft Excel 2007+ |
| PDF | ~2KB | application/pdf | PDF v1.4, 2 pages |

---

## Issues Found

**None** - All endpoints functioning correctly.

---

## Recommendations

1. **Consider pagination** for large datasets on the summary endpoint
2. **Add date range presets** (e.g., "last 7 days", "last 30 days") for convenience
3. **Consider async export** for very large datasets to avoid timeout issues

---

## Test Execution Commands

```bash
# Health check
curl http://localhost:8090/api/v1/health

# Summary
curl "http://localhost:8090/api/v1/analytics/summary?from_time=2026-01-01T00:00:00Z&to_time=2026-01-17T00:00:00Z"

# Trends
curl "http://localhost:8090/api/v1/analytics/violations/trends?from_time=2026-01-01T00:00:00Z&to_time=2026-01-17T00:00:00Z&granularity=day"

# Device status
curl "http://localhost:8090/api/v1/analytics/devices/status?from_time=2026-01-01T00:00:00Z&to_time=2026-01-17T00:00:00Z"

# Export CSV
curl -X POST "http://localhost:8090/api/v1/analytics/export" \
  -H "Content-Type: application/json" \
  -d '{"format": "csv", "time_range": {"from": "2026-01-01T00:00:00Z", "to": "2026-01-17T00:00:00Z"}}' \
  -o export.csv

# Export XLSX
curl -X POST "http://localhost:8090/api/v1/analytics/export" \
  -H "Content-Type: application/json" \
  -d '{"format": "xlsx", "time_range": {"from": "2026-01-01T00:00:00Z", "to": "2026-01-17T00:00:00Z"}}' \
  -o export.xlsx

# Export PDF
curl -X POST "http://localhost:8090/api/v1/analytics/export" \
  -H "Content-Type: application/json" \
  -d '{"format": "pdf", "time_range": {"from": "2026-01-01T00:00:00Z", "to": "2026-01-17T00:00:00Z"}}' \
  -o export.pdf
```

---

**Report Generated:** 2026-01-16T06:55:00Z
**Tester:** Claude API Tester Agent
