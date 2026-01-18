/**
 * PPE Detection Service
 * Extracts frames from video element and sends to PPE detection model
 * Detects: hardhat, vest, gloves, goggles, boots, mask (violation only)
 */

export interface PPEBoundingBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  confidence: number;
  class_name: string;
}

export interface PPEPersonDetection {
  person_bbox: {
    x1: number;
    y1: number;
    x2: number;
    y2: number;
    confidence: number;
  };
  ppe_items: {
    hardhat: PPEBoundingBox | null;
    vest: PPEBoundingBox | null;
    gloves: PPEBoundingBox | null;
    goggles: PPEBoundingBox | null;
    boots: PPEBoundingBox | null;
    mask: PPEBoundingBox | null;
  };
  missing_ppe: string[];
  violations: string[];
}

export interface PPEDetectionResult {
  success: boolean;
  mode: 'presence' | 'violation' | 'full';
  model_version: string;
  person_count: number;
  violation_detected: boolean;
  violations: string[];
  detections: PPEPersonDetection[];
  inference_time_ms: number;
  timestamp: number;
  // Store video dimensions for coordinate scaling
  videoWidth?: number;
  videoHeight?: number;
}

// Raw API response types (from the PPE detection model)
interface RawPPEDetection {
  item: string;
  status: 'present' | 'missing';
  confidence: number;
  bbox: [number, number, number, number];  // [x1, y1, x2, y2]
  class_id: number;
  class_name: string;
  model_source: string;
}

interface RawPPEAPIResponse {
  success: boolean;
  model: string;
  violation_detected: boolean;
  violation_type: string | null;
  severity: string;
  confidence: number;
  detections: RawPPEDetection[];
  persons_detected: number;
  violations: string[];
  ppe_present: string[];
  detection_count: number;
  model_name: string;
  model_version: string;
  mode: string;
  inference_time_ms: number;
  timestamp: string;
}

export interface PPEDetectionConfig {
  fps: number;           // Frame rate for inference (default: 1 - slower due to 12 models)
  enabled: boolean;      // Whether detection is active
  mode: 'presence' | 'violation' | 'full';  // Detection mode
}

// PPE item colors for visualization
export const PPE_COLORS: Record<string, string> = {
  hardhat: '#fbbf24',    // Amber
  vest: '#f97316',       // Orange
  gloves: '#a855f7',     // Purple
  goggles: '#3b82f6',    // Blue
  boots: '#84cc16',      // Lime
  mask: '#06b6d4',       // Cyan
  person: '#22c55e',     // Green
  violation: '#ef4444',  // Red
};

// PPE item labels for display
export const PPE_LABELS: Record<string, string> = {
  hardhat: 'Hard Hat',
  vest: 'Safety Vest',
  gloves: 'Gloves',
  goggles: 'Safety Goggles',
  boots: 'Safety Boots',
  mask: 'Face Mask',
};

const DEFAULT_CONFIG: PPEDetectionConfig = {
  fps: 1,  // 1 FPS - PPE detection with 12 models on GPU (~500ms-1s per frame)
  enabled: true,
  mode: 'full',  // Full mode: detect persons, present PPE items, and missing/violation items
};

/**
 * Transform raw API response to the expected PPEDetectionResult format
 * Groups flat detections into person-centric structure
 */
