"""Bookmark analysis pipeline.

End-to-end worker that lands a real summary on a bookmark_analyses
row. Phase D.2 implements ``tank_overflow_monitoring`` specifically;
the dispatch layer is set up so additional models can be added
without restructuring.

Pipeline:

  1. Load row, transition PENDING -> RUNNING.
  2. Stream the bookmark video from VAS to /tmp.
  3. Walk the file with OpenCV, sample frames at the requested fps,
     JPEG-encode each sample.
  4. For each sample, call the unified runtime's /inference.
  5. Aggregate per-frame results into a summary (timeline +
     threshold-crossing events + stats).
  6. Transition COMPLETED with the summary, or FAILED with
     error_message.
  7. Clean up the temp video file.

Frame-level failures (one snapshot fails inference) are non-fatal —
they're counted as ``frames_skipped`` and the summary still lands.
The whole analysis only fails if download, decode, or all-frames-
failed errors occur.
"""

from __future__ import annotations

import asyncio
import base64
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import cv2  # opencv-python-headless
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.deps.services import get_vas_client_optional
from app.integrations.unified_runtime.client import (
    UnifiedRuntimeClient,
    UnifiedRuntimeError,
)
from app.integrations.vas.exceptions import VASError
from app.models import BookmarkAnalysis, BookmarkAnalysisState
from app.schemas.bookmark_analysis import SAMPLING_FPS_DEFAULT

logger = get_logger(__name__)

TEMP_DIR = Path("/tmp/ruth-bookmark-analyses")
TANK_THRESHOLDS = [80, 90]

# Stable UUID5 namespace for synthesizing stream_ids from analysis_ids.
# UnifiedRuntimeClient.submit_inference requires a stream_id UUID; for
# bookmark analyses we don't have a real stream so we deterministically
# derive one from the analysis_id. Same analysis_id always maps to the
# same synthetic stream_id, so the runtime metrics group cleanly.
_ANALYSIS_STREAM_NAMESPACE = uuid.UUID("00000000-0000-0000-0000-000000000d02")


# ---------------------------------------------------------------------------
# Public entry point — called from BackgroundTasks.
# ---------------------------------------------------------------------------


async def run_analysis(analysis_id: uuid.UUID) -> None:
    """BackgroundTasks worker entry point.

    Opens its own DB session (request session has closed by now),
    runs the pipeline, and persists the terminal state. Never crashes
    the BackgroundTasks runner — any uncaught error is logged and
    persisted as FAILED.
    """
    factory = get_session_factory()
    if factory is None:
        logger.error(
            "Cannot run bookmark analysis — DB session factory not initialized",
            analysis_id=str(analysis_id),
        )
        return

    # 1. Load + transition to RUNNING in its own short-lived session.
    async with factory() as db:
        analysis = await _load(db, analysis_id)
        if analysis is None:
            logger.warning(
                "Bookmark analysis row missing when worker started",
                analysis_id=str(analysis_id),
            )
            return
        if analysis.state != BookmarkAnalysisState.PENDING:
            logger.info(
                "Skipping bookmark analysis worker — row not in pending state",
                analysis_id=str(analysis_id),
                state=analysis.state.value,
            )
            return
        analysis.state = BookmarkAnalysisState.RUNNING
        analysis.started_at = datetime.now(timezone.utc)
        await db.commit()

        # Capture immutable fields for the pipeline. Avoids any stale-row
        # issue if a future revision adds row mutation between sessions.
        vas_bookmark_id = analysis.vas_bookmark_id
        model_id = analysis.model_id
        model_version = analysis.model_version
        parameters = dict(analysis.parameters or {})

    logger.info(
        "Bookmark analysis running",
        analysis_id=str(analysis_id),
        model_id=model_id,
        vas_bookmark_id=vas_bookmark_id,
    )

    # 2. Run the pipeline outside any DB session (long-running work).
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    temp_video = TEMP_DIR / f"{analysis_id}.mp4"
    try:
        summary = await _run_pipeline(
            analysis_id=analysis_id,
            vas_bookmark_id=vas_bookmark_id,
            model_id=model_id,
            model_version=model_version,
            parameters=parameters,
            temp_video=temp_video,
        )
    except Exception as exc:
        logger.warning(
            "Bookmark analysis failed",
            analysis_id=str(analysis_id),
            error=str(exc),
            error_type=type(exc).__name__,
        )
        async with factory() as db:
            await _finalize_failed(db, analysis_id, str(exc))
    else:
        async with factory() as db:
            await _finalize_completed(db, analysis_id, summary)
        logger.info(
            "Bookmark analysis completed",
            analysis_id=str(analysis_id),
            frames_analyzed=summary["stats"]["frames_analyzed"],
            frames_skipped=summary["stats"]["frames_skipped"],
        )
    finally:
        try:
            if temp_video.exists():
                temp_video.unlink()
        except OSError as e:
            logger.warning(
                "Failed to clean up temp bookmark video",
                path=str(temp_video),
                error=str(e),
            )


