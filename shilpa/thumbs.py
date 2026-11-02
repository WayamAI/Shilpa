"""Headless isometric thumbnails of a model version (numpy + Pillow + trimesh only).

One painter's-algorithm renderer shared by the CAD worker (a THUMB artifact is
published with every version), the offline scripts and the backfill command:

    uv run python -m shilpa.thumbs backfill [--force]

Output is a transparent 480x400 WebP: grey faces (#D9D9E0) with feature edges (#5E6370).
``render_dir`` never raises: it returns None (and logs) when no thumbnail can be made.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

log = logging.getLogger("shilpa.thumbs")

W, H, SS = 480, 400, 3          # output size and supersampling factor
PAD = 0.9                       # fraction of the canvas the part may fill
BASE = np.array([0xD9, 0xD9, 0xE0], dtype=float)
EDGE = (0x5E, 0x63, 0x70)
FEATURE_DEG = 32.0              # dihedral angle above which an edge is drawn
MAX_FACES = 150_000             # beyond this the pure-python painter is no longer cheap: skip the thumb
THUMB_FILE = "thumb.webp"


def _view() -> np.ndarray:
    """World (Z up) to camera rows [right, up, toward-viewer]: 45 deg turn, 35.264 deg tilt."""
    az, el = np.radians(45.0), np.radians(35.264)
    rz = np.array([[np.cos(az), -np.sin(az), 0], [np.sin(az), np.cos(az), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, np.sin(el), np.cos(el)], [0, -np.cos(el), np.sin(el)]])
    return rx @ rz


def decode(mesh: dict) -> tuple[np.ndarray, np.ndarray]:
    v = np.frombuffer(base64.b64decode(mesh["positions"]), dtype=np.float32).reshape(-1, 3).astype(float)
    f = np.frombuffer(base64.b64decode(mesh["indices"]), dtype=np.uint32).reshape(-1, 3).astype(np.int64)
    return v, f


def render(verts: np.ndarray, faces: np.ndarray) -> Image.Image:
    tm = trimesh.Trimesh(verts, faces, process=True)  # merges split vertices so adjacency works
    verts, faces = tm.vertices, tm.faces
    R = _view()
    cam = (verts - verts.mean(axis=0)) @ R.T           # x right, y up, z toward viewer
    lo, hi = cam[:, :2].min(axis=0), cam[:, :2].max(axis=0)
    scale = SS * min(W * PAD / max(hi[0] - lo[0], 1e-9), H * PAD / max(hi[1] - lo[1], 1e-9))
    mid = (lo + hi) / 2
    px = np.column_stack([W * SS / 2 + (cam[:, 0] - mid[0]) * scale, H * SS / 2 - (cam[:, 1] - mid[1]) * scale])

    normals = tm.face_normals @ R.T
    front = normals[:, 2] > 1e-6
    light = np.array([-0.45, 0.65, 0.62])
    light /= np.linalg.norm(light)
    shade = 0.58 + 0.42 * np.clip(normals @ light, 0, 1)
    depth = cam[faces][:, :, 2].mean(axis=1)

    # Feature edges: dihedral angle above threshold, plus open (boundary) edges.
    feat: dict[int, list[tuple[int, int]]] = {}
    adj, edges = tm.face_adjacency, tm.face_adjacency_edges
    angle = np.degrees(tm.face_adjacency_angles)
    for (a, b), e, ang in zip(adj, edges, angle):
        if ang > FEATURE_DEG:
            for fi in (a, b):
                if front[fi]:
                    feat.setdefault(int(fi), []).append((int(e[0]), int(e[1])))
    # Silhouette edges (one side facing the camera, one away) always get a line.
    for (a, b), e in zip(adj, edges):
        if front[a] != front[b]:
            fi = int(a if front[a] else b)
            feat.setdefault(fi, []).append((int(e[0]), int(e[1])))

    img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lw = max(1, round(SS * 0.9))
    for fi in np.argsort(depth):                         # far to near
        if not front[fi]:
            continue
        col = tuple(int(c) for c in np.clip(BASE * shade[fi], 0, 255)) + (255,)
        tri = [tuple(px[i]) for i in faces[fi]]
        d.polygon(tri, fill=col)
        for i, j in feat.get(int(fi), ()):
            d.line([tuple(px[i]), tuple(px[j])], fill=EDGE + (255,), width=lw)
    return img.resize((W, H), Image.LANCZOS)


def to_webp(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=88, method=6)
    return buf.getvalue()


# ------------------------------------------------------------------ meshes of a version

def part_mesh(stl: bytes) -> tuple[np.ndarray, np.ndarray]:
    m = trimesh.load(io.BytesIO(stl), file_type="stl")
    return np.asarray(m.vertices, dtype=float), np.asarray(m.faces, dtype=np.int64)


def assembly_mesh(meshes: bytes, viewer: dict) -> tuple[np.ndarray, np.ndarray]:
    """All placed instances of a MESHES artifact in one mesh, positioned by viewer.instances."""
    parts = json.loads(meshes)["parts"]
    vs, fs, base = [], [], 0
    for inst in viewer.get("instances") or []:
        key = inst.get("mesh")
        if not key or key not in parts or inst.get("error") or inst.get("placed") is False:
            continue
        v, f = decode(parts[key])
        if inst.get("matrix"):
            m = np.array(inst["matrix"], dtype=float)  # row-major part-to-world
            v = v @ m[:3, :3].T + m[:3, 3]
        vs.append(v)
        fs.append(f + base)
        base += len(v)
    if not vs:
        raise ValueError("no placed instances with geometry")
    return np.vstack(vs), np.vstack(fs)


def mesh_from_dir(d: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read the mesh of a staged or committed version directory (file names are shared by every job kind)."""
    d = Path(d)
    if (d / "meshes.json").exists() and (d / "viewer.json").exists():
        return assembly_mesh((d / "meshes.json").read_bytes(), json.loads((d / "viewer.json").read_text(encoding="utf-8")))
    if (d / "model.stl").exists():
        return part_mesh((d / "model.stl").read_bytes())
    raise ValueError("no STL or MESHES artifact")


