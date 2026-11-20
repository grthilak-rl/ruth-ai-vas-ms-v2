"""Model notes and recommended models (Settings -> AI Models), on Postgres.

Notes: dated, admin-written, kept across install/uninstall, ``internal``
hides one from the camera picker. Recommendations: one per violation type,
only for an installed model that raises it, with one of its own notes as the
reason; uninstalling makes it inactive, reinstalling active again.
"""

from datetime import date, datetime, timezone

import pytest

from app.models.project import Project
from app.services.model_store import notes as notes_service
from app.services.model_store import seed_notes
from app.services.model_store.enabled import StoreModelInfo
from tests.model_store.conftest import DATABASE_URL

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="MODEL_STORE_TEST_DATABASE_URL not set")

BASE = "/api/v1/admin/model-store"


async def new_model(client, model_id, display_name=None):
    r = await client.post(f"{BASE}/models", json={"display_name": display_name or model_id, "model_id": model_id})
    assert r.status_code == 201, r.text
    return r.json()


async def add_note(client, model_pk, body="Fires on pipe clutter", observed_on="2026-10-17", **extra):
    r = await client.post(
        f"{BASE}/models/{model_pk}/notes", json={"body": body, "observed_on": observed_on, **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


def info(model_id, *types, name=None):
    return StoreModelInfo(model_id, "1.0.0", name or model_id, (), False, True, violation_types=types)


@pytest.fixture
def installed(monkeypatch):
    """Set what is installed: installed({"hard_hat": ("missing_hardhat",)})."""
    from app.api.v1.admin import model_store as admin_api

    def set_installed(models: dict):
        table = {m: info(m, *types) for m, types in models.items()}
        monkeypatch.setattr(notes_service, "enabled_store_models", lambda: table)
        monkeypatch.setattr(admin_api, "enabled_store_models", lambda: table)

    set_installed({})
    return set_installed


async def make_project(session_factory, name, state="ended"):
    async with session_factory() as db:
        project = Project(
            name=name, slug=name.lower().replace(" ", "-"), state=state,
            started_at=datetime(2026, 10, 16, tzinfo=timezone.utc), started_by="admin",
        )
        db.add(project)
        await db.commit()
        return project.id


# =============================================================================
# Notes
# =============================================================================


async def test_notes_are_dated_listed_newest_first_and_editable(client, admin_username, session_factory):
    hpcl = await make_project(session_factory, "HPCL")
    model = await new_model(client, "gloves_x")
    old = await add_note(client, model["id"], "Inert on 32 frames", "2026-10-17", project_id=str(hpcl),
                         source="/mnt/storage/ruth-models/eval/2026-10-17/README.md")
    new = await add_note(client, model["id"], "Catches bare hands at ~0.7", "2026-11-01", internal=True)

    assert old["project_name"] == "HPCL" and old["created_by"] == admin_username
    assert old["internal"] is False and new["internal"] is True
    listed = (await client.get(f"{BASE}/models/{model['id']}/notes")).json()["notes"]
    assert [n["body"] for n in listed] == ["Catches bare hands at ~0.7", "Inert on 32 frames"]

    edited = await client.patch(f"{BASE}/notes/{old['id']}", json={"internal": True, "project_id": None, "source": None})
    assert edited.status_code == 200
    body = edited.json()
    assert (body["internal"], body["project_id"], body["source"]) == (True, None, None)
    assert body["body"] == "Inert on 32 frames" and body["edited_by"] == admin_username


async def test_note_validation(client):
    model = await new_model(client, "vest_x")
    blank = await client.post(f"{BASE}/models/{model['id']}/notes", json={"body": "   ", "observed_on": "2026-10-17"})
    assert blank.status_code == 422
    no_project = await client.post(
        f"{BASE}/models/{model['id']}/notes",
        json={"body": "x", "observed_on": "2026-10-17", "project_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert no_project.status_code == 422
    assert no_project.json()["detail"]["message"] == "That project does not exist"


async def test_deleted_note_disappears(client):
    model = await new_model(client, "vest_y")
    note = await add_note(client, model["id"])
    assert (await client.delete(f"{BASE}/notes/{note['id']}")).status_code == 204
    assert (await client.get(f"{BASE}/models/{model['id']}/notes")).json()["notes"] == []
    assert (await client.patch(f"{BASE}/notes/{note['id']}", json={"body": "x"})).status_code == 404


async def test_notes_survive_uninstall_and_reinstall(client, installed):
    model = await new_model(client, "harness_x")
    await add_note(client, model["id"])
    for state in ({"harness_x": ("missing_harness",)}, {}, {"harness_x": ("missing_harness",)}):
        installed(state)
        assert len((await client.get(f"{BASE}/models/{model['id']}/notes")).json()["notes"]) == 1


async def test_latest_public_note_skips_internal_and_deleted(client, session_factory):
    model = await new_model(client, "goggles_x")
    await add_note(client, model["id"], "Public, older", "2026-10-18")
    await add_note(client, model["id"], "Internal, newest", "2026-11-01", internal=True)
    gone = await add_note(client, model["id"], "Deleted, newer", "2026-10-20")
    await client.delete(f"{BASE}/notes/{gone['id']}")
    other = await new_model(client, "goggles_y")

    async with session_factory() as db:
        latest = await notes_service.latest_public_notes(db, ["goggles_x", "goggles_y"])
    assert latest["goggles_x"].body == "Public, older"
    assert latest["goggles_x"].observed_on == date(2026, 10, 18)
    assert "goggles_y" not in latest and other  # no notes, no entry


# =============================================================================
# Recommendations
# =============================================================================


async def test_recommend_one_model_per_violation_type_with_its_note(client, installed, admin_username):
    hard_hat = await new_model(client, "hard_hat_x", "Hard Hat")
    rival = await new_model(client, "hard_hat_y", "Hard Hat 2")
    installed({"hard_hat_x": ("missing_hardhat",), "hard_hat_y": ("missing_hardhat",)})
    reason = await add_note(client, hard_hat["id"], "Inconclusive but the only working one")
    rival_reason = await add_note(client, rival["id"], "Better on bare heads")

    r = await client.put(f"{BASE}/recommendations/missing_hardhat",
                         json={"model_pk": hard_hat["id"], "note_id": reason["id"]})
    assert r.status_code == 200, r.text
    (rec,) = r.json()["recommendations"]
    assert (rec["model_id"], rec["label"], rec["active"]) == ("hard_hat_x", "Missing hard hat", True)
    assert rec["note"]["body"] == "Inconclusive but the only working one" and rec["set_by"] == admin_username

    detail = (await client.get(f"{BASE}/models/{hard_hat['id']}")).json()
    assert detail["recommended_for"] == ["missing_hardhat"] and detail["violation_types"] == ["missing_hardhat"]
    notes = (await client.get(f"{BASE}/models/{hard_hat['id']}/notes")).json()["notes"]
    assert notes[0]["reason_for"] == ["missing_hardhat"]

    # Recommending the rival replaces it: still one per type.
    r = await client.put(f"{BASE}/recommendations/missing_hardhat",
                         json={"model_pk": rival["id"], "note_id": rival_reason["id"]})
    assert [x["model_id"] for x in r.json()["recommendations"]] == ["hard_hat_y"]
    assert (await client.get(f"{BASE}/models/{hard_hat['id']}")).json()["recommended_for"] == []


async def test_recommendation_rules(client, installed):
    vest = await new_model(client, "vest_z")
    other = await new_model(client, "other_z")
    vest_note = await add_note(client, vest["id"])
    other_note = await add_note(client, other["id"])

    not_installed = await client.put(f"{BASE}/recommendations/missing_vest",
                                     json={"model_pk": vest["id"], "note_id": vest_note["id"]})
    assert not_installed.status_code == 409
    assert not_installed.json()["detail"]["error"] == "model_not_installed"

    installed({"vest_z": ("missing_vest",), "other_z": ("missing_gloves",)})
    wrong_type = await client.put(f"{BASE}/recommendations/missing_hardhat",
                                  json={"model_pk": vest["id"], "note_id": vest_note["id"]})
    assert wrong_type.status_code == 422
    assert wrong_type.json()["detail"]["error"] == "violation_type_not_raised"
    assert "raises missing_vest" in wrong_type.json()["detail"]["message"]

    foreign_note = await client.put(f"{BASE}/recommendations/missing_vest",
                                    json={"model_pk": vest["id"], "note_id": other_note["id"]})
    assert foreign_note.status_code == 422
    assert foreign_note.json()["detail"]["error"] == "note_not_for_model"


async def test_reason_note_cannot_be_deleted_while_in_use(client, installed):
    vest = await new_model(client, "vest_r")
    installed({"vest_r": ("missing_vest",)})
    note = await add_note(client, vest["id"])
    await client.put(f"{BASE}/recommendations/missing_vest", json={"model_pk": vest["id"], "note_id": note["id"]})

    refused = await client.delete(f"{BASE}/notes/{note['id']}")
    assert refused.status_code == 409
    assert refused.json()["detail"]["error"] == "note_in_use"
    assert "Missing safety vest" in refused.json()["detail"]["message"]

    assert (await client.delete(f"{BASE}/recommendations/missing_vest")).status_code == 204
    assert (await client.delete(f"{BASE}/recommendations/missing_vest")).status_code == 404
    assert (await client.delete(f"{BASE}/notes/{note['id']}")).status_code == 204


async def test_uninstalling_the_recommended_model_makes_it_inactive_not_replaced(client, installed):
    goggles = await new_model(client, "goggles_r", "Goggles 3")
    installed({"goggles_r": ("missing_goggles",)})
    note = await add_note(client, goggles["id"])
    await client.put(f"{BASE}/recommendations/missing_goggles", json={"model_pk": goggles["id"], "note_id": note["id"]})

    installed({})
    (rec,) = (await client.get(f"{BASE}/recommendations")).json()["recommendations"]
    assert (rec["model_id"], rec["active"]) == ("goggles_r", False)
    assert (await client.get(f"{BASE}/models/{goggles['id']}")).json()["recommended_for"] == []

    installed({"goggles_r": ("missing_goggles",)})
    (rec,) = (await client.get(f"{BASE}/recommendations")).json()["recommendations"]
    assert rec["active"] is True


# =============================================================================
# Seed
# =============================================================================


async def test_seed_adds_notes_and_three_recommendations_once(client, installed, session_factory):
    await make_project(session_factory, "HPCL")
    await make_project(session_factory, "Post HPCL Dev", state="active")
    for model_id in {s.model_id for s in seed_notes.SEEDS}:
        await new_model(client, model_id)
    installed({"hard_hat": ("missing_hardhat",), "safety_vest": ("missing_vest",),
               "goggles_3": ("missing_goggles",), "harness_3": ("missing_harness",)})

    async with session_factory() as db:
        plan = await seed_notes.seed(db, apply=False)
        await db.rollback()
    assert sum(line.startswith("would add") for line in plan) == len(seed_notes.SEEDS) == 14

    async with session_factory() as db:
        report = await seed_notes.seed(db, apply=True)
        await db.commit()
    assert sum(line.startswith("add ") for line in report) == 14
    assert not any(line.startswith("FAIL") for line in report)

    recs = (await client.get(f"{BASE}/recommendations")).json()["recommendations"]
    assert {(r["violation_type"], r["model_id"]) for r in recs} == {
        ("missing_goggles", "goggles_3"), ("missing_hardhat", "hard_hat"), ("missing_vest", "safety_vest")
    }
    hard_hat = next(r for r in recs if r["model_id"] == "hard_hat")
    assert hard_hat["note"]["created_by"] == "imported"
    assert hard_hat["note"]["observed_on"] == "2026-10-17"
    assert hard_hat["note"]["project_name"] == "HPCL"
    assert hard_hat["note"]["source"].startswith("/mnt/storage/ruth-models/eval/2026-10-17/")

    # Re-running adds nothing and leaves recommendations alone.
    async with session_factory() as db:
        again = await seed_notes.seed(db, apply=True)
        await db.commit()
    assert not any(line.startswith(("add ", "recommend ")) for line in again)
    assert len((await client.get(f"{BASE}/recommendations")).json()["recommendations"]) == 3


async def test_seed_never_overrides_an_admins_recommendation(client, installed, session_factory):
    await make_project(session_factory, "HPCL")
    goggles_3 = await new_model(client, "goggles_3")
    no_goggles = await new_model(client, "no_goggles")
    installed({"goggles_3": ("missing_goggles",), "no_goggles": ("missing_goggles",)})
    mine = await add_note(client, no_goggles["id"], "My pick")
    await client.put(f"{BASE}/recommendations/missing_goggles", json={"model_pk": no_goggles["id"], "note_id": mine["id"]})

    async with session_factory() as db:
        report = await seed_notes.seed(db, apply=True)
        await db.commit()
    assert "have  recommendation for missing_goggles (left as is)" in report
    (rec,) = (await client.get(f"{BASE}/recommendations")).json()["recommendations"]
    assert rec["model_id"] == "no_goggles" and goggles_3
