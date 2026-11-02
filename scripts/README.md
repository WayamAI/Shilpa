# scripts

## render_catalog_thumbs.py

Renders one isometric WebP thumbnail per listed catalog generator (default
params) into `apps/web/public/thumbs/catalog/`, plus `index.json` listing which
exist (the Library reads it and falls back to the category icon otherwise).
Uses only numpy, Pillow and trimesh (already dependencies); no GPU.

    uv run python scripts/render_catalog_thumbs.py            # all
    uv run python scripts/render_catalog_thumbs.py screw.button_head   # some

## render_model_thumbs.py

Renders the head version of every project model visible to the API caller
(parts from their STL, assemblies/products/sheet metal from MESHES + VIEWER with
all instances placed) into `apps/web/public/thumbs/models/<model_id>-v<n>.webp`
plus `index.json`. A model whose head version has no file falls back to the icon,
so a stale image is never shown. Needs the API running.

    uv run python scripts/render_model_thumbs.py
    API=http://127.0.0.1:8010 TOKEN=dev:dev@wayam.local uv run python scripts/render_model_thumbs.py
