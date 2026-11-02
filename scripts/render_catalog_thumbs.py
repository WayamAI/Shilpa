"""Render one isometric thumbnail per listed catalog generator (default params).

Offline and deterministic: builds each part with build123d, tessellates it, and
rasterises it with a small painter's-algorithm renderer (numpy + Pillow, both
already project dependencies; no GPU, no extra packages). Output is a
transparent 480x400 WebP per generator in apps/web/public/thumbs/catalog/.

    uv run python scripts/render_catalog_thumbs.py            # all generators
    uv run python scripts/render_catalog_thumbs.py screw.button_head nut.hex
"""

from __future__ import annotations

import base64
import sys
import time
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "apps" / "web" / "public" / "thumbs" / "catalog"

W, H, SS = 480, 400, 3          # output size and supersampling factor
PAD = 0.9                       # fraction of the canvas the part may fill
BASE = np.array([0xD9, 0xD9, 0xE0], dtype=float)
EDGE = (0x5E, 0x63, 0x70)
FEATURE_DEG = 32.0              # dihedral angle above which an edge is drawn


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


def write_manifest() -> None:
    """index.json lists the generators that have a thumbnail; the library reads it."""
    import json

    names = sorted(p.stem for p in OUT.glob("*.webp"))
    (OUT / "index.json").write_text(json.dumps(names, indent=0) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    from shilpa.catalog.preview import browse, preview

    names = argv or [g["name"] for g in browse()["generators"]]
    OUT.mkdir(parents=True, exist_ok=True)
    done, failed = 0, []
    for name in names:
        t0 = time.perf_counter()
        try:
            verts, faces = decode(preview(name, {})["mesh"])
            if len(faces) == 0:
                raise ValueError("empty mesh")
            render(verts, faces).save(OUT / f"{name}.webp", "WEBP", quality=88, method=6)
            done += 1
            print(f"ok   {name}  {len(faces)} tris  {time.perf_counter() - t0:.1f}s")
        except Exception as e:  # keep going; the library falls back to the icon
            failed.append((name, f"{type(e).__name__}: {e}"))
            print(f"FAIL {name}  {type(e).__name__}: {e}")
    write_manifest()
    print(f"\n{done} rendered, {len(failed)} failed -> {OUT}")
    for n, why in failed:
        print(f"  {n}: {why}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
