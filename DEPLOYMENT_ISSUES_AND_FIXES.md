# Ruth AI Deployment Issues & Fixes

**Date:** 2026-01-18
**Deployment Target:** VAS-MS-V2 at 10.30.250.99:8085
**Status:** Successfully resolved, but requires systematic fixes

---

## Executive Summary

During the first deployment of Ruth AI to a new VAS instance, we encountered **4 critical deployment blockers** that required manual intervention. Each issue prevented the system from functioning and took significant time to diagnose and resolve. These issues MUST be addressed before the next deployment.

**Total Time Lost:** ~3-4 hours
**Root Cause:** Missing automated setup steps in deployment pipeline

---

## Issue #1: GPU Not Detected in Backend Container

### Symptom
Hardware Capacity card showed "No GPU detected" despite NVIDIA GeForce RTX 3090 being present and visible to host system (`nvidia-smi` worked on host).

### Root Cause
The `ruth-ai-backend` service in `docker-compose.yml` lacked GPU passthrough configuration. The container couldn't access NVIDIA libraries or GPU hardware.

### Manual Fix Applied
Added GPU device reservation to backend service in `docker-compose.yml`:

```yaml
ruth-ai-backend:
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: all
            capabilities: [gpu, utility]
```

### Impact
- **Severity:** High - GPU features completely non-functional
- **User Visible:** Yes - Hardware capacity shows "CPU Mode" instead of GPU metrics
- **Time to Diagnose:** 30 minutes
- **Time to Fix:** 15 minutes (includes container rebuild)

### Required Fix
1. **Make GPU support conditional but automatic**
   - Detect GPU availability during deployment
   - Auto-configure docker-compose with GPU passthrough if available
   - Gracefully fall back to CPU mode if no GPU present

2. **Update Dockerfile**
   - Consider creating separate Dockerfile variants for CPU/GPU builds
   - Or use multi-stage builds with runtime GPU detection

3. **Add deployment validation**
   - Post-deployment health check should verify GPU status
   - Fail deployment if GPU expected but not accessible

---

## Issue #2: Database Migrations Not Executed

### Symptom
All API endpoints returned 500 errors:
```
sqlalchemy.exc.ProgrammingError: relation "violations" does not exist
```

Backend health checks passed, but any database query failed.

### Root Cause
The backend Dockerfile has no automatic migration execution. Database tables were never created.

**Current Dockerfile CMD:**
```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

No migration step exists in:
- Dockerfile entrypoint
- docker-compose startup
- Application initialization code

### Manual Fix Applied
1. Created migration script: `ruth-ai-backend/run_migrations.sh`
2. Ran migrations manually from host:
   ```bash
   cd ruth-ai-backend
   mv alembic db_migrations  # Workaround for path shadowing
   python3 -m venv /tmp/migrate_venv
   source /tmp/migrate_venv/bin/activate
   pip install alembic asyncpg sqlalchemy
   PYTHONPATH=$(pwd) DATABASE_URL="postgresql+asyncpg://ruth:ruth_dev_password@10.30.250.99:5434/ruth_ai" \
     alembic -c <(sed 's|script_location = alembic|script_location = db_migrations|' alembic.ini) upgrade head
   mv db_migrations alembic
   ```

### Impact
- **Severity:** Critical - Complete system failure
- **User Visible:** Yes - All API calls fail with 500 errors
- **Time to Diagnose:** 45 minutes
- **Time to Fix:** 30 minutes

### Additional Complexity
The `/app/alembic` directory name shadows the `alembic` Python package, causing import errors:
```python
from alembic.config import main
# ModuleNotFoundError: No module named 'alembic.config'
```

This required renaming the directory during migration execution.

### Required Fix

**Option A: Automatic Migrations on Startup (Recommended for Dev)**
1. Create entrypoint script:
   ```bash
   #!/bin/bash
   set -e

   # Run migrations
   cd /app
   PYTHONPATH=/app alembic upgrade head

   # Start application
   exec uvicorn app.main:app --host 0.0.0.0 --port 8080
   ```

2. Update Dockerfile:
   ```dockerfile
   COPY entrypoint.sh /entrypoint.sh
   RUN chmod +x /entrypoint.sh
   ENTRYPOINT ["/entrypoint.sh"]
   ```

**Option B: Separate Migration Job (Recommended for Production)**
1. Add init container to docker-compose:
   ```yaml
   ruth-ai-db-migrate:
     image: ruth-ai-backend
     command: ["alembic", "upgrade", "head"]
     environment:
       DATABASE_URL: ${DATABASE_URL}
       PYTHONPATH: /app
     depends_on:
       postgres:
         condition: service_healthy
     restart: "no"

   ruth-ai-backend:
     depends_on:
       ruth-ai-db-migrate:
         condition: service_completed_successfully
   ```

**Option C: Makefile Target**
```makefile
migrate:
	docker compose run --rm ruth-ai-backend alembic upgrade head

