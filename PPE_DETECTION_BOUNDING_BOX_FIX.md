# PPE Detection Bounding Box Coordinate Fix - 2026-01-18

## Problem
Bounding boxes were appearing far off-screen and not aligned with detected persons in the video.

### Root Cause
**Incorrect coordinate scaling assumption:**
- The code assumed PPE detection API returns coordinates in 640×640 model space
- **Reality:** The API returns coordinates in the **original video frame dimensions** (e.g., 1920×1080)
- This caused coordinates like `x1: 867` to be scaled by `0.96` (616/640) instead of `0.32` (616/1920)
- Result: Bounding boxes drawn way outside the visible canvas area

### Evidence
Console logs showed:
```
canvasWidth: 616, canvasHeight: 346
person_bbox.x1: 867.14  // Already in 1920-wide video space!
scaleX: 0.9625  // WRONG - scaling from 640
scaleY: 0.540625
```

After fix:
```
canvasWidth: 616, canvasHeight: 346
videoWidth: 1920, videoHeight: 1080
scaleX: 0.32083  // CORRECT - scaling from 1920
scaleY: 0.32037
```

## Solution

### Files Changed

#### 1. `/home/ruth-ai-vas-ms-v2/frontend/src/services/ppeDetection.ts`

**Changed:** `drawPPEDetections` function signature and scaling logic

**Before:**
```typescript
export function drawPPEDetections(
  ctx: CanvasRenderingContext2D,
  detections: PPEPersonDetection[],
  canvasWidth: number,
  canvasHeight: number
): void {
  // WRONG: Assumed 640x640 model space
  const scaleX = canvasWidth / MODEL_SIZE;  // MODEL_SIZE = 640
  const scaleY = canvasHeight / MODEL_SIZE;
  // ...
}
```

**After:**
```typescript
export function drawPPEDetections(
  ctx: CanvasRenderingContext2D,
  detections: PPEPersonDetection[],
  canvasWidth: number,
  canvasHeight: number,
  videoWidth?: number,    // NEW: Pass actual video dimensions
  videoHeight?: number
): void {
  // CORRECT: Scale from actual video dimensions to canvas
  const scaleX = videoWidth ? canvasWidth / videoWidth : 1;
  const scaleY = videoHeight ? canvasHeight / videoHeight : 1;
  // ...
}
```

**Also removed:** Unused `MODEL_SIZE` constant (line 116)

#### 2. `/home/ruth-ai-vas-ms-v2/frontend/src/components/video/LiveVideoPlayer.tsx`

**Changed:** Pass video dimensions to `drawPPEDetections`

**Before:**
```typescript
drawPPEDetections(
  ctx,
  ppeDetection.detections,
  canvas.width,
  canvas.height
);
```

**After:**
```typescript
drawPPEDetections(
  ctx,
  ppeDetection.detections,
  canvas.width,
  canvas.height,
  ppeDetection.videoWidth,   // NEW: Pass video frame dimensions
  ppeDetection.videoHeight
);
```

## Verification

### Console Logs
With the fix applied, you should see:
```
[PPEDetection] drawPPEDetections called: {
  detectionsCount: 1,
  canvasWidth: 616,
  canvasHeight: 346,
  videoWidth: 1920,
  videoHeight: 1080,
  ...
}
[PPEDetection] Scale factors: {
  scaleX: 0.32083333333333336,
  scaleY: 0.32037037037037036,
  videoWidth: 1920,
  videoHeight: 1080,
  canvasWidth: 616,
  canvasHeight: 346
}
```

### Visual Verification
- Bounding boxes should now appear directly on top of detected persons
- Person boxes (green/red) should align with people in the video
- Individual PPE item boxes (hardhat, vest, etc.) should align with the items
- Missing PPE text should appear below the person's bounding box

## Technical Details

### Coordinate Flow
1. **Video Element** → 1920×1080 pixels (native resolution)
2. **Frame Extraction** → Captured at video.videoWidth × video.videoHeight (1920×1080)
3. **PPE API** → Receives 1920×1080 image, returns detections in same coordinate space
4. **Canvas** → 616×346 pixels (browser rendering size)
5. **Scaling Required** → 1920×1080 → 616×346 (factor of ~0.32)

### Why This Wasn't Obvious
- Fall detection models **do** output in 640×640 space (they resize images internally)
- PPE detection model preserves original image dimensions
- No explicit documentation of coordinate system in API responses
- Error only visible when video dimensions ≠ canvas dimensions

## Related Issues

This fix also required:
- GPU support added to PPE detection container (see `PPE_DETECTION_GPU_CONFIGURATION.md`)
- FPS increased from 0.02 to 1.0 for real-time detection
- Frontend bundle caching issues requiring hard refresh

## Deployment

Build and deploy commands:
```bash
docker compose build ruth-ai-frontend
docker compose up -d --force-recreate ruth-ai-frontend
```

Bundle hash after fix: `index-Cn2BBtco.js`
