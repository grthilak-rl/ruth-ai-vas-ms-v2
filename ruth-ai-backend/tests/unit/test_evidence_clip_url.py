"""The clip URL the evidence player loads must be the MP4 proxy.

It pointed at /violations/{id}/video — the clip's JSON status — so <video>
errored and "Play Evidence" silently did nothing for every ready clip.
"""

import uuid

from app.api.v1.violations import build_evidence_summary
from app.models import Evidence
from app.models.enums import EvidenceStatus, EvidenceType


def bookmark(vas_bookmark_id: str | None = "3b069b07-8c57-4d9b-b82b-4df1c8f2db95") -> Evidence:
    return Evidence(
        id=uuid.uuid4(),
        violation_id=uuid.uuid4(),
        evidence_type=EvidenceType.BOOKMARK,
        status=EvidenceStatus.READY,
        vas_bookmark_id=vas_bookmark_id,
    )


def test_bookmark_url_is_the_range_enabled_mp4_proxy():
    evidence = bookmark()
    assert evidence.bookmark_url == "/api/v1/bookmarks/3b069b07-8c57-4d9b-b82b-4df1c8f2db95/video"
    assert "/violations/" not in evidence.bookmark_url


def test_no_url_without_a_vas_bookmark_or_for_other_evidence():
    assert bookmark(None).bookmark_url is None
    snapshot = bookmark()
    snapshot.evidence_type = EvidenceType.SNAPSHOT
    assert snapshot.bookmark_url is None


def test_summary_carries_the_playable_url():
    summary = build_evidence_summary([bookmark()])
    assert summary.bookmark_status == "ready"
    assert summary.bookmark_url == "/api/v1/bookmarks/3b069b07-8c57-4d9b-b82b-4df1c8f2db95/video"