deploy: migrate
	docker compose up -d
```

**Critical: Fix Directory Naming Conflict**
Rename `/app/alembic/` to `/app/migrations/` to avoid shadowing the alembic package:
- Update `alembic.ini`: `script_location = migrations`
- Update `.gitignore` if needed
- Update documentation

---

## Issue #3: Invalid VAS Credentials

### Symptom
Backend startup logs showed:
```
{"error": "Invalid client credentials [INVALID_CREDENTIALS] (HTTP 401)",
 "event": "Failed to initialize VAS client", "level": "error"}
```

System Health showed:
- VAS: ❌ Unhealthy
- AI Runtime: ❌ Not initialized

All device-related endpoints returned 500:
```
RuntimeError: VAS client not initialized
```

### Root Cause
Docker-compose used incorrect VAS client credentials:
- **Used:** `VAS_CLIENT_ID=ruth-ai-backend`
- **Correct:** `VAS_CLIENT_ID=vas-portal`

The default client in VAS is `vas-portal`, not `ruth-ai-backend`. The backend tried to authenticate with non-existent credentials.

### Manual Fix Applied
Updated `.env`:
```bash
VAS_CLIENT_ID=vas-portal
VAS_CLIENT_SECRET=vas-portal-secret-2024
```

Recreated containers:
```bash
docker compose up -d --force-recreate ruth-ai-backend ruth-ai-frontend
```

### Impact
- **Severity:** Critical - No VAS integration possible
- **User Visible:** Yes - "No cameras configured" even when cameras exist in VAS
- **Time to Diagnose:** 20 minutes
- **Time to Fix:** 5 minutes

### Required Fix

1. **Environment Validation Script**
   Create `scripts/validate-env.sh`:
   ```bash
   #!/bin/bash
   set -e

   echo "Validating VAS credentials..."

   # Test VAS authentication
   response=$(curl -s -X POST "${VAS_BASE_URL}/v2/auth/token" \
     -H "Content-Type: application/json" \
     -d "{\"client_id\": \"${VAS_CLIENT_ID}\", \"client_secret\": \"${VAS_CLIENT_SECRET}\"}")

   if echo "$response" | grep -q "access_token"; then
     echo "✓ VAS credentials valid"
   else
     echo "✗ VAS authentication failed:"
     echo "$response"
     exit 1
   fi
   ```

2. **Pre-deployment Checklist**
   Add to deployment documentation:
   ```
   Before deploying Ruth AI:
   1. Verify VAS is accessible at ${VAS_BASE_URL}
   2. Test VAS credentials using validate-env.sh
   3. Ensure VAS API version compatibility (v2)
   ```

3. **Better Error Messages**
   Update backend startup to fail fast with actionable errors:
   ```python
   try:
       await vas_client.connect()
   except AuthenticationError as e:
       logger.error(
           "VAS authentication failed. Please verify:\n"
           f"  - VAS_BASE_URL is correct: {settings.vas_base_url}\n"
           f"  - VAS_CLIENT_ID is valid: {settings.vas_client_id}\n"
           "  - VAS_CLIENT_SECRET matches the client_id\n"
           f"Original error: {e}"
       )
       raise SystemExit(1)
   ```

4. **Environment Template with Documentation**
   Update `.env.example`:
   ```bash
   # VAS Integration
   # NOTE: Use the default 'vas-portal' client unless you've created a custom client in VAS
   VAS_BASE_URL=http://localhost:8085
   VAS_CLIENT_ID=vas-portal  # Default VAS client (DO NOT CHANGE unless custom client exists)
   VAS_CLIENT_SECRET=vas-portal-secret-2024
   ```

---

## Issue #4: No Automatic Device Sync from VAS

### Symptom
Ruth AI frontend showed "No cameras configured" even though:
- VAS had 2 cameras configured and streaming
- VAS connectivity was working
- Backend was healthy

### Root Cause
Ruth AI maintains its own device registry separate from VAS. There's no automatic synchronization mechanism. Cameras must be manually added to Ruth AI's database even though they exist in VAS.

### Manual Fix Applied
Created and executed `sync_devices.py` script:
```python
# Fetches devices from VAS API
vas_devices = await vas_client.get_devices()

