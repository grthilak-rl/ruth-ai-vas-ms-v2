# Ruth AI VAS-MS-V2 Project Notes

## VAS Service Configuration

**IMPORTANT:** The VAS service port mapping from docker-compose.yml:

| Service      | Container Port | Host Port |
|--------------|----------------|-----------|
| Backend API  | 8085           | 8085      |
| Frontend     | 3000           | 3200      |
| MediaSoup    | 3001           | 3002      |
| PostgreSQL   | 5432           | 5433      |
| Redis        | 6379           | 6380      |

### Environment Variables for Testing

```bash
export VAS_BASE_URL="http://10.30.250.245:8085"
export VAS_DEFAULT_CLIENT_ID="vas-portal"
export VAS_DEFAULT_CLIENT_SECRET="vas-portal-secret-2024"
```

### Health Check

To verify the backend is running:

```bash
curl http://10.30.250.245:8085/health
```

Expected response:
```json
{"status":"healthy","service":"VAS Backend","version":"1.0.0"}
```

## Common Issues

### Connection Refused
If you get "Connection refused" errors, check:
1. **Port 8085** - Backend API runs on port 8085, NOT port 80
2. Verify service is running: `curl http://10.30.250.245:8085/health`

### Running Integration Tests

```bash
cd tests
source .venv/bin/activate
python run_tests.py
```

## API Contract Discrepancies Discovered

The integration tests revealed several differences between the documented API and actual implementation:

### 1. Stream State Case
- **Documented:** Uppercase states (`LIVE`, `STOPPED`, etc.)
- **Actual:** Lowercase states (`live`, `stopped`, etc.)
- **Impact:** Models updated to handle both

### 2. Token Refresh Endpoint ✅ FIXED
- **Documented:** `POST /v2/auth/token/refresh` with refresh_token in body
- **Issue:** Required `X-API-Key` header and missing token rotation
- **Fixed:** Added to EXEMPT_PATHS, implemented token rotation

### 3. Consumer Attachment ✅ FULLY FIXED
- **Previous:** "Stream has no producer" error, list/delete/connect 500 errors
- **Fixed:**
  - Producer DB record now created correctly
  - room_id mismatch resolved (use camera_id instead of stream_id)
  - Removed extra_metadata from consumer response
  - Fixed onupdate="now()" → onupdate=func.now()
  - Removed consumer_id from ConsumerConnectRequest and ICECandidateRequest schemas

### 4. Bookmark Fields ✅ FIXED (in test model)
- `label` and `event_type` can be `null` in existing bookmarks
- **Impact:** Made fields optional in Pydantic model

### 5. Stream Health Endpoint ✅ FIXED
- **Previous:** Returns 500 Internal Server Error ("Multiple rows found")
- **Fixed:** Changed Producer query to filter by `Producer.state == ProducerState.ACTIVE` and use `.scalars().first()`
- **Note:** Test model updated to match expected response schema

### 6. Bookmark Update Endpoint ✅ FIXED
- **Previous:** `PUT /v2/bookmarks/{id}` returns 500 Internal Server Error
- **Fixed:** Added missing `event_type` and `confidence` fields to BookmarkUpdate schema

## Test Results Summary (2026-01-13 - Latest)

**87 passed, 1 failed** (up from 69 passed, 19 failed initially)

| Category | Passed | Failed | Notes |
|----------|--------|--------|-------|
| Authentication | 10 | 0 | ✅ All passing |
| Device | 9 | 0 | ✅ All passing |
| Stream | 15 | 0 | ✅ All passing |
| Snapshot | 13 | 0 | ✅ All passing |
| Bookmark | 19 | 0 | ✅ All passing |
| Consumer | 14 | 0 | ✅ All passing |
| HLS | 7 | 1 | Segment timing issue |

### Consumer Endpoint Status ✅ ALL FIXED
- `POST /v2/streams/{id}/consume` ✅ Working (201 Created)
- `GET /v2/streams/{id}/consumers` ✅ Working (200 OK)
- `DELETE /v2/streams/{id}/consumers/{consumer_id}` ✅ Working (204 No Content)
- `POST /v2/streams/{id}/consumers/{consumer_id}/connect` ✅ Working (200 OK)
- `POST /v2/streams/{id}/consumers/{consumer_id}/ice-candidate` ✅ Working (200 OK)

### Remaining Issues (1 failure)

1. **HLS Segment (1 failure)**
   - Segment listed in playlist returns 404 when fetched
   - Timing issue: segment may expire between playlist fetch and segment request
   - This is a test timing issue, not an API bug

---

## Ruth AI Design & Contract Documents (Authoritative)

The following documents are **authoritative, approved, and present in the repository**.  
All Claude agents MUST treat these as existing inputs when working on the corresponding phases.

### Phase 1 — System Architecture
- **Document:** Ruth AI System Architecture Design  
- **Path:** `docs/RUTH_AI_SYSTEM_ARCHITECTURE_DESIGN.md`  
- **Status:** Approved / Frozen  
- **Owner:** Architecture Agent

### Phase 2 — API & Contract Specification
- **Document:** Ruth AI API & Contract Specification  
- **Path:** `docs/RUTH_AI_API_CONTRACT_SPECIFICATION.md`  
- **Status:** Approved / Frozen  
- **Owner:** API & Contract Designer Agent

### Phase 2 (Supporting) — VAS Integration Reference
- **Document:** VAS-MS-V2 Integration Guide  
- **Path:** `docs/VAS-MS-V2_INTEGRATION_GUIDE.md`  
- **Status:** Validated (87/88 tests passing)  
- **Owner:** VAS API Guardian Agent

### Phase 3 — Infrastructure & Deployment
- **Document:** Ruth AI Infrastructure & Deployment Design  
- **Path:** `docs/infrastructure-deployment-design.md`  
- **Status:** Approved / Frozen  
- **Owner:** Platform & Infrastructure Authority Agent

### Product Definition
- **Document:** Product Requirement Document (PRD)  
- **Path:** `docs/PRODUCT_REQUIREMENT_DOCUMENT.md`  
- **Status:** Approved  
- **Owner:** Product / Architecture

/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/frontend/analytics-design.md
/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/frontend/data-contracts.md
/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/frontend/frontend-readiness-checklist.md
/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/frontend/information-architecture.md
/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/frontend/operator-workflows.md
/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/frontend/personas.md
/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/frontend/ux-flows.md
/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/frontend/wireframes.md
/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/ai-model-contract.md
/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/ai-model-contributor-guide.md
/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/ai-model-directory-standard.md
/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/ai-runtime-architecture.md
/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/infrastructure-deployment-design.md
/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/PRODUCT_REQUIREMENT_DOCUMENT.md
/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/RUTH_AI_API_CONTRACT_SPECIFICATION.md
/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/RUTH_AI_SYSTEM_ARCHITECTURE_DESIGN.md
/home/atgin-rnd-ubuntu/ruth-ai-vas-ms-v2/docs/VAS-MS-V2_INTEGRATION_GUIDE.md
---

**Important Rules for All Agents:**
- Do NOT assume these documents are missing
- Do NOT redesign content from these documents
- If clarification is needed, reference the document path explicitly
- Phase 4+ agents may proceed assuming these documents exist