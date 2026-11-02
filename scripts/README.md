# scripts

## render_catalog_thumbs.py

Renders one isometric WebP thumbnail per listed catalog generator (default
params) into `apps/web/public/thumbs/catalog/`, plus `index.json` listing which
exist (the Library reads it and falls back to the category icon otherwise).
Uses only numpy, Pillow and trimesh (already dependencies); no GPU.

    uv run python scripts/render_catalog_thumbs.py            # all
    uv run python scripts/render_catalog_thumbs.py screw.button_head   # some

Model thumbnails are rendered by the CAD worker when a version is published (THUMB artifact); backfill existing versions with `uv run python -m shilpa.thumbs backfill`.
