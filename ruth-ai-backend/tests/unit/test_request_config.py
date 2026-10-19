"""The camera name the store plugin sees, and where it comes from.

The plugin is handed only ``(frame, config)``, so ``config`` is the only
channel that can tell it which camera a frame came from — which its trial
summaries need in order to be broken down per camera.

The label is *derived at request time*, not stored on the model entry.
Storing it was the first attempt and it was wrong twice over: the picker
writes ``config: null`` on every add, so a persisted label has to be
re-applied by hand after every tick, and ``models[0].config`` is mirrored
into ``session.model_config``, which ``GET /devices`` returns.

The tests that matter are the ones where a wrong answer is silent — a
built-in model receiving something new, or an operator's zones being
dropped on the way to the runtime.
"""

from uuid import uuid4

import pytest

from app.services.model_store.enabled import StoreModelInfo

DEVICE = uuid4()
OTHER = uuid4()


class _Loop:
    """Only the state `_request_config` touches."""

    def __init__(self, names):
        self._device_names = names


@pytest.fixture
def request_config(monkeypatch):
    """`_request_config` with the store-model lookup faked out."""
    from app.services import inference_loop as mod

    def make(store_ids=("goggles", "no_goggles"), names=None):
        store = {
            m: StoreModelInfo(model_id=m, version="1.0.0", display_name=m,
                              min_confidence=0.7)
            for m in store_ids
        }
        monkeypatch.setattr(mod, "enabled_store_models", lambda: store)
        loop = _Loop({DEVICE: "75096"} if names is None else names)
        return lambda model_id, device_id=DEVICE, config=None: (
            mod.InferenceLoopService._request_config(loop, model_id, device_id, config)
        )

    return make


# ---------------------------------------------------------------------------
# What it adds
# ---------------------------------------------------------------------------


def test_store_model_gets_the_camera_name(request_config):
    rc = request_config()
    assert rc("goggles") == {"camera_name": "75096"}


def test_existing_config_is_merged_not_replaced(request_config):
    """`config` is also where zones live. Losing them would silently stop
    every zone-gated rule from firing."""
    rc = request_config()
    zones = {"zones": [{"id": "z1", "type": "restricted", "points": [[0, 0]]}]}
    out = rc("goggles", config=zones)
    assert out["zones"] == zones["zones"]
    assert out["camera_name"] == "75096"


def test_the_stored_config_object_is_not_mutated(request_config):
    """The entry dict belongs to the session; writing through it would
    persist the derived label, which is the thing this avoids."""
    rc = request_config()
    original = {"zones": []}
    rc("goggles", config=original)
    assert original == {"zones": []}


def test_an_explicit_camera_name_wins(request_config):
    rc = request_config()
    assert rc("goggles", config={"camera_name": "override"})["camera_name"] == "override"


# ---------------------------------------------------------------------------
# What it must leave alone
# ---------------------------------------------------------------------------


def test_builtin_model_config_is_untouched(request_config):
    """Built-ins receive config and ignore it; sending them something new
    is risk without benefit."""
    rc = request_config()
    assert rc("ppe_detection") is None
    assert rc("fall_detection", config={"zones": []}) == {"zones": []}


def test_unknown_device_passes_config_through(request_config):
    """A device missing from the cache must behave exactly as before,
    not send an empty or placeholder name."""
    rc = request_config()
    assert rc("goggles", device_id=OTHER) is None
    assert rc("goggles", device_id=OTHER, config={"zones": []}) == {"zones": []}


def test_empty_device_name_is_treated_as_unknown(request_config):
    rc = request_config(names={DEVICE: ""})
    assert rc("goggles") is None


# ---------------------------------------------------------------------------
# Renames
# ---------------------------------------------------------------------------


def test_a_rename_is_picked_up(request_config):
    """_main_loop refreshes the cache every pass, so the label follows the
    device rather than needing a restart."""
    names = {DEVICE: "75096"}
    rc = request_config(names=names)
    assert rc("goggles")["camera_name"] == "75096"
    names[DEVICE] = "75096-renamed"
    assert rc("goggles")["camera_name"] == "75096-renamed"


# ---------------------------------------------------------------------------
# Both call sites
# ---------------------------------------------------------------------------


def test_both_inference_paths_use_the_helper():
    """The legacy single-model path and the multi-model path must agree.

    Asserted against the source because the two call sites are far apart
    and a future edit to one is easy to miss.
    """
    import inspect

    from app.services import inference_loop as mod

    src = inspect.getsource(mod)
    assert src.count("config=self._request_config(") == 2
    # and nothing bypasses it
    assert "config=entry.get(\"config\")" not in src
