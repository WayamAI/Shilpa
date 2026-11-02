"""Render one isometric thumbnail per listed catalog generator (default params).

Offline and deterministic: builds each part with build123d, tessellates it, and
rasterises it with a small painter's-algorithm renderer (numpy + Pillow, both
already project dependencies; no GPU, no extra packages). Output is a
transparent 480x400 WebP per generator in apps/web/public/thumbs/catalog/.

    uv run python scripts/render_catalog_thumbs.py            # all generators
    uv run python scripts/render_catalog_thumbs.py screw.button_head nut.hex
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shilpa.thumbs import decode, render, to_webp  # noqa: E402,F401  (the renderer lives in the package)

OUT = ROOT / "apps" / "web" / "public" / "thumbs" / "catalog"

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
            (OUT / f"{name}.webp").write_bytes(to_webp(render(verts, faces)))
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
