"""Filesystem side of the model store.

Layout under MODEL_STORE_ROOT (host: /mnt/storage/ruth-models, backend: /store):

    staging/<upload_id>/data.part        sparse file, chunks written at offset
    staging/<upload_id>/chunks/<n>       marker: chunk n is durably written
    drafts/<model_pk>/weights/<file>.pt  completed uploads
    enabled/  disabled/  state/          reserved for Step 5 (store runtime)
    trash/<model_id>__<model_pk>__<ts>/  deleted drafts

Drafts are keyed by the immutable row id, not model_id, so editing model_id
before the first Apply never moves files. Everything lives on one filesystem,
so promotion from staging and moves to trash are atomic renames.

All functions here are blocking; callers run them via asyncio.to_thread.
"""

import hashlib
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

LAYOUT_DIRS = ("staging", "drafts", "enabled", "disabled", "state", "trash")
HASH_BLOCK = 8 * 1024 * 1024


class StoreUnavailableError(Exception):
    """The store root is missing or not writable by this process."""


@dataclass(frozen=True)
class ModelStore:
    root: Path

    # --- layout -------------------------------------------------------------

    def ensure_layout(self) -> None:
        if not self.root.is_dir():
            raise StoreUnavailableError(f"{self.root} does not exist")
        if not os.access(self.root, os.W_OK | os.X_OK):
            raise StoreUnavailableError(f"{self.root} is not writable")
        for name in LAYOUT_DIRS:
            (self.root / name).mkdir(mode=0o750, exist_ok=True)

    def free_bytes(self) -> int:
        return shutil.disk_usage(self.root).free

    def relative(self, path: Path) -> str:
        return str(path.relative_to(self.root))

    # --- staging ------------------------------------------------------------

    def staging_dir(self, upload_id: UUID) -> Path:
        return self.root / "staging" / str(upload_id)

    def data_path(self, upload_id: UUID) -> Path:
        return self.staging_dir(upload_id) / "data.part"

    def create_staging(self, upload_id: UUID, size_bytes: int) -> None:
        """Create the staging dir and a sparse data file of the final size."""
        directory = self.staging_dir(upload_id)
        (directory / "chunks").mkdir(parents=True, exist_ok=True)
        with open(directory / "data.part", "ab") as f:
            f.truncate(size_bytes)

    def write_chunk(self, upload_id: UUID, index: int, offset: int, data: bytes) -> None:
        """Write one chunk at its offset, fsync, then drop its marker.

        Idempotent: a retried chunk rewrites the same bytes and marker. The
        marker is only created after the data is on disk, so a crash between
        the two just means the chunk is re-sent.
        """
        fd = os.open(self.data_path(upload_id), os.O_WRONLY)
        try:
            written = 0
            while written < len(data):
                written += os.pwrite(fd, data[written:], offset + written)
            os.fsync(fd)
        finally:
            os.close(fd)
        marker = self.staging_dir(upload_id) / "chunks" / str(index)
        marker.touch()

    def received_chunks(self, upload_id: UUID) -> list[int]:
        chunk_dir = self.staging_dir(upload_id) / "chunks"
        try:
            names = os.listdir(chunk_dir)
        except FileNotFoundError:
            return []
        return sorted(int(n) for n in names if n.isdigit())

    def sha256_of_data(self, upload_id: UUID) -> tuple[str, int]:
        """(hex sha256, size) of the assembled data file."""
        digest = hashlib.sha256()
        size = 0
        with open(self.data_path(upload_id), "rb") as f:
            while block := f.read(HASH_BLOCK):
                digest.update(block)
                size += len(block)
        return digest.hexdigest(), size

    def remove_staging(self, upload_id: UUID) -> None:
        shutil.rmtree(self.staging_dir(upload_id), ignore_errors=True)

    def staging_entries(self) -> list[tuple[str, float]]:
        """(name, mtime) of every entry in staging/."""
        entries = []
        with os.scandir(self.root / "staging") as it:
            for entry in it:
                try:
                    entries.append((entry.name, entry.stat().st_mtime))
                except FileNotFoundError:
                    continue
        return entries

    def remove_staging_entry(self, name: str) -> None:
        target = self.root / "staging" / name
        if target.parent != self.root / "staging":
            return
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)

    # --- drafts -------------------------------------------------------------

    def draft_dir(self, model_pk: UUID) -> Path:
        return self.root / "drafts" / str(model_pk)

    def weights_path(self, model_pk: UUID, filename: str) -> Path:
        return self.draft_dir(model_pk) / "weights" / filename

    def promote(self, upload_id: UUID, model_pk: UUID, filename: str) -> Path:
        """Atomically move a completed upload into the draft's weights dir."""
        destination = self.weights_path(model_pk, filename)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(self.data_path(upload_id), destination)
        os.chmod(destination, 0o640)
        return destination

    def delete_weights(self, relative_path: str) -> None:
        path = (self.root / relative_path).resolve()
        if self.root.resolve() in path.parents:
            path.unlink(missing_ok=True)

    def trash_draft(self, model_pk: UUID, model_id: str) -> str | None:
        """Move a draft dir to trash/. Returns its relative trash path."""
        source = self.draft_dir(model_pk)
        if not source.exists():
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = self.root / "trash" / f"{model_id}__{model_pk}__{stamp}"
        os.replace(source, destination)
        return self.relative(destination)


def file_age_seconds(mtime: float) -> float:
    return time.time() - mtime