# Inserts into Ruth AI database
for vas_device in vas_devices:
    device = Device(
        id=uuid4(),
        vas_device_id=vas_device.id,
        name=vas_device.name,
        is_active=vas_device.is_active,
        ...
    )
    session.add(device)
```

Synced 2 devices:
- Cabin Camera (VAS ID: d6e45ffc-5211-4f81-a3db-3f19b4c843e2)
- Warehouse camera 124 (VAS ID: c830222f-9b8a-4c49-86ac-9e0cd5897c9a)

### Impact
- **Severity:** High - System appears non-functional to users
- **User Visible:** Yes - Empty state shown despite cameras existing
- **Time to Diagnose:** 40 minutes
- **Time to Fix:** 45 minutes (script creation + debugging)

### Required Fix

**Option A: Automatic Sync on Startup (Recommended)**
1. Add device sync to backend startup:
   ```python
   @app.on_event("startup")
   async def sync_devices_from_vas():
       """Sync devices from VAS on backend startup."""
       logger.info("Syncing devices from VAS...")

       device_service = DeviceService(session)
       vas_client = get_vas_client()

       vas_devices = await vas_client.get_devices()

       for vas_device in vas_devices:
           await device_service.sync_device_from_vas(vas_device)

       logger.info(f"Synced {len(vas_devices)} devices from VAS")
   ```

2. Add `DeviceService.sync_device_from_vas()` method:
   ```python
   async def sync_device_from_vas(self, vas_device: VASDevice):
       """Upsert device from VAS data."""
       existing = await self.get_by_vas_id(vas_device.id)

       if existing:
           # Update existing
           existing.name = vas_device.name
           existing.is_active = vas_device.is_active
           existing.last_synced_at = datetime.now(timezone.utc)
       else:
           # Create new
           device = Device(
               id=uuid4(),
               vas_device_id=vas_device.id,
               name=vas_device.name,
               is_active=vas_device.is_active,
               ...
           )
           self.session.add(device)

       await self.session.commit()
   ```

**Option B: Periodic Background Sync**
1. Add background task with APScheduler:
   ```python
   from apscheduler.schedulers.asyncio import AsyncIOScheduler

   scheduler = AsyncIOScheduler()

   @scheduler.scheduled_job('interval', minutes=5)
   async def sync_devices():
       """Sync devices from VAS every 5 minutes."""
       # Same logic as Option A

   @app.on_event("startup")
   async def start_scheduler():
       scheduler.start()
   ```

**Option C: Manual Sync Endpoint (Fallback)**
Add API endpoint for manual sync:
```python
@router.post("/devices/sync", status_code=200)
async def sync_devices_from_vas(
    device_service: DeviceServiceDep,
    vas_client: VASClientDep,
):
    """Manually trigger device sync from VAS."""
    vas_devices = await vas_client.get_devices()

    for vas_device in vas_devices:
        await device_service.sync_device_from_vas(vas_device)

    return {"synced": len(vas_devices)}
```

**Recommendation:** Implement **Option A** (startup sync) + **Option C** (manual endpoint)
- Startup sync ensures devices are always available
- Manual endpoint allows re-sync without restart
- Add sync status to `/api/v1/health` endpoint

---

## Deployment Automation Checklist

To prevent these issues in future deployments, implement:

### Pre-Deployment
- [ ] Environment variable validation script
- [ ] VAS connectivity test
- [ ] VAS credential verification
- [ ] GPU detection and docker-compose auto-configuration
- [ ] Database connection test

### During Deployment
- [ ] Automatic database migrations (via entrypoint or init container)
- [ ] Automatic device sync from VAS on startup
- [ ] GPU passthrough auto-configuration based on availability
- [ ] Health check validation before marking deployment complete

### Post-Deployment
- [ ] Verify GPU detection (if GPU present)
- [ ] Verify VAS connectivity
- [ ] Verify device count matches VAS
- [ ] Verify sample API calls (devices, violations, health)
- [ ] Check system health dashboard

### Deployment Script Template

```bash
#!/bin/bash
# deploy.sh - Automated Ruth AI Deployment

set -e

echo "======================================"
echo "Ruth AI Deployment Script"
echo "======================================"

# 1. Validate environment
echo "→ Validating environment..."
./scripts/validate-env.sh

