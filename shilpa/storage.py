"""Artifact storage (blueprint section 16). Local filesystem now, Azure Blob later.

Key layout follows the blueprint:
  tenants/{tenant}/projects/{project}/jobs/{job}/attempts/{n}/...   (staging)
  tenants/{tenant}/projects/{project}/versions/{version}/...        (committed)
A prefix is a naming convention, not an access boundary: downloads are authorised
against database ownership in the API.
"""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath

from .settings import settings


def _safe(key: str) -> PurePosixPath:
    p = PurePosixPath(key)
    if p.is_absolute() or any(part in ("..", "") for part in p.parts):
        raise ValueError(f"unsafe blob key {key!r}")
    return p


class LocalBlobStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        return self.root.joinpath(*_safe(key).parts)

    def staging_prefix(self, tenant: str, project: str, job: str, attempt: int) -> str:
        return f"tenants/{tenant}/projects/{project}/jobs/{job}/attempts/{attempt}"

    def version_prefix(self, tenant: str, project: str, version: str) -> str:
        return f"tenants/{tenant}/projects/{project}/versions/{version}"

    def copy(self, src_key: str, dst_key: str) -> None:
        dst = self.path(dst_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.path(src_key), dst)

    def exists(self, key: str) -> bool:
        return self.path(key).exists()

    def delete_prefix(self, prefix: str) -> None:
        shutil.rmtree(self.path(prefix), ignore_errors=True)


blobs = LocalBlobStore(settings.blob_root)