# ---------------------------------------------------------------------------
# Pipeline — pure async logic without DB binding.
# ---------------------------------------------------------------------------


async def _run_pipeline(
    *,
    analysis_id: uuid.UUID,
    vas_bookmark_id: str,
    model_id: str,
    model_version: str | None,
    parameters: dict[str, Any],
    temp_video: Path,
) -> dict[str, Any]:
    """Returns the summary blob on success; raises on fatal failure."""

    # Step 1: download bookmark video from VAS to local file.
    vas = get_vas_client_optional()
    if vas is None:
        raise RuntimeError("VAS client not available — cannot download bookmark")
    try:
        async with vas.download_bookmark_video(vas_bookmark_id) as response:
            with temp_video.open("wb") as fh:
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    fh.write(chunk)
    except VASError as e:
        raise RuntimeError(f"VAS bookmark download failed: {e}") from e

    size_bytes = temp_video.stat().st_size
    logger.debug(
        "Bookmark video downloaded",
        analysis_id=str(analysis_id),
        path=str(temp_video),
        size_bytes=size_bytes,
    )
    if size_bytes == 0:
        raise RuntimeError("Downloaded bookmark video is empty (0 bytes)")

    # Step 2: extract frames at the requested fps. cv2.VideoCapture is
    # synchronous and CPU-bound; run it in a worker thread so we don't
    # block the event loop for the duration of the decode.
    sampling_fps = float(parameters.get("sampling_fps", SAMPLING_FPS_DEFAULT))
    frames = await asyncio.to_thread(_extract_frames_list, temp_video, sampling_fps)
    if not frames:
        raise RuntimeError("No frames extracted from bookmark video")
    logger.info(
        "Extracted frames from bookmark",
        analysis_id=str(analysis_id),
        frame_count=len(frames),
        sampling_fps=sampling_fps,
    )

    # Step 3: per-frame inference via the unified runtime.
    stream_id = uuid.uuid5(_ANALYSIS_STREAM_NAMESPACE, str(analysis_id))
    timeline: list[dict[str, float]] = []
    frames_skipped = 0
    started_at = time.monotonic()

    async with UnifiedRuntimeClient() as runtime:
        for ts_seconds, jpeg_bytes in frames:
            try:
                response = await runtime.submit_inference(
                    model_id=model_id,
                    frame_base64=base64.b64encode(jpeg_bytes).decode("ascii"),
                    stream_id=stream_id,
                    model_version=model_version,
                    frame_format="jpeg",
                    config=parameters,
                    metadata={
                        "source": "bookmark_analysis",
                        "analysis_id": str(analysis_id),
                        "vas_bookmark_id": vas_bookmark_id,
                    },
                )
            except UnifiedRuntimeError as e:
                # Connection-level failure to the runtime is fatal for the
                # whole analysis — no point continuing if it can't reach
                # the model server at all.
                raise RuntimeError(f"AI runtime unreachable: {e}") from e

            if response.status != "success" or response.result is None:
                frames_skipped += 1
                logger.debug(
                    "Frame inference returned non-success; skipping",
                    analysis_id=str(analysis_id),
                    ts_seconds=ts_seconds,
                    status=response.status,
                    error=response.error,
                )
                continue

            fill = _extract_fill_percentage(model_id, response.result)
            if fill is None:
                frames_skipped += 1
                continue
            timeline.append(
                {"timestamp_seconds": ts_seconds, "fill_percentage": fill}
            )

    if not timeline:
        raise RuntimeError(
            f"All {len(frames)} frames failed inference — no fill data to summarize"
        )

    inference_elapsed = time.monotonic() - started_at
    logger.info(
        "Bookmark analysis inference loop done",
        analysis_id=str(analysis_id),
        frames_analyzed=len(timeline),
        frames_skipped=frames_skipped,
        inference_elapsed_seconds=round(inference_elapsed, 2),
    )

    # Step 4: aggregate.
    threshold_events = _detect_threshold_crossings(timeline, TANK_THRESHOLDS)
    stats = _compute_stats(timeline, frames_skipped)

    return {
        "timeline": timeline,
        "threshold_events": threshold_events,
        "stats": stats,
        "metadata": {
            "model_id": model_id,
            "model_version": model_version,
            "sampling_fps": sampling_fps,
            "parameters_used": parameters,
        },
    }


# ---------------------------------------------------------------------------
# Result-shape adapter.
# ---------------------------------------------------------------------------