# 2. Configure GPU support
echo "→ Configuring GPU support..."
if nvidia-smi &>/dev/null; then
    echo "  ✓ GPU detected, enabling GPU support"
    export ENABLE_GPU=true
    envsubst < docker-compose.gpu.yml > docker-compose.override.yml
else
    echo "  ℹ No GPU detected, using CPU mode"
    export ENABLE_GPU=false
fi

# 3. Pull/build images
echo "→ Building images..."
docker compose build

# 4. Start database
echo "→ Starting database..."
docker compose up -d postgres redis
sleep 5

# 5. Run migrations
echo "→ Running database migrations..."
docker compose run --rm ruth-ai-backend alembic upgrade head

# 6. Start all services
echo "→ Starting all services..."
docker compose up -d

# 7. Wait for health
echo "→ Waiting for services to be healthy..."
timeout 60 bash -c 'until curl -sf http://localhost:8090/api/v1/health >/dev/null; do sleep 2; done'

# 8. Sync devices from VAS
echo "→ Syncing devices from VAS..."
docker compose exec -T ruth-ai-backend python /app/sync_devices.py

# 9. Validate deployment
echo "→ Validating deployment..."
./scripts/validate-deployment.sh

echo "======================================"
echo "✓ Deployment complete!"
echo "======================================"
echo "Ruth AI is running at: http://localhost:3300"
echo "Backend API at: http://localhost:8090"
echo "System Health: http://localhost:8090/api/v1/health"
```

---

## File Modifications Required

### 1. Dockerfile Changes
**File:** `ruth-ai-backend/Dockerfile`

**Add entrypoint script:**
```dockerfile
# Add before CMD
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
```

**Create:** `ruth-ai-backend/entrypoint.sh`
```bash
#!/bin/bash
set -e

echo "Running database migrations..."
cd /app
PYTHONPATH=/app alembic upgrade head
echo "✓ Migrations complete"

echo "Starting Ruth AI Backend..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8080
```

### 2. Docker Compose Changes
**File:** `docker-compose.yml`

**Make GPU support conditional:**
```yaml
ruth-ai-backend:
  # ... existing config ...
  deploy:
    resources:
      reservations:
        devices:
          # This section will be added by deploy script if GPU available
          ${GPU_CONFIG}
```

**Create:** `docker-compose.gpu.yml` (template)
```yaml
services:
  ruth-ai-backend:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu, utility]
```

### 3. Backend Application Changes
**File:** `ruth-ai-backend/app/main.py`

**Add device sync to startup:**
```python
@app.on_event("startup")
async def startup_sync_devices():
    """Sync devices from VAS on startup."""
    if not settings.skip_device_sync:  # Allow disabling for tests
        from app.services.device_sync import sync_devices_from_vas
        try:
            count = await sync_devices_from_vas()
            logger.info(f"Synced {count} devices from VAS")
        except Exception as e:
            logger.warning(f"Failed to sync devices: {e}")
            # Don't fail startup, but log warning
```

**Create:** `ruth-ai-backend/app/services/device_sync.py`
```python
"""Device synchronization from VAS."""
# Implementation of sync logic
```

### 4. Migration Directory Rename
**Current:** `/app/alembic/`
**New:** `/app/migrations/`

**Files to update:**
- `alembic.ini`: Change `script_location = alembic` → `script_location = migrations`
- `ruth-ai-backend/Dockerfile`: Update COPY command
- Documentation references

### 5. Environment Template
**File:** `.env.example`

**Add comprehensive documentation:**
```bash
# ============================================
# VAS Integration Configuration
# ============================================
# IMPORTANT: Verify these settings before deployment
#
# VAS_BASE_URL: The URL where VAS-MS-V2 is running
# VAS_CLIENT_ID: Must match a client configured in VAS
#                Default is 'vas-portal' - DO NOT CHANGE unless custom
# VAS_CLIENT_SECRET: Secret for the client_id
#
# To verify credentials:
#   curl -X POST ${VAS_BASE_URL}/v2/auth/token \
#     -H "Content-Type: application/json" \
#     -d '{"client_id":"${VAS_CLIENT_ID}","client_secret":"${VAS_CLIENT_SECRET}"}'
#
VAS_BASE_URL=http://localhost:8085
VAS_CLIENT_ID=vas-portal
VAS_CLIENT_SECRET=vas-portal-secret-2024
VAS_WEBRTC_URL=ws://localhost:3002
```

---

## Testing Requirements

Before marking these fixes complete, add automated tests:

### Integration Tests
```python
def test_deployment_with_clean_database():
    """Test deployment from scratch."""
    # 1. Start containers
    # 2. Verify migrations ran
    # 3. Verify VAS connection
    # 4. Verify devices synced
    # 5. Verify GPU detected (if present)

