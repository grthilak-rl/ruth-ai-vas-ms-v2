"""DB-backed tests for /api/v1/admin/model-store.

Chunk assembly, resume, sha256 mismatch, quota, file limits, reserved and
tombstoned ids, deletes, stale-staging cleanup. See conftest.py for setup.
"""

import hashlib
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.models.model_store import ModelStoreUpload
from app.services.model_store import service
from tests.model_store.conftest import DATABASE_URL, TEST_CHUNK

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="MODEL_STORE_TEST_DATABASE_URL not set")

BASE = "/api/v1/admin/model-store"


# =============================================================================
# Helpers
# =============================================================================


async def new_model(client, display_name="PPE six items", **extra):
    response = await client.post(f"{BASE}/models", json={"display_name": display_name, **extra})
    assert response.status_code == 201, response.text
    return response.json()


async def init(client, model_pk, filename, data, **extra):
    return await client.post(
        f"{BASE}/models/{model_pk}/uploads",
        json={"filename": filename, "size_bytes": len(data), **extra},
    )


def chunks_of(data: bytes) -> list[bytes]:
    return [data[i : i + TEST_CHUNK] for i in range(0, len(data), TEST_CHUNK)]


async def put(client, upload_id, index, chunk):
    return await client.put(f"{BASE}/uploads/{upload_id}/chunks/{index}", content=chunk)


async def upload_file(client, model_pk, filename, data, order=None, **extra):
    """Init, send every chunk (optionally out of order), complete."""
    started = await init(client, model_pk, filename, data, **extra)
    assert started.status_code == 201, started.text
    upload = started.json()
    pieces = chunks_of(data)
    for index in order or range(len(pieces)):
        assert (await put(client, upload["id"], index, pieces[index])).status_code == 200
    return upload, await client.post(f"{BASE}/uploads/{upload['id']}/complete")


# =============================================================================
# Models and ids
# =============================================================================


async def test_create_generates_model_id_and_lists(client, admin_username):
    model = await new_model(client, "PPE — six items")
    assert model["model_id"] == "ppe_six_items"
    assert model["state"] == "draft"
    assert model["model_id_editable"] is True
    assert model["status"] == "no_files"
    assert model["created_by"] == admin_username

    listed = (await client.get(f"{BASE}/models")).json()["models"]
    assert [m["model_id"] for m in listed] == ["ppe_six_items"]


@pytest.mark.parametrize(
    "model_id",
    ["fall_detection", "ppe_detection", "geo_fencing", "tank_overflow_monitoring",
     "chane_tank_monitor", "helmet_detection", "fire_detection", "intrusion_detection",
     "chane_tank_overflow"],
)
async def test_reserved_model_ids_rejected(client, model_id):
    response = await client.post(f"{BASE}/models", json={"display_name": "x", "model_id": model_id})
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "invalid_model_id"


async def test_generated_id_never_reserved(client):
    model = await new_model(client, "Fall Detection")
    assert model["model_id"] == "fall_detection_2"


async def test_tombstoned_id_is_never_reused(client):
    model = await new_model(client, "Harness", model_id="harness_model")
    assert (await client.delete(f"{BASE}/models/{model['id']}")).status_code == 204

    again = await client.post(
        f"{BASE}/models", json={"display_name": "Harness", "model_id": "harness_model"}
    )
    assert again.status_code == 409
    assert again.json()["detail"]["error"] == "model_id_taken"
    # Generation skips the tombstone too.
    assert (await new_model(client, "Harness Model"))["model_id"] == "harness_model_2"


async def test_model_id_editable_while_draft(client):
    model = await new_model(client, "Vest")
    renamed = await client.patch(f"{BASE}/models/{model['id']}", json={"model_id": "vest_v1"})
    assert renamed.status_code == 200
    assert renamed.json()["model_id"] == "vest_v1"
    reserved = await client.patch(f"{BASE}/models/{model['id']}", json={"model_id": "ppe_detection"})
    assert reserved.status_code == 422


# =============================================================================
# Chunked upload
# =============================================================================


async def test_chunk_assembly_out_of_order(client, store, admin_username):
    model = await new_model(client)
    data = os.urandom(3 * TEST_CHUNK - 72)  # 3 chunks, short last one
    upload, completed = await upload_file(client, model["id"], "hardhat.pt", data, order=[2, 0, 1])

    assert completed.status_code == 200, completed.text
    record = completed.json()["file"]
    assert record["sha256"] == hashlib.sha256(data).hexdigest()
    assert record["size_bytes"] == len(data)
    assert record["uploaded_by"] == admin_username

    on_disk = store.root / "drafts" / model["id"] / "weights" / "hardhat.pt"
    assert on_disk.read_bytes() == data
    assert not (store.root / "staging" / upload["id"]).exists()

    files = (await client.get(f"{BASE}/models/{model['id']}/files")).json()["files"]
    assert [(f["filename"], f["sha256"]) for f in files] == [("hardhat.pt", record["sha256"])]
    detail = (await client.get(f"{BASE}/models/{model['id']}")).json()
    assert detail["status"] == "uploaded"
    assert detail["file_count"] == 1