def render_dir(d: Path) -> bytes | None:
    """WebP bytes for the version files in ``d``, or None (logged) if it cannot be rendered cheaply."""
    try:
        verts, faces = mesh_from_dir(d)
        if len(faces) == 0:
            raise ValueError("empty mesh")
        if len(faces) > MAX_FACES:
            raise ValueError(f"{len(faces)} triangles exceeds the thumbnail budget")
        return to_webp(render(verts, faces))
    except Exception as e:
        log.warning("thumbnail skipped for %s: %s: %s", d, type(e).__name__, e)
        return None


def write_thumb(d: Path) -> Path | None:
    """Render into ``d/thumb.webp``; None when no thumbnail could be made."""
    data = render_dir(d)
    if data is None:
        return None
    out = Path(d) / THUMB_FILE
    out.write_bytes(data)
    return out


# ------------------------------------------------------------------ backfill

def backfill(force: bool = False) -> tuple[int, int]:
    """Render THUMB for every model's head version that lacks one. Returns (rendered, skipped)."""
    from sqlalchemy import select

    from .db import Artifact, Model, init_db, tx
    from .storage import blobs

    init_db()
    with tx() as s:
        todo = []
        for m in s.scalars(select(Model).where(Model.head_version_id.is_not(None))).all():
            have = s.scalars(select(Artifact).where(Artifact.version_id == m.head_version_id, Artifact.format == "THUMB")).first()
            if have is None or force:
                todo.append((m.id, m.tenant_id, m.project_id, m.head_version_id, have.id if have else None))
    done = skipped = 0
    for model_id, tenant, project, version, existing in todo:
        prefix = blobs.version_prefix(tenant, project, version)
        out = write_thumb(blobs.path(prefix))
        if out is None:
            skipped += 1
            print(f"skip {model_id} version={version}")
            continue
        data = out.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        with tx() as s:
            art = s.get(Artifact, existing) if existing else None
            if art is None:
                s.add(Artifact(tenant_id=tenant, version_id=version, format="THUMB", blob_key=f"{prefix}/{THUMB_FILE}",
                               sha256=sha, bytes=len(data)))
            else:
                art.sha256, art.bytes = sha, len(data)
        done += 1
        print(f"ok   {model_id} version={version}")
    print(f"{done} rendered, {skipped} skipped")
    return done, skipped


def main(argv: list[str]) -> int:
    if argv[:1] == ["backfill"]:
        backfill(force="--force" in argv)
        return 0
    print("usage: python -m shilpa.thumbs backfill [--force]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
