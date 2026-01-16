# Analytics Backend Deployment Checklist

## Pre-Deployment Steps

### 1. Install Dependencies
```bash
cd ruth-ai-backend
pip install -r requirements.txt
# Or if using pyproject.toml:
pip install -e .
```

This will install the new dependencies:
- `openpyxl>=3.1.0,<4.0.0`
- `reportlab>=4.0.0,<5.0.0`

### 2. Run Syntax Checks
```bash
python3 -m py_compile app/api/v1/analytics.py
python3 -m py_compile app/schemas/analytics.py
python3 -m py_compile app/services/export_service.py
```

All should complete without errors.

### 3. Database Verification
Ensure the following tables and indexes exist:
- `violations` table with indexes on:
  - `timestamp`
  - `device_id`
  - `type`
  - `status`
  - Composite: `(status, timestamp)`
  - Composite: `(device_id, status, timestamp)`
- `devices` table
- `stream_sessions` table

### 4. Run Backend Tests
```bash
cd ruth-ai-backend
pytest tests/
```

### 5. Manual API Testing

#### Test GET /api/v1/analytics/summary
```bash
curl -X GET "http://localhost:8000/api/v1/analytics/summary?from=2026-01-15T00:00:00Z&to=2026-01-16T00:00:00Z&granularity=hour" \
  -H "Authorization: Bearer <token>"
```

Expected: 200 OK with full analytics summary including time_series, by_camera, by_type, by_status

#### Test GET /api/v1/analytics/violations/trends
```bash
curl -X GET "http://localhost:8000/api/v1/analytics/violations/trends?from=2026-01-15T00:00:00Z&to=2026-01-16T00:00:00Z&granularity=hour" \
  -H "Authorization: Bearer <token>"
```

Expected: 200 OK with trend buckets containing by_type and by_status

#### Test GET /api/v1/analytics/devices/status
```bash
curl -X GET "http://localhost:8000/api/v1/analytics/devices/status?from=2026-01-15T00:00:00Z&to=2026-01-16T00:00:00Z" \
  -H "Authorization: Bearer <token>"
```

Expected: 200 OK with per-device analytics and summary

#### Test POST /api/v1/analytics/export (CSV)
```bash
curl -X POST "http://localhost:8000/api/v1/analytics/export" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "format": "csv",
    "time_range": {
      "from": "2026-01-15T00:00:00Z",
      "to": "2026-01-16T00:00:00Z"
    },
    "scope": {
      "all": true
    },
    "options": {
      "include_headers": true,
      "include_timestamps": true
    }
  }' --output test-export.csv
```

Expected: 200 OK with CSV file download

#### Test POST /api/v1/analytics/export (XLSX)
```bash
curl -X POST "http://localhost:8000/api/v1/analytics/export" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "format": "xlsx",
    "time_range": {
      "from": "2026-01-15T00:00:00Z",
      "to": "2026-01-16T00:00:00Z"
    },
    "scope": {
      "all": true
    },
    "options": {}
  }' --output test-export.xlsx
```

Expected: 200 OK with XLSX file download

#### Test POST /api/v1/analytics/export (PDF)
```bash
curl -X POST "http://localhost:8000/api/v1/analytics/export" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "format": "pdf",
    "time_range": {
      "from": "2026-01-15T00:00:00Z",
      "to": "2026-01-16T00:00:00Z"
    },
    "scope": {
      "all": true
    },
    "options": {}
  }' --output test-export.pdf
```

Expected: 200 OK with PDF file download

### 6. Verify Export Files
- Open CSV in a text editor or spreadsheet
- Open XLSX in Excel/LibreOffice and verify Summary + Violations sheets
- Open PDF in a PDF viewer and verify title page, summary, and table

## Post-Deployment Verification

### 1. Monitor Logs
```bash
tail -f ruth-ai-backend.log | grep -i analytics
```

Look for:
- "Analytics summary requested"
- "Violation trends requested"
- "Device status analytics requested"
- "Export requested"
- "Export generated"

### 2. Check Performance
Monitor query execution times:
- `/analytics/summary` should complete in < 1s for 24h range
- `/analytics/violations/trends` should complete in < 1s for 24h range with hourly granularity
- `/analytics/devices/status` should complete in < 2s for 24h range
- Export generation should complete in < 5s for < 1000 violations

### 3. Verify API Documentation
Visit `http://localhost:8000/docs` and confirm:
- All 4 analytics endpoints are visible
- Request/response schemas are correct
- Try It Out functionality works

## Rollback Plan

If issues are detected:

1. **Code Rollback**
   ```bash
   git revert <commit-hash>
   ```

2. **Dependency Rollback**
   ```bash
   pip uninstall openpyxl reportlab
   ```

3. **Restart Service**
   ```bash
   systemctl restart ruth-ai-backend
   ```

## Known Limitations

1. **Export Size Limit**: Exports are limited to 90-day time ranges
2. **PDF Pagination**: PDFs show only first 100 violations
3. **Memory Usage**: Large exports (> 10,000 violations) may use significant memory
4. **Evidence URLs**: Export currently doesn't include evidence URLs (requires evidence table query)

## Future Enhancements

1. Async export generation for large datasets
2. Export caching
3. Evidence URLs in exports
4. Custom export templates
5. Scheduled/automated exports

---

**Deployment Date**: ___________
**Deployed By**: ___________
**Verification Completed**: ☐ Yes ☐ No
**Issues Encountered**: ___________