function transformAPIResponse(
  rawResponse: RawPPEAPIResponse,
  videoWidth?: number,
  videoHeight?: number
): PPEDetectionResult {
  const personDetections: PPEPersonDetection[] = [];

  // Find all person detections first
  const persons = rawResponse.detections.filter(d => d.item === 'person' || d.model_source === 'person');
  const ppeItems = rawResponse.detections.filter(d => d.item !== 'person' && d.model_source !== 'person');

  // If persons detected, group PPE items with each person
  if (persons.length > 0) {
    for (const person of persons) {
      const [x1, y1, x2, y2] = person.bbox;

      // Find PPE items that overlap with this person's bbox
      const associatedPPE: Record<string, PPEBoundingBox | null> = {
        hardhat: null,
        vest: null,
        gloves: null,
        goggles: null,
        boots: null,
        mask: null,
      };

      const missingPPE: string[] = [];
      const violations: string[] = [];

      for (const ppe of ppeItems) {
        const [px1, py1, px2, py2] = ppe.bbox;

        // Check if PPE bbox overlaps with person bbox (simple overlap check)
        const overlaps = !(px2 < x1 || px1 > x2 || py2 < y1 || py1 > y2);

        if (overlaps) {
          const ppeItem = ppe.item.toLowerCase().replace('no_', '');

          if (ppe.status === 'present' && ppeItem in associatedPPE) {
            associatedPPE[ppeItem] = {
              x1: px1,
              y1: py1,
              x2: px2,
              y2: py2,
              confidence: ppe.confidence,
              class_name: ppe.class_name,
            };
          } else if (ppe.status === 'missing') {
            if (!missingPPE.includes(ppeItem)) {
              missingPPE.push(ppeItem);
            }
            if (!violations.includes(ppeItem)) {
              violations.push(ppeItem);
            }
          }
        }
      }

      personDetections.push({
        person_bbox: {
          x1,
          y1,
          x2,
          y2,
          confidence: person.confidence,
        },
        ppe_items: associatedPPE as PPEPersonDetection['ppe_items'],
        missing_ppe: missingPPE,
        violations,
      });
    }
  } else if (ppeItems.length > 0) {
    // No person detected but PPE items found - create a synthetic person
    // Use the union of all PPE item bboxes as the person bbox
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

    const associatedPPE: Record<string, PPEBoundingBox | null> = {
      hardhat: null,
      vest: null,
      gloves: null,
      goggles: null,
      boots: null,
      mask: null,
    };

    const missingPPE: string[] = [];
    const violations: string[] = [];

    for (const ppe of ppeItems) {
      const [px1, py1, px2, py2] = ppe.bbox;
      minX = Math.min(minX, px1);
      minY = Math.min(minY, py1);
      maxX = Math.max(maxX, px2);
      maxY = Math.max(maxY, py2);

      const ppeItem = ppe.item.toLowerCase().replace('no_', '');

      if (ppe.status === 'present' && ppeItem in associatedPPE) {
        associatedPPE[ppeItem] = {
          x1: px1,
          y1: py1,
          x2: px2,
          y2: py2,
          confidence: ppe.confidence,
          class_name: ppe.class_name,
        };
      } else if (ppe.status === 'missing') {
        if (!missingPPE.includes(ppeItem)) {
          missingPPE.push(ppeItem);
        }
        if (!violations.includes(ppeItem)) {
          violations.push(ppeItem);
        }
      }
    }

    if (minX !== Infinity) {
      personDetections.push({
        person_bbox: {
          x1: minX,
          y1: minY,
          x2: maxX,
          y2: maxY,
          confidence: 0.5,  // Synthetic person, lower confidence
        },
        ppe_items: associatedPPE as PPEPersonDetection['ppe_items'],
        missing_ppe: missingPPE,
        violations,
      });
    }
  }

  return {
    success: rawResponse.success,
    mode: rawResponse.mode as 'presence' | 'violation' | 'full',
    model_version: rawResponse.model_version,
    person_count: rawResponse.persons_detected || personDetections.length,
    violation_detected: rawResponse.violation_detected,
    violations: rawResponse.violations,
    detections: personDetections,
    inference_time_ms: rawResponse.inference_time_ms,
    timestamp: Date.now(),
    videoWidth,
    videoHeight,
  };
}

/**
 * Extract a single frame from video element as JPEG blob
 */
export function extractFrameFromVideo(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement
): Promise<Blob | null> {
  return new Promise((resolve) => {
    if (!video.videoWidth || !video.videoHeight) {
      console.warn('[PPEDetection] Video not ready for frame extraction');
      resolve(null);
      return;
    }

    // Set canvas size to match video
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      console.error('[PPEDetection] Could not get canvas context');
      resolve(null);
      return;
    }

    // Draw video frame to canvas
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    // Convert to JPEG blob
    canvas.toBlob(
      (blob) => {
        resolve(blob);
      },
      'image/jpeg',
      0.8 // Quality
    );
  });
}

/**
 * Send frame to PPE detection model API
 */
