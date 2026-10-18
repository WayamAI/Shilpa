"""Offscreen PNG renders of a placed assembly with no GPU or OpenGL (Pillow only).

Each placed solid is tessellated, projected orthographically, flat-shaded
(Lambert, two-sided, plus ambient) and painted far-to-near at twice the output
size, then downsampled for anti-aliasing. Painter's ordering by triangle depth
is exact for a mesh this fine except where long triangles interpenetrate, which
shows as small speckles on touching parts; it is a review image, not a
marketing render.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw

from ..assembly.build import AssemblyBuild

VIEWS = {
    # name: (azimuth deg from the drive side (-Y) toward the front, elevation deg)
    "side": (0.0, 0.0),
    "three_quarter": (35.0, 18.0),
    "front": (90.0, 8.0),
}


def _camera(azimuth: float, elevation: float) -> np.ndarray:
    """Rows: screen right, screen up, toward the viewer (world coordinates)."""
    az, el = math.radians(azimuth), math.radians(elevation)
    toward = np.array([math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)])
    up0 = np.array([0.0, 0.0, 1.0])
    right = np.cross(up0, toward)
    right /= np.linalg.norm(right)
    up = np.cross(toward, right)
    return np.vstack([right, up, toward])


def _mesh(shape, tol: float) -> tuple[np.ndarray, np.ndarray]:
    try:
        verts, tris = shape.tessellate(tol, 0.35)
    except AttributeError:  # a face OCCT could not triangulate: mesh face by face and skip it
        verts, tris = [], []
        for f in shape.faces():
            try:
                fv, ft = f.tessellate(tol, 0.35)
            except AttributeError:
                continue
            tris += [(a + len(verts), b + len(verts), c + len(verts)) for a, b, c in ft]
            verts += fv
    if not tris:
        return np.zeros((0, 3)), np.zeros((0, 3), int)
    return np.array([tuple(v) for v in verts], float), np.array(tris, int)


def render(build: AssemblyBuild, path: str | Path, view: str = "three_quarter", size: tuple[int, int] = (1600, 1000),
           title: str | None = None, ground_z: float | None = None, tol: float = 0.4, hidden: tuple[str, ...] = ()) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    R = _camera(*VIEWS[view])
    light = R.T @ np.array([-0.35, 0.55, 0.75])
    light /= np.linalg.norm(light)
    polys, depth, cols = [], [], []
    for iid, shape in build.placed.items():
        if iid in hidden:
            continue
        v, t = _mesh(shape, tol)
        if not len(t):
            continue
        inst = build.spec.instance(iid)
        rgb = np.array(ImageColor.getrgb(inst.color or "#8a8a8a"), float)
        cam = v @ R.T
        tri = cam[t]  # (n, 3, 3)
        n = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
        norm = np.linalg.norm(n, axis=1)
        keep = norm > 1e-12
        n[keep] /= norm[keep, None]
        lam = np.abs(n @ light)  # two-sided
        shade = 0.38 + 0.62 * lam
        polys.append(tri[:, :, :2])
        depth.append(tri[:, :, 2].mean(axis=1))
        cols.append(np.clip(rgb[None, :] * shade[:, None] + 18.0 * lam[:, None] ** 8, 0, 255))
    P = np.concatenate(polys)
    D = np.concatenate(depth)
    C = np.concatenate(cols).astype(np.uint8)

    W, H = size[0] * 2, size[1] * 2
    lo, hi = P.reshape(-1, 2).min(axis=0), P.reshape(-1, 2).max(axis=0)
    if ground_z is not None and view == "side":
        lo[1] = min(lo[1], ground_z)
    margin = 0.07
    scale = min(W * (1 - 2 * margin) / (hi[0] - lo[0]), H * (1 - 2 * margin) / (hi[1] - lo[1]))
    off = np.array([W / 2, H / 2]) - scale * (lo + hi) / 2
    S = P * scale + off
    S[:, :, 1] = H - S[:, :, 1]

    img = Image.new("RGB", (W, H), (246, 246, 244))
    draw = ImageDraw.Draw(img)
    if ground_z is not None:
        # Ground line (side view) or a soft floor band under the lowest point.
        gy = H - (ground_z * scale + off[1]) if view == "side" else None
        if gy is not None:
            draw.rectangle([0, gy, W, H], fill=(232, 232, 228))
            draw.line([0, gy, W, gy], fill=(150, 150, 145), width=3)
    for k in np.argsort(D):  # far to near (camera z points toward the viewer)
        tri = S[k]
        c = tuple(int(x) for x in C[k])
        draw.polygon([tuple(tri[0]), tuple(tri[1]), tuple(tri[2])], fill=c, outline=c)
    img = img.resize(size, Image.LANCZOS)
    if title:
        ImageDraw.Draw(img).text((18, 14), title, fill=(40, 40, 40))
    img.save(path)
    return path