def _extract_fill_percentage(model_id: str, result: dict[str, Any]) -> float | None:
    """Pull the fill-level number out of a model's inference response.

    tank_overflow_monitoring publishes ``level_percent`` (see
    ai/models/tank_overflow_monitoring/1.0.0/inference.py). We surface
    the public summary field as ``fill_percentage`` for clearer UX
    semantics but read the raw model field here.

    Returns None when the field is missing or non-numeric — caller
    treats that as a skipped frame.
    """
    if model_id == "tank_overflow_monitoring":
        raw = result.get("level_percent")
    else:
        # Unknown model — try common keys defensively. Phase D.2 only
        # implements tank_overflow; this is a soft fallback for D.3+.
        raw = result.get("fill_percentage", result.get("level_percent"))
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


# ---------------------------------------------------------------------------
# Frame extraction (synchronous, runs in a thread).
# ---------------------------------------------------------------------------


def _extract_frames_list(
    video_path: Path, fps: float
) -> list[tuple[float, bytes]]:
    """Materialize all sampled frames as (timestamp_seconds, jpeg_bytes).

    Intentionally NOT a generator: we run this inside ``asyncio.to_thread``
    and need to return a complete result to the event loop.
    """
    return list(_extract_frames(video_path, fps))


def _extract_frames(video_path: Path, fps: float) -> Iterator[tuple[float, bytes]]:
    """Yield ``(timestamp_seconds, jpeg_bytes)`` at approximately ``fps``."""
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise RuntimeError(f"OpenCV cannot open video: {video_path}")
        source_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if source_fps <= 0:
            # Some containers don't expose fps cleanly. Fall back to a
            # safe default — better to over-sample than to refuse to run.
            source_fps = 30.0
            logger.warning(
                "Video reports no fps; assuming 30",
                path=str(video_path),
            )
        frame_interval = source_fps / fps  # source frames per sample
        next_sample_at = 0.0
        frame_idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_idx >= next_sample_at:
                ts = frame_idx / source_fps
                encoded_ok, buf = cv2.imencode(".jpg", frame)
                if encoded_ok:
                    yield ts, bytes(buf)
                next_sample_at += frame_interval
            frame_idx += 1
    finally:
        cap.release()


# ---------------------------------------------------------------------------
# Aggregation helpers.
# ---------------------------------------------------------------------------


def _detect_threshold_crossings(
    timeline: list[dict[str, float]],
    thresholds: list[int],
) -> list[dict[str, Any]]:
    """Detect the first upward crossing of each threshold.

    A crossing is the first timeline sample at or above the threshold
    after having been below it. Tanks don't drain mid-run so we don't
    track downward crossings.
    """
    events: list[dict[str, Any]] = []
    above = {t: False for t in thresholds}
    for sample in timeline:
        ts = sample["timestamp_seconds"]
        fill = sample["fill_percentage"]
        for t in thresholds:
            if not above[t] and fill >= t:
                events.append(
                    {
                        "crossed_at_seconds": ts,
                        "threshold": t,
                        "going_up": True,
                    }
                )
                above[t] = True
    return events


def _compute_stats(
    timeline: list[dict[str, float]],
    frames_skipped: int,
) -> dict[str, Any]:
    """Aggregate stats over the timeline."""
    fills = [s["fill_percentage"] for s in timeline]
    peak = max(fills) if fills else 0.0
    final = fills[-1] if fills else 0.0
    duration = timeline[-1]["timestamp_seconds"] if timeline else 0.0

    def first_at(threshold: float) -> float | None:
        return next(
            (s["timestamp_seconds"] for s in timeline if s["fill_percentage"] >= threshold),
            None,
        )

    return {
        "peak_fill_percentage": peak,
        "final_fill_percentage": final,
        "time_to_80_percent_seconds": first_at(80),
        "time_to_90_percent_seconds": first_at(90),
        "duration_seconds": duration,
        "frames_analyzed": len(timeline),
        "frames_skipped": frames_skipped,
    }


# ---------------------------------------------------------------------------
# DB helpers (small, kept local to the worker).
# ---------------------------------------------------------------------------


async def _load(db: AsyncSession, analysis_id: uuid.UUID) -> BookmarkAnalysis | None:
    return await db.get(BookmarkAnalysis, analysis_id)


async def _finalize_completed(
    db: AsyncSession,
    analysis_id: uuid.UUID,
    summary: dict[str, Any],
) -> None:
    analysis = await _load(db, analysis_id)
    if analysis is None:
        return
    analysis.state = BookmarkAnalysisState.COMPLETED
    analysis.completed_at = datetime.now(timezone.utc)
    analysis.summary = summary
    await db.commit()


async def _finalize_failed(
    db: AsyncSession,
    analysis_id: uuid.UUID,
    error_message: str,
) -> None:
    analysis = await _load(db, analysis_id)
    if analysis is None:
        return
    analysis.state = BookmarkAnalysisState.FAILED
    analysis.completed_at = datetime.now(timezone.utc)
    analysis.error_message = error_message[:2000]
    await db.commit()
