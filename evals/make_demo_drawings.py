"""New synthetic drawings of parts Shilpa has not seen, for a browser demo of drawing -> CAD.

Each part reuses a golden recipe's structure with new dimensions, so the sheets differ from the
evaluation set. Expected geometry comes from building the modified recipe with the build123d
adapter (a cross-check reference, not an analytic oracle).

Run:  uv run python evals/make_demo_drawings.py
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from make_drawings import DRAWERS, rasterise  # noqa: E402
from shilpa.pipeline import execute  # noqa: E402

OUT = ROOT / "drawings_demo"

DEMOS = [
    # (name, base fixture, parameter overrides, variant)
    ("D1_base_plate", "P02", {"width": 150, "height": 90, "thickness": 12, "hole_diameter": 11, "edge_offset": 15}, "vector"),
    ("D2_pump_flange", "F02", {"outer_diameter": 180, "thickness": 18, "bore_diameter": 75, "bolt_diameter": 13.5,
                               "pitch_diameter": 145, "bolt_count": {"value": 8, "kind": "count"},
                               "start_angle": {"value": 22.5, "kind": "angle", "unit": "deg"}}, "vector"),
    ("D3_drive_shaft", "H02", {"d1": 32, "l1": 18, "d2": 25, "l2": 60, "d3": 20, "l3": 35}, "scan"),
    ("D4_motor_bracket", "B04", {"width": 90, "depth": 65, "thickness": 8, "height": 75, "hole_diameter": 9, "hole_pitch": 55,
                                 "inner_radius": 5}, "vector"),
    ("D5_controller_box", "E02", {"width": 160, "depth": 100, "height": 50, "wall": 3, "floor": 4, "outer_radius": 8,
                                  "inner_radius": 5}, "vector"),
    ("D6_spacer_ring", "S05", {"outer_diameter": 56, "inner_diameter": 30, "length": 14, "chamfer": 1.5}, "scan"),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*"):
        f.unlink()
    manifest = []
    for name, base, overrides, variant in DEMOS:
        fx = json.loads((ROOT / "corpus" / f"{base}.json").read_text(encoding="utf-8"))
        recipe = copy.deepcopy(fx["recipe"])
        for k, v in overrides.items():
            if k not in recipe["parameters"]:
                raise SystemExit(f"{name}: {base} has no parameter {k}")
            recipe["parameters"][k] = v
        recipe["name"] = name
        recipe["assertions"].pop("holes", None)  # literal counts belong to the base fixture
        ref = execute(recipe, Path(tempfile.mkdtemp(prefix="demo-ref-")))
        if not ref.ok:
            raise SystemExit(f"{name}: reference build failed: {ref.error.message}")
        m = ref.validation["measurement"]
        demo = {**fx, "id": name, "recipe": recipe}
        pdf = OUT / f"{name}.pdf"
        if variant == "scan":
            tmp = OUT / f"_{name}.pdf"
            DRAWERS[fx["family"]](demo, "vector").save(tmp)
            rasterise(tmp, pdf, dpi=150, seed=len(manifest) + 7)
            tmp.unlink()
        else:
            DRAWERS[fx["family"]](demo, "vector").save(pdf)
        holes: dict[str, int] = {}
        for c in m["cylinders"]:
            if c["kind"] == "hole":
                holes[str(round(c["diameter"], 3))] = holes.get(str(round(c["diameter"], 3)), 0) + 1
        manifest.append({"id": name, "base": base, "variant": variant, "file": pdf.name, "family": fx["family"],
                         "expected": {"bbox": m["bbox_size"], "volume": m["volume"], "holes": holes}})
        print(f"{name:20} {variant:6} bbox={m['bbox_size']} volume={m['volume']:.2f} holes={holes}")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
