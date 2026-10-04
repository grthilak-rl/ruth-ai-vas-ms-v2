"""Manifests of the store models installed for the store runtime.

The store runtime loads ``<store root>/enabled/<model_id>/<version>/``; each
version dir carries the ``store_manifest.json`` its plugin runs from. The
backend reads the same files for what the camera picker and the add-model
API need to know about a store model (display name, zone-required rules,
whether it reports PPE). Reading only; nothing here writes the store.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

from app.core.logging import get_logger
from app.models.enums import VIOLATION_TYPE_MAP, ViolationType
from app.services.model_store import ModelStoreSettings

logger = get_logger(__name__)

MANIFEST_FILENAME = "store_manifest.json"
CACHE_SECONDS = 30.0


@dataclass(frozen=True)
class StoreModelInfo:
    model_id: str
    version: str
    display_name: str
    #: ids of rules that only fire inside a zone of their type
    zone_required_rules: Tuple[str, ...] = field(default_factory=tuple)
    #: every violation rule needs a zone: the model can do nothing without one
    all_rules_need_zone: bool = False
    #: reports missing PPE, like the built-in ppe_detection
    reports_ppe: bool = False


def _version_key(name: str) -> Tuple[int, ...]:
    try:
        return tuple(int(p) for p in name.split("."))
    except ValueError:
        return (-1,)


def _info_from_manifest(model_id: str, version: str, manifest: dict) -> StoreModelInfo:
    rules = [r for r in manifest.get("rules", []) if isinstance(r, dict)]
    zone_rules = tuple(str(r.get("id")) for r in rules if r.get("requires_zone"))
    reports_ppe = any(
        VIOLATION_TYPE_MAP.get(str(r.get("violation_type", "")).strip().lower())
        == ViolationType.PPE_VIOLATION
        for r in rules
    )
    return StoreModelInfo(
        model_id=model_id,
        version=version,
        display_name=str(manifest.get("display_name") or model_id),
        zone_required_rules=zone_rules,
        all_rules_need_zone=bool(rules) and len(zone_rules) == len(rules),
        reports_ppe=reports_ppe,
    )


def read_enabled_models(enabled_root: Path) -> Dict[str, StoreModelInfo]:
    """Every installed store model's newest version, by model_id."""
    out: Dict[str, StoreModelInfo] = {}
    if not enabled_root.is_dir():
        return out
    for model_dir in sorted(p for p in enabled_root.iterdir() if p.is_dir()):
        versions = sorted(
            (v for v in model_dir.iterdir() if (v / MANIFEST_FILENAME).is_file()),
            key=lambda v: _version_key(v.name),
        )
        if not versions:
            continue
        newest = versions[-1]
        try:
            manifest = json.loads((newest / MANIFEST_FILENAME).read_text())
        except (OSError, ValueError) as exc:
            logger.warning("Unreadable store manifest", path=str(newest), error=str(exc))
            continue
        out[model_dir.name] = _info_from_manifest(model_dir.name, newest.name, manifest)
    return out


_cache: Optional[Tuple[float, Dict[str, StoreModelInfo]]] = None


def enabled_store_models() -> Dict[str, StoreModelInfo]:
    """Installed store models (cached briefly; a missing store gives {})."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    root = Path(ModelStoreSettings().model_store_root) / "enabled"
    try:
        models = read_enabled_models(root)
    except OSError as exc:
        logger.warning("Model store not readable", path=str(root), error=str(exc))
        models = {}
    _cache = (now, models)
    return models