def test_deployment_with_existing_database():
    """Test deployment upgrade scenario."""
    # 1. Create old schema
    # 2. Run migrations
    # 3. Verify schema updated
    # 4. Verify data preserved

def test_deployment_with_invalid_vas_credentials():
    """Test graceful failure on bad credentials."""
    # 1. Set invalid credentials
    # 2. Start containers
    # 3. Verify clear error message
    # 4. Verify backend doesn't crash
```

### Validation Script
**Create:** `scripts/validate-deployment.sh`
```bash
#!/bin/bash
set -e

echo "Validating Ruth AI deployment..."

# Test health endpoint
echo "→ Checking health endpoint..."
health=$(curl -sf http://localhost:8090/api/v1/health)
echo "$health" | jq -e '.components.database.status == "healthy"' >/dev/null
echo "$health" | jq -e '.components.vas.status == "healthy"' >/dev/null
echo "  ✓ Health checks passed"

# Test devices synced
echo "→ Checking device sync..."
devices=$(curl -sf http://localhost:8090/api/v1/devices)
device_count=$(echo "$devices" | jq -r '.total')
if [ "$device_count" -gt 0 ]; then
    echo "  ✓ $device_count devices synced"
else
    echo "  ✗ No devices found"
    exit 1
fi

# Test GPU detection (if available)
if nvidia-smi &>/dev/null; then
    echo "→ Checking GPU detection..."
    hardware=$(curl -sf http://localhost:8090/api/v1/system/hardware)
    echo "$hardware" | jq -e '.gpu.available == true' >/dev/null
    echo "  ✓ GPU detected"
fi

echo "✓ All validation checks passed"
```

---

## Priority Ranking

**P0 (Blocker - Fix Immediately):**
1. ✅ Automatic database migrations
2. ✅ Automatic device sync from VAS
3. ✅ VAS credential validation with clear errors

**P1 (Critical - Fix Before Next Deployment):**
4. ✅ GPU auto-configuration based on detection
5. ✅ Deployment validation script
6. ✅ Fix alembic directory shadowing issue

**P2 (Important - Fix Soon):**
7. ⏳ Deployment automation script
8. ⏳ Integration tests for deployment scenarios
9. ⏳ Comprehensive .env documentation

**P3 (Nice to Have):**
10. ⏳ Background device sync (periodic refresh)
11. ⏳ Multi-environment deployment configs (dev/staging/prod)
12. ⏳ Rollback procedures

---

## Lessons Learned

1. **Never assume manual steps will be remembered**
   - Database migrations must be automatic
   - Device sync must be automatic
   - Configuration validation must be automatic

2. **Deployment should be one command**
   - Current: 10+ manual steps over 4 hours
   - Target: `./deploy.sh` completes in <5 minutes

3. **Fail fast with clear errors**
   - Wrong credentials should fail immediately with actionable message
   - Missing GPU should log clearly, not silently fail
   - Missing migrations should be detected before startup

4. **Test deployment from clean state**
   - We only tested "already working" systems
   - First clean deployment revealed all these issues
   - Add CI/CD pipeline that tests clean deployment

5. **Document deployment assumptions**
   - VAS must be running first
   - Database must be accessible
   - GPU is optional but should be detected
   - Default credentials are 'vas-portal', not 'ruth-ai-backend'

---

## Next Steps

1. **Immediate (This Week):**
   - [ ] Implement automatic migrations (P0)
   - [ ] Implement automatic device sync (P0)
   - [ ] Add VAS credential validation (P0)
   - [ ] Create deployment validation script (P1)

2. **Short Term (Next Sprint):**
   - [ ] Fix alembic directory naming (P1)
   - [ ] Implement GPU auto-detection (P1)
   - [ ] Create deployment automation script (P2)
   - [ ] Write deployment integration tests (P2)

3. **Long Term (Next Month):**
   - [ ] Add CI/CD pipeline with deployment tests
   - [ ] Create deployment documentation/runbook
   - [ ] Implement periodic device sync (P3)
   - [ ] Multi-environment deployment configs (P3)

---

**Document Owner:** System Integration Team
**Last Updated:** 2026-01-18
**Status:** Active - Tracking remediation

