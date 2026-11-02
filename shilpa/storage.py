"""Artifact storage (blueprint section 16). Local filesystem by default, Azure Blob Storage when
SHILPA_BLOB_BACKEND=azure. Both stores share one interface (see ``LocalBlobStore``).

Key layout follows the blueprint:
  tenants/{tenant}/projects/{project}/jobs/{job}/attempts/{n}/...   (staging)
  tenants/{tenant}/projects/{project}/versions/{version}/...        (committed)
A prefix is a naming convention, not an access boundary: downloads are authorised
against database ownership in the API.

Publication stays atomic in spirit on both backends: a worker builds into a local scratch directory,
``push_dir`` uploads it under the *staging* prefix, then the version prefix is filled with server-side
copies, and only then are the database rows (version, artifacts) committed. Blobs under a version prefix
without rows are invisible and can be swept; rows never point at missing blobs.
"""

from __future__ import annotations

import mimetypes
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator

from .settings import cloud, settings


def _safe(key: str) -> PurePosixPath:
    p = PurePosixPath(key)
    if p.is_absolute() or any(part in ("..", "") for part in p.parts):
        raise ValueError(f"unsafe blob key {key!r}")
    return p


class _Prefixes:
    def staging_prefix(self, tenant: str, project: str, job: str, attempt: int) -> str:
        return f"tenants/{tenant}/projects/{project}/jobs/{job}/attempts/{attempt}"

    def version_prefix(self, tenant: str, project: str, version: str) -> str:
        return f"tenants/{tenant}/projects/{project}/versions/{version}"