async def test_resume_after_reload_and_idempotent_chunk_retry(client):
    model = await new_model(client)
    data = os.urandom(3 * TEST_CHUNK)
    pieces = chunks_of(data)

    first = (await init(client, model["id"], "vest.pt", data)).json()
    assert (await put(client, first["id"], 0, pieces[0])).status_code == 200
    assert (await put(client, first["id"], 0, pieces[0])).status_code == 200  # retry

    # "Page reload": the client re-inits the same file and gets the same upload.
    resumed = await init(client, model["id"], "vest.pt", data)
    assert resumed.status_code == 200
    assert resumed.json()["id"] == first["id"]
    assert resumed.json()["received_chunks"] == [0]
    listed = (await client.get(f"{BASE}/models/{model['id']}/uploads")).json()["uploads"]
    assert [u["id"] for u in listed] == [first["id"]]

    for index in (1, 2):
        assert (await put(client, first["id"], index, pieces[index])).status_code == 200
    completed = await client.post(f"{BASE}/uploads/{first['id']}/complete")
    assert completed.status_code == 200
    assert completed.json()["file"]["sha256"] == hashlib.sha256(data).hexdigest()
    # A retried complete returns the same file.
    again = await client.post(f"{BASE}/uploads/{first['id']}/complete")
    assert again.status_code == 200
    assert again.json()["file"]["id"] == completed.json()["file"]["id"]


async def test_sha256_mismatch_fails_upload(client, store):
    model = await new_model(client)
    data = os.urandom(2 * TEST_CHUNK)
    upload, completed = await upload_file(
        client, model["id"], "gloves.pt", data, sha256="0" * 64
    )
    assert completed.status_code == 422
    detail = completed.json()["detail"]
    assert detail["error"] == "sha256_mismatch"
    assert detail["actual_sha256"] == hashlib.sha256(data).hexdigest()

    state = (await client.get(f"{BASE}/uploads/{upload['id']}")).json()
    assert state["status"] == "failed"  # persisted despite the error response
    assert not (store.root / "staging" / upload["id"]).exists()
    assert (await client.get(f"{BASE}/models/{model['id']}/files")).json()["files"] == []


async def test_matching_client_sha256_accepted(client):
    model = await new_model(client)
    data = os.urandom(TEST_CHUNK + 5)
    _, completed = await upload_file(
        client, model["id"], "boots.pt", data, sha256=hashlib.sha256(data).hexdigest()
    )
    assert completed.status_code == 200


async def test_complete_with_missing_chunks(client):
    model = await new_model(client)
    data = os.urandom(3 * TEST_CHUNK)
    upload = (await init(client, model["id"], "goggles.pt", data)).json()
    await put(client, upload["id"], 1, chunks_of(data)[1])
    response = await client.post(f"{BASE}/uploads/{upload['id']}/complete")
    assert response.status_code == 409
    assert response.json()["detail"]["missing_chunks"] == [0, 2]


@pytest.mark.parametrize(
    ("index", "size", "status"),
    [(0, TEST_CHUNK - 1, 400), (0, TEST_CHUNK + 1, 413), (1, 10, 400), (5, TEST_CHUNK, 422)],
    ids=["short", "long", "short-last", "out-of-range"],
)
async def test_chunk_length_and_index_enforced(client, index, size, status):
    model = await new_model(client)
    data = os.urandom(TEST_CHUNK + 50)  # chunk 0 = 1024, chunk 1 = 50
    upload = (await init(client, model["id"], "x.pt", data)).json()
    response = await put(client, upload["id"], index, b"\0" * size)
    assert response.status_code == status, response.text


# =============================================================================
# Limits and validation
# =============================================================================


async def test_staging_quota_checked_before_accepting(client):
    model = await new_model(client)
    big = os.urandom(10 * TEST_CHUNK)  # quota is 16 chunks
    first = await init(client, model["id"], "a.pt", big)
    assert first.status_code == 201
    second = await init(client, model["id"], "b.pt", big)
    assert second.status_code == 507
    assert second.json()["detail"]["error"] == "staging_quota_exceeded"

    # Finishing the first frees its staging share.
    for index, piece in enumerate(chunks_of(big)):
        await put(client, first.json()["id"], index, piece)
    assert (await client.post(f"{BASE}/uploads/{first.json()['id']}/complete")).status_code == 200
    assert (await init(client, model["id"], "b.pt", big)).status_code == 201


async def test_files_per_model_limit(client, monkeypatch):
    monkeypatch.setattr(service, "MAX_FILES_PER_MODEL", 2)
    model = await new_model(client)
    for name in ("a.pt", "b.pt"):
        _, done = await upload_file(client, model["id"], name, os.urandom(10))
        assert done.status_code == 200
    third = await init(client, model["id"], "c.pt", os.urandom(10))
    assert third.status_code == 409
    assert third.json()["detail"]["error"] == "too_many_files"


