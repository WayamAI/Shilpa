"""Render one isometric thumbnail per project model's head version, via the API.

Reads every model visible to the caller, fetches the head version's geometry
(STL for parts, the MESHES + VIEWER artifacts for assemblies, products and
sheet metal, all instances placed in one image), and renders it with the same
renderer as the catalog thumbnails. Files are named <model_id>-v<head_number>.webp
so a newer version without a render falls back to the icon instead of a stale image.

    uv run python scripts/render_model_thumbs.py
    API=http://127.0.0.1:8010 TOKEN=dev:dev@wayam.local uv run python scripts/render_model_thumbs.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_catalog_thumbs import ROOT, decode, render  # noqa: E402

OUT = ROOT / "apps" / "web" / "public" / "thumbs" / "models"
API = os.environ.get("API", "http://127.0.0.1:8010").rstrip("/")
TOKEN = os.environ.get("TOKEN", "dev:dev@wayam.local")


def get(path: str, raw: bool = False):
    req = urllib.request.Request(API + path, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read()
    return body if raw else json.loads(body)


def artifact(version: dict, fmt: str) -> bytes | None:
    a = next((a for a in version["artifacts"] if a["format"] == fmt), None)
    return get(f"/v1/artifacts/{a['id']}/download", raw=True) if a else None


def part_mesh(version: dict) -> tuple[np.ndarray, np.ndarray]:
    stl = artifact(version, "STL")
    if stl is None:
        raise ValueError("no STL artifact")
    m = trimesh.load(io.BytesIO(stl), file_type="stl")
    return np.asarray(m.vertices, dtype=float), np.asarray(m.faces, dtype=np.int64)


def assembly_mesh(version: dict) -> tuple[np.ndarray, np.ndarray]:
    raw = artifact(version, "MESHES")
    viewer = version.get("viewer")
    if raw is None or not viewer:
        raise ValueError("no MESHES artifact or viewer instances")
    parts = json.loads(raw)["parts"]
    vs, fs, base = [], [], 0
    for inst in viewer["instances"]:
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


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    done, failed = 0, []
    for p in get("/v1/projects"):
        if not p["model_count"]:
            continue
        for m in get(f"/v1/projects/{p['id']}")["models"]:
            name = f"{m['id']}-v{m['head_number']}"
            try:
                if not m["head_version_id"]:
                    raise ValueError("no head version")
                version = get(f"/v1/versions/{m['head_version_id']}")
                verts, faces = (part_mesh if m["kind"] == "part" else assembly_mesh)(version)
                if len(faces) == 0:
                    raise ValueError("empty mesh")
                render(verts, faces).save(OUT / f"{name}.webp", "WEBP", quality=88, method=6)
                done += 1
                print(f"ok   {name}  {m['kind']}  {len(faces)} tris")
            except Exception as e:  # keep going; the library falls back to the icon
                failed.append((name, m.get("kind"), f"{type(e).__name__}: {e}"))
                print(f"FAIL {name}  {type(e).__name__}: {e}")
    # Manifest lists only files that exist, so stale versions are never offered.
    names = sorted(p.stem for p in OUT.glob("*.webp"))
    (OUT / "index.json").write_text(json.dumps(names, indent=0) + "\n", encoding="utf-8")
    print(f"\n{done} rendered, {len(failed)} failed -> {OUT}")
    for n, k, why in failed:
        print(f"  {n} ({k}): {why}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