export async function detectPPE(
  frameBlob: Blob,
  mode: 'presence' | 'violation' | 'full' = 'violation',
  videoWidth?: number,
  videoHeight?: number
): Promise<PPEDetectionResult | null> {
  try {
    const formData = new FormData();
    formData.append('file', frameBlob, 'frame.jpg');

    const response = await fetch(`/ppe-detection/detect?mode=${mode}`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      console.error('[PPEDetection] API error:', response.status, response.statusText);
      return null;
    }

    const rawResult: RawPPEAPIResponse = await response.json();
    console.log('[PPEDetection] Raw API response:', rawResult);
    console.log('[PPEDetection] Raw detections count:', rawResult.detections?.length || 0);
    console.log('[PPEDetection] Raw detections:', rawResult.detections);

    // Transform the flat API response into person-centric structure
    const transformedResult = transformAPIResponse(rawResult, videoWidth, videoHeight);
    console.log('[PPEDetection] Transformed result:', transformedResult);
    console.log('[PPEDetection] Transformed detections count:', transformedResult.detections?.length || 0);
    console.log('[PPEDetection] Transformed detections:', transformedResult.detections);

    return transformedResult;
  } catch (error) {
    console.error('[PPEDetection] Request failed:', error);
    return null;
  }
}

/**
 * Check if PPE detection model is available
 */
export async function checkPPEModelHealth(): Promise<boolean> {
  try {
    const response = await fetch('/ppe-detection/health');
    if (!response.ok) return false;
    const data = await response.json();
    return data.status === 'healthy';
  } catch {
    return false;
  }
}

/**
 * Draw PPE detection overlays on canvas
 */
export function drawPPEDetections(
  ctx: CanvasRenderingContext2D,
  detections: PPEPersonDetection[],
  canvasWidth: number,
  canvasHeight: number,
  videoWidth?: number,
  videoHeight?: number
): void {
  console.log('[PPEDetection] drawPPEDetections called:', {
    detectionsCount: detections.length,
    canvasWidth,
    canvasHeight,
    videoWidth,
    videoHeight,
    detections: JSON.stringify(detections, null, 2)
  });

  // IMPORTANT: Coordinates from the API are in the VIDEO frame dimensions,
  // NOT in 640x640 model space. We need to scale from video dimensions to canvas dimensions.
  // If videoWidth/Height are not provided, assume they match canvas (no scaling needed)
  const scaleX = videoWidth ? canvasWidth / videoWidth : 1;
  const scaleY = videoHeight ? canvasHeight / videoHeight : 1;

  console.log('[PPEDetection] Scale factors:', { scaleX, scaleY, videoWidth, videoHeight, canvasWidth, canvasHeight });

  detections.forEach((detection, personIdx) => {
    const { person_bbox, ppe_items, violations, missing_ppe } = detection;
    const hasViolations = violations.length > 0;

    // Scale person bounding box
    const px1 = person_bbox.x1 * scaleX;
    const py1 = person_bbox.y1 * scaleY;
    const px2 = person_bbox.x2 * scaleX;
    const py2 = person_bbox.y2 * scaleY;

    // Draw person bounding box
    ctx.strokeStyle = hasViolations ? PPE_COLORS.violation : PPE_COLORS.person;
    ctx.lineWidth = 3;
    ctx.strokeRect(px1, py1, px2 - px1, py2 - py1);

    // Draw person label
    const personLabel = hasViolations
      ? `Person ${personIdx + 1} - PPE VIOLATION`
      : `Person ${personIdx + 1} - PPE OK`;
    ctx.font = 'bold 14px sans-serif';
    const textWidth = ctx.measureText(personLabel).width;
    ctx.fillStyle = hasViolations ? PPE_COLORS.violation : PPE_COLORS.person;
    ctx.fillRect(px1, py1 - 22, textWidth + 10, 22);
    ctx.fillStyle = '#ffffff';
    ctx.fillText(personLabel, px1 + 5, py1 - 6);

    // Draw detected PPE items
    const ppeKeys = ['hardhat', 'vest', 'gloves', 'goggles', 'boots', 'mask'] as const;
    ppeKeys.forEach((key) => {
      const item = ppe_items[key];
      if (item) {
        const ix1 = item.x1 * scaleX;
        const iy1 = item.y1 * scaleY;
        const ix2 = item.x2 * scaleX;
        const iy2 = item.y2 * scaleY;

        // Draw PPE item bounding box
        ctx.strokeStyle = PPE_COLORS[key];
        ctx.lineWidth = 2;
        ctx.strokeRect(ix1, iy1, ix2 - ix1, iy2 - iy1);

        // Draw PPE item label
        const itemLabel = `${PPE_LABELS[key]} (${Math.round(item.confidence * 100)}%)`;
        ctx.font = '12px sans-serif';
        const itemTextWidth = ctx.measureText(itemLabel).width;
        ctx.fillStyle = PPE_COLORS[key];
        ctx.fillRect(ix1, iy1 - 18, itemTextWidth + 6, 18);
        ctx.fillStyle = '#ffffff';
        ctx.fillText(itemLabel, ix1 + 3, iy1 - 4);
      }
    });

    // Draw missing PPE indicators
    if (missing_ppe.length > 0) {
      const missingText = `Missing: ${missing_ppe.map(k => PPE_LABELS[k] || k).join(', ')}`;
      ctx.font = 'bold 12px sans-serif';
      const missingWidth = ctx.measureText(missingText).width;
      ctx.fillStyle = 'rgba(239, 68, 68, 0.9)'; // Red with transparency
      ctx.fillRect(px1, py2 + 5, missingWidth + 10, 20);
      ctx.fillStyle = '#ffffff';
      ctx.fillText(missingText, px1 + 5, py2 + 18);
    }
  });
}