async def test_file_size_limit(client):
    model = await new_model(client)
    response = await client.post(
        f"{BASE}/models/{model['id']}/uploads",
        json={"filename": "huge.pt", "size_bytes": 64 * TEST_CHUNK + 1},
    )
    assert response.status_code == 413


@pytest.mark.parametrize(
    ("filename", "status"),
    [("model.onnx", 415), ("model.pth", 415), ("../escape.pt", 422), ("a/b.pt", 422), (".hidden.pt", 422)],
)
async def test_filename_rules(client, filename, status):
    model = await new_model(client)
    response = await init(client, model["id"], filename, b"1234")
    assert response.status_code == status, response.text


async def test_duplicate_filename_rejected(client):
    model = await new_model(client)
    await upload_file(client, model["id"], "vest.pt", b"abc")
    response = await init(client, model["id"], "vest.pt", b"abcd")
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "file_exists"


# =============================================================================
# Deletes
# =============================================================================


async def test_delete_single_file(client, store):
    model = await new_model(client)
    _, done = await upload_file(client, model["id"], "vest.pt", b"weights")
    file_id = done.json()["file"]["id"]

    response = await client.delete(f"{BASE}/models/{model['id']}/files/{file_id}")
    assert response.status_code == 204
    assert not (store.root / "drafts" / model["id"] / "weights" / "vest.pt").exists()
    assert (await client.get(f"{BASE}/models/{model['id']}/files")).json()["files"] == []
    # The name can be uploaded again.
    assert (await init(client, model["id"], "vest.pt", b"weights2")).status_code == 201


async def test_delete_draft_moves_to_trash_and_aborts_uploads(client, store):
    model = await new_model(client, "Harness", model_id="harness_ppe")
    await upload_file(client, model["id"], "harness.pt", b"weights")
    pending = (await init(client, model["id"], "vest.pt", os.urandom(2 * TEST_CHUNK))).json()

    assert (await client.delete(f"{BASE}/models/{model['id']}")).status_code == 204

    assert not (store.root / "drafts" / model["id"]).exists()
    trashed = list((store.root / "trash").iterdir())
    assert len(trashed) == 1 and trashed[0].name.startswith(f"harness_ppe__{model['id']}__")
    assert (trashed[0] / "weights" / "harness.pt").read_bytes() == b"weights"
    assert not (store.root / "staging" / pending["id"]).exists()
    assert (await client.get(f"{BASE}/uploads/{pending['id']}")).json()["status"] == "aborted"
    assert (await client.get(f"{BASE}/models/{model['id']}")).status_code == 404
    assert (await client.get(f"{BASE}/models")).json()["models"] == []


# =============================================================================
# Stale staging cleanup
# =============================================================================


async def test_cleanup_expires_stale_uploads_and_orphans(client, store, session_factory):
    model = await new_model(client)
    stale = (await init(client, model["id"], "old.pt", os.urandom(TEST_CHUNK))).json()
    fresh = (await init(client, model["id"], "new.pt", os.urandom(TEST_CHUNK))).json()

    async with session_factory() as db:
        await db.execute(
            update(ModelStoreUpload)
            .where(ModelStoreUpload.id == stale["id"])
            .values(updated_at=datetime.now(timezone.utc) - timedelta(hours=25))
        )
        await db.commit()

    orphan = store.root / "staging" / "orphan-leftover"
    orphan.mkdir()
    day_ago = time.time() - 25 * 3600
    os.utime(orphan, (day_ago, day_ago))

    async with session_factory() as db:
        result = await service.cleanup_stale_staging(db, store)
        await db.commit()

    assert result == {"expired_uploads": 1, "orphans_removed": 1}
    assert (await client.get(f"{BASE}/uploads/{stale['id']}")).json()["status"] == "expired"
    assert not (store.root / "staging" / stale["id"]).exists()
    assert not orphan.exists()
    assert (await client.get(f"{BASE}/uploads/{fresh['id']}")).json()["status"] == "uploading"
    assert (store.root / "staging" / fresh["id"]).exists()


# =============================================================================
# Store not mounted
# =============================================================================


async def test_store_unavailable_returns_503(app, client, monkeypatch, tmp_path):
    from app.services.model_store import _configured_store, get_model_store

    app.dependency_overrides.pop(get_model_store)
    monkeypatch.setenv("MODEL_STORE_ROOT", str(tmp_path / "not-mounted"))
    _configured_store.cache_clear()
    try:
        response = await client.get(f"{BASE}/models")
        assert response.status_code == 503
        assert response.json()["detail"]["error"] == "model_store_unavailable"
        # The rest of the API is unaffected.
        assert (await client.get("/api/v1/health/live")).status_code == 200
    finally:
        _configured_store.cache_clear()
