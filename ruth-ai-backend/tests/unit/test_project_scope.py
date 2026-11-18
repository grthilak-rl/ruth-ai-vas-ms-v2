"""Project view mode: which paths are scoped, and guards against bypasses.

The scope is applied by a do_orm_execute hook (tests/projects/ prove it on
Postgres). What can silently bypass it is raw SQL and a tagged model left
out of SCOPED_MODELS; both are checked here, statically.
"""

import re
import uuid
from pathlib import Path

import pytest

from app.core.project_scope import SCOPED_MODELS, path_mode
from app.models import ProjectTagMixin, StreamSession
from app.models.base import Base
from app.models.project_tag import TAGGED_TABLES

APP = Path(__file__).resolve().parents[2] / "app"
ID = str(uuid.uuid4())


@pytest.mark.parametrize("path, mode", [
    ("/api/v1/violations", "scoped"),
    ("/api/v1/violations/incidents", "scoped"),
    ("/api/v1/violations/types", "scoped"),
    ("/api/v1/violations/bulk", "scoped"),
    ("/api/v1/violations/counts/current-shift", "scoped"),
    ("/api/v1/analytics/summary", "scoped"),
    ("/api/v1/analytics/export", "scoped"),
    ("/api/v1/events", "scoped"),
    ("/api/v1/admin/customer-reports", "scoped"),
    ("/api/v1/admin/customer-reports/defaults", "scoped"),
    ("/api/v1/admin/violation-exports/preview", "scoped"),
    (f"/api/v1/violations/{ID}", "by_id"),
    (f"/api/v1/violations/{ID}/frame/image", "by_id"),
    (f"/api/v1/violations/{ID}/clip", "by_id"),
    (f"/api/v1/admin/customer-reports/{ID}/download", "by_id"),
    (f"/api/v1/admin/violation-exports/{ID}/download", "by_id"),
    (f"/api/v1/events/{ID}", "by_id"),
    ("/api/v1/devices", "live"),
    (f"/api/v1/devices/{ID}/start-inference", "live"),
    ("/api/v1/models/status", "live"),
    ("/api/v1/health", "live"),
    ("/api/v1/bookmark-analyses", "live"),
    ("/internal/events", "live"),
    ("/api/v1/violationsX", "live"),  # prefix match is on segments
])
def test_path_mode(path, mode):
    assert path_mode(path) == mode


def test_every_tagged_model_is_scoped_except_sessions():
    tagged = {m.class_.__tablename__ for m in Base.registry.mappers if issubclass(m.class_, ProjectTagMixin)}
    assert tagged == set(TAGGED_TABLES)
    scoped = {m.__tablename__ for m in SCOPED_MODELS}
    # Sessions are live operational state; see SCOPED_MODELS for why.
    assert scoped == tagged - {StreamSession.__tablename__}


def test_no_raw_sql_reads_a_tagged_table():
    """text()/exec_driver_sql bypasses the scope. Filter explicitly or use the ORM."""
    pattern = re.compile(
        r"\b(FROM|JOIN|UPDATE|INTO)\s+(" + "|".join(TAGGED_TABLES) + r")\b", re.IGNORECASE
    )
    offenders = []
    for path in APP.rglob("*.py"):
        source = path.read_text()
        for m in re.finditer(r"text\(\s*(f?\"\"\"|f?\"|f?')(.*?)(\1)", source, re.DOTALL):
            if pattern.search(m.group(2)):
                offenders.append(f"{path.relative_to(APP)}: {m.group(2)[:60]!r}")
    assert offenders == []
