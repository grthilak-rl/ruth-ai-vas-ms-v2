"""fall_pose (store) replacing the built-in fall_detection: what the backend
reads from its manifest must leave fall violations, past and new, labelled,
gated and graded exactly as before."""

import json
import shutil
from pathlib import Path

import pytest

from app.models.enums import ViolationType
from app.services.model_store.enabled import read_enabled_models
from app.services.violation_labels import ViolationLabeler
from app.services.violation_severity import resolve_severity

MANIFEST = (
    Path(__file__).resolve().parents[3] / "ai" / "store_plugin" / "manifests" / "fall_pose.json"
)


@pytest.fixture
def store(tmp_path):
    version_dir = tmp_path / "fall_pose" / "1.0.0"
    version_dir.mkdir(parents=True)
    shutil.copyfile(MANIFEST, version_dir / "store_manifest.json")
    return read_enabled_models(tmp_path)


def test_backend_reads_the_pose_manifest(store):
    info = store["fall_pose"]
    assert info.display_name == "Fall Detection"
    # Same gate the built-in model had (session threshold 0.7).
    assert info.min_confidence == 0.7
    # A fall model is not a PPE model, and needs no zone.
    assert info.reports_ppe is False
    assert info.zone_required_rules == () and info.all_rules_need_zone is False
    assert info.rule_severity("fall_detected") == "critical"
    assert info.rule_severity("possible_fall") == "high"


def test_labels_unchanged_for_past_and_new_rows(store):
    before, after = ViolationLabeler({}), ViolationLabeler(store)
    for model_id in ("fall_detection", "fall_pose"):  # past rows, new rows
        for detail in (None, "possible_fall"):
            row = (ViolationType.FALL_DETECTED, detail, model_id)
            assert after.combined_label(*row) == before.combined_label(*row)
    assert after.combined_label(ViolationType.FALL_DETECTED, None, "fall_pose") == "Fall Detected"
    assert after.detail_label("possible_fall", "fall_pose") == "Possible fall"


@pytest.mark.parametrize("detail, level", [(None, "critical"), ("possible_fall", "high")])
def test_severity_of_unbackfilled_past_rows_unchanged(store, detail, level):
    """Past fall rows here carry NULL severity and are graded at read time;
    installing fall_pose must not regrade them."""
    for models in ({}, store):
        assert resolve_severity(
            type_=ViolationType.FALL_DETECTED, type_detail=detail,
            model_id="fall_detection", store_models=models,
        ) == level


def test_new_rows_take_the_plugin_reported_severity(store):
    for reported, detail in (("critical", None), ("high", "possible_fall")):
        assert resolve_severity(
            reported=reported, type_=ViolationType.FALL_DETECTED, type_detail=detail,
            model_id="fall_pose", store_models=store,
        ) == reported


def test_manifest_emits_only_known_fall_types():
    from app.models.enums import VIOLATION_TYPE_MAP

    rules = json.loads(MANIFEST.read_text())["rules"]
    for rule in rules:
        assert VIOLATION_TYPE_MAP[rule["violation_type"]] is ViolationType.FALL_DETECTED