class LocalBlobStore(_Prefixes):
    """Blobs are files under ``root``. ``path`` exists only here: code that must work on both backends uses
    read_bytes/write_bytes/stream/workdir/view/push_dir instead."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        return self.root.joinpath(*_safe(key).parts)

    def local_path(self, key: str) -> Path | None:
        """A real file for this key, or None when the bytes are not on this machine's disk."""
        p = self.path(key)
        return p if p.is_file() else None

    def ping(self) -> None:
        if not self.root.is_dir():
            raise FileNotFoundError("blob root is missing")

    def copy(self, src_key: str, dst_key: str) -> None:
        dst = self.path(dst_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.path(src_key), dst)

    def exists(self, key: str) -> bool:
        return self.path(key).exists()

    def size(self, key: str) -> int:
        return self.path(key).stat().st_size

    def read_bytes(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def write_bytes(self, key: str, data: bytes) -> None:
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def stream(self, key: str, chunk: int = 1 << 20) -> Iterator[bytes]:
        with self.path(key).open("rb") as f:
            while block := f.read(chunk):
                yield block

    def delete_prefix(self, prefix: str) -> None:
        shutil.rmtree(self.path(prefix), ignore_errors=True)

    # -- local working directories ---------------------------------------------------------------
    @contextmanager
    def workdir(self, prefix: str) -> Iterator[Path]:
        """A directory to build files in for ``prefix``. Locally that is the blob directory itself."""
        d = self.path(prefix)
        d.mkdir(parents=True, exist_ok=True)
        yield d

    @contextmanager
    def view(self, prefix: str) -> Iterator[Path]:
        """A read-only local directory holding the blobs under ``prefix``."""
        yield self.path(prefix)

    def push_dir(self, local_dir: Path, prefix: str) -> None:
        """Make the files in ``local_dir`` the blobs under ``prefix`` (a no-op when it already is that directory)."""
        dst = self.path(prefix)
        if Path(local_dir).resolve() == dst.resolve():
            return
        shutil.copytree(local_dir, dst, dirs_exist_ok=True)


class AzureBlobStore(_Prefixes):
    """Azure Blob Storage through the account URL with DefaultAzureCredential (managed identity); no account keys.
    A connection string is accepted only for Azurite. ``service`` can be injected (tests)."""

    def __init__(self, account_url: str = "", container: str = "artifacts", *, connection_string: str = "",
                 credential=None, service=None, workdir: str = ""):
        self.container_name = container
        self._account_url, self._conn, self._credential, self._service = account_url, connection_string, credential, service
        self._workdir_root = workdir or None
        self._ready = service is not None

    # -- clients -----------------------------------------------------------------------------------
    @property
    def container(self):
        if self._service is None:
            from azure.storage.blob import BlobServiceClient

            if self._conn:
                self._service = BlobServiceClient.from_connection_string(self._conn)
            else:
                if not self._account_url:
                    raise RuntimeError("SHILPA_BLOB_ACCOUNT_URL is required when SHILPA_BLOB_BACKEND=azure")
                from azure.identity import DefaultAzureCredential

                self._service = BlobServiceClient(self._account_url, credential=self._credential or DefaultAzureCredential())
        c = self._service.get_container_client(self.container_name)
        if self._conn and not self._ready:  # emulator: create the container on first use; Azure's is infrastructure
            from azure.core.exceptions import ResourceExistsError

            try:
                c.create_container()
            except ResourceExistsError:
                pass
            self._ready = True
        return c

    def _blob(self, key: str):
        return self.container.get_blob_client(_safe(key).as_posix())

    # -- interface -----------------------------------------------------------------------------------
    def local_path(self, key: str) -> Path | None:
        return None

    def ping(self) -> None:
        """Readiness probe: the container must exist and be reachable with the current identity."""
        self.container.get_container_properties()

    def exists(self, key: str) -> bool:
        return self._blob(key).exists()

    def size(self, key: str) -> int:
        return int(self._blob(key).get_blob_properties().size)

    def read_bytes(self, key: str) -> bytes:
        return self._blob(key).download_blob().readall()

    def write_bytes(self, key: str, data: bytes) -> None:
        from azure.storage.blob import ContentSettings

        ctype = mimetypes.guess_type(key)[0] or "application/octet-stream"
        self._blob(key).upload_blob(data, overwrite=True, content_settings=ContentSettings(content_type=ctype))

    def stream(self, key: str, chunk: int = 1 << 20) -> Iterator[bytes]:
        yield from self._blob(key).download_blob().chunks()

    def copy(self, src_key: str, dst_key: str) -> None:
        """Server-side copy inside the account; falls back to download and upload if the service does not finish it at once."""
        src, dst = self._blob(src_key), self._blob(dst_key)
        props = dst.start_copy_from_url(src.url)
        status = props.get("copy_status")
        deadline = time.monotonic() + 60
        while status == "pending" and time.monotonic() < deadline:
            time.sleep(0.2)
            status = dst.get_blob_properties().copy.status
        if status != "success":
            if status == "pending":
                dst.abort_copy(props["copy_id"])
            self.write_bytes(dst_key, self.read_bytes(src_key))

    def delete_prefix(self, prefix: str) -> None:
        base = _safe(prefix).as_posix().rstrip("/") + "/"
        for b in list(self.container.list_blobs(name_starts_with=base)):
            self.container.delete_blob(b.name)

    # -- local working directories ---------------------------------------------------------------
    @contextmanager
    def workdir(self, prefix: str) -> Iterator[Path]:
        """A scratch directory deleted on exit; nothing reaches the store until ``push_dir``."""
        with tempfile.TemporaryDirectory(prefix="shilpa-work-", dir=self._workdir_root) as tmp:
            d = Path(tmp) / "out"
            d.mkdir()
            yield d

    @contextmanager
    def view(self, prefix: str) -> Iterator[Path]:
        with tempfile.TemporaryDirectory(prefix="shilpa-view-", dir=self._workdir_root) as tmp:
            d = Path(tmp) / "in"
            d.mkdir()
            base = _safe(prefix).as_posix().rstrip("/") + "/"
            for b in self.container.list_blobs(name_starts_with=base):
                rel = PurePosixPath(b.name[len(base):])
                if not rel.parts or any(part in ("..", "") for part in rel.parts):
                    continue
                target = d.joinpath(*rel.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as f:
                    self.container.get_blob_client(b.name).download_blob().readinto(f)
            yield d

    def push_dir(self, local_dir: Path, prefix: str) -> None:
        base = _safe(prefix).as_posix().rstrip("/")
        for f in sorted(Path(local_dir).rglob("*")):
            if f.is_file():
                rel = f.relative_to(local_dir).as_posix()
                self.write_bytes(f"{base}/{rel}", f.read_bytes())


def make_store() -> LocalBlobStore | AzureBlobStore:
    backend = cloud.blob_backend
    if backend == "local":
        return LocalBlobStore(settings.blob_root)
    if backend == "azure":
        return AzureBlobStore(cloud.blob_account_url, cloud.blob_container, connection_string=cloud.blob_connection_string,
                              workdir=cloud.blob_workdir)
    raise RuntimeError(f"SHILPA_BLOB_BACKEND={backend!r} is not valid (local | azure)")


blobs = make_store()