/**
 * PPE Detection Manager
 * Manages continuous frame extraction and inference
 */
export class PPEDetectionManager {
  private video: HTMLVideoElement | null = null;
  private canvas: HTMLCanvasElement;
  private config: PPEDetectionConfig;
  private intervalId: number | null = null;
  private isProcessing = false;
  private onResult: ((result: PPEDetectionResult) => void) | null = null;

  constructor(config: Partial<PPEDetectionConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    // Create offscreen canvas for frame extraction
    this.canvas = document.createElement('canvas');
  }

  /**
   * Start PPE detection on video element
   */
  start(
    video: HTMLVideoElement,
    onResult: (result: PPEDetectionResult) => void
  ): void {
    this.video = video;
    this.onResult = onResult;

    if (!this.config.enabled) {
      console.log('[PPEDetection] Detection disabled');
      return;
    }

    const intervalMs = 1000 / this.config.fps;
    console.log(`[PPEDetection] Starting detection at ${this.config.fps} FPS (${intervalMs}ms interval), mode: ${this.config.mode}`);

    this.intervalId = window.setInterval(() => {
      this.processFrame();
    }, intervalMs);
  }

  /**
   * Stop PPE detection
   */
  stop(): void {
    if (this.intervalId !== null) {
      window.clearInterval(this.intervalId);
      this.intervalId = null;
    }
    this.video = null;
    this.onResult = null;
    this.isProcessing = false;
    console.log('[PPEDetection] Detection stopped');
  }

  /**
   * Process a single frame
   */
  private async processFrame(): Promise<void> {
    // Skip if already processing or video not ready
    if (this.isProcessing || !this.video || !this.onResult) {
      if (this.isProcessing) {
        console.log('[PPEDetection] Skipping frame - previous request still processing');
      }
      return;
    }

    // Skip if video is paused or not playing
    if (this.video.paused || this.video.ended || this.video.readyState < 2) {
      return;
    }

    this.isProcessing = true;
    console.log('[PPEDetection] Starting frame processing...');
    const startTime = Date.now();

    try {
      // Extract frame
      const frameBlob = await extractFrameFromVideo(this.video, this.canvas);
      if (!frameBlob) {
        return;
      }

      // Send to model with video dimensions for coordinate scaling
      const result = await detectPPE(
        frameBlob,
        this.config.mode,
        this.video.videoWidth,
        this.video.videoHeight
      );
      const elapsed = Date.now() - startTime;
      console.log(`[PPEDetection] Frame processing completed in ${elapsed}ms, detections: ${result?.detections?.length || 0}`);
      if (result && this.onResult) {
        this.onResult(result);
      }
    } catch (error) {
      console.error('[PPEDetection] Frame processing error:', error);
    } finally {
      this.isProcessing = false;
    }
  }

  /**
   * Update configuration
   */
  setConfig(config: Partial<PPEDetectionConfig>): void {
    const wasRunning = this.intervalId !== null;
    const video = this.video;
    const onResult = this.onResult;

    if (wasRunning) {
      this.stop();
    }

    this.config = { ...this.config, ...config };

    if (wasRunning && video && onResult) {
      this.start(video, onResult);
    }
  }

  /**
   * Get current configuration
   */
  getConfig(): PPEDetectionConfig {
    return { ...this.config };
  }

  /**
   * Set detection mode
   */
  setMode(mode: 'presence' | 'violation' | 'full'): void {
    this.setConfig({ mode });
  }
}
