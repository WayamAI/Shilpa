"""Generate the 30 golden reference recipes with analytic oracles (blueprint G1, T019).

Expected geometry is computed here from closed-form formulas, independently of
the CAD adapter. These are synthetic starter fixtures: the mechanical SME must
review and replace them with approved reference parts (backlog B002).

Run:  uv run python evals/make_corpus.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

OUT = Path(__file__).parent / "corpus"
PI = math.pi
INCH = 25.4


def circ(d):
    return PI * d * d / 4


def rect(id, w, h, plane="XY", cx=None, cy=None, r=None):
    f = {"id": id, "op": "centered_rectangle", "plane": plane, "width_ref": w, "height_ref": h}
    if cx:
        f["center_x_ref"] = cx
    if cy:
        f["center_y_ref"] = cy
    if r:
        f["corner_radius_ref"] = r
    return f


def circle(id, d, cx=None, cy=None):
    f = {"id": id, "op": "circle", "plane": "XY", "diameter_ref": d}
    if cx:
        f["center_x_ref"] = cx
    if cy:
        f["center_y_ref"] = cy
    return f


def extrude(id, prof, dist, offset=None, direction="positive_z"):
    f = {"id": id, "op": "extrude", "profile_ref": prof, "distance_ref": dist, "direction": direction}
    if offset:
        f["offset_ref"] = offset
    return f


def recipe(name, params, features, bbox_ref=None, holes=None):
    r = {"schema_version": "1.0", "name": name, "intent": "engineering_cad", "units": "mm", "parameters": params, "features": features}
    a = {"solid_count": 1, "valid_brep": True}
    if bbox_ref:
        a["bbox_ref"] = bbox_ref
    if holes:
        a["holes"] = holes
    r["assertions"] = a
    return r


fixtures: list[dict] = []


def add(id, family, desc, rec, bbox, volume, holes=None, hole_centers=None):
    oracle = {"bbox": [round(x, 6) for x in bbox], "volume": round(volume, 6), "solid_count": 1}
    if holes:
        oracle["holes"] = {str(k): v for k, v in holes.items()}
    if hole_centers:
        oracle["hole_centers"] = hole_centers
    fixtures.append({"id": id, "family": family, "description": desc, "recipe": rec, "oracle": oracle})


# ------------------------------------------------------------------ plates


def corner_plate(id, w, h, t, d, e, desc, units="mm", fillet=None):
    params = {"width": w, "height": h, "thickness": t, "hole_diameter": d, "edge_offset": e}
    feats = [rect("base_profile", "width", "height"), extrude("base_solid", "base_profile", "thickness")]
    body = "base_solid"
    if fillet:
        params["corner_radius"] = fillet
        feats.append({"id": "corner_round", "op": "fillet", "body_ref": body, "radius_ref": "corner_radius",
                      "edges": {"direction": "parallel_z", "boundary": "outer", "expected_count": 4}})
        body = "corner_round"
    feats.append({"id": "mount_holes", "op": "corner_hole_pattern", "body_ref": body, "diameter_ref": "hole_diameter",
                  "edge_offset_ref": "edge_offset", "mode": "through_all"})
    rec = recipe(desc, params, feats, ["width", "height", "thickness"], [{"diameter_ref": "hole_diameter", "count": 4}])
    rec["units"] = units
    k = INCH if units == "in" else 1.0
    W, H, T, D, E = (x * k for x in (w, h, t, d, e))
    area = W * H - ((4 - PI) * (fillet * k) ** 2 if fillet else 0)
    vol = area * T - 4 * circ(D) * T
    cx, cy = W / 2 - E, H / 2 - E
    centers = [[sx * cx, sy * cy] for sx in (-1, 1) for sy in (-1, 1)]
    add(id, "plate", desc, rec, (W, H, T), vol, {round(D, 4): 4}, {"diameter": D, "centers": centers})


corner_plate("P01", 80, 40, 8, 6, 10, "Analytic plate 80x40x8 with four 6 mm corner holes")
corner_plate("P02", 100, 60, 10, 8, 12, "Mounting plate 100x60x10 with four 8 mm holes")
corner_plate("P04", 90, 70, 6, 5.5, 10, "Plate with R5 outer corners and four 5.5 mm holes", fillet=5)
corner_plate("P05", 4, 2, 0.25, 0.25, 0.5, "Imperial plate 4x2x0.25 in with four 0.25 in holes", units="in")

# P03: linear 3x2 pattern
params = {"width": 120, "height": 80, "thickness": 6, "hole_diameter": 6.6, "pitch_x": 40, "pitch_y": 40,
          "count_x": {"value": 3, "kind": "count"}, "count_y": {"value": 2, "kind": "count"}}
feats = [rect("base_profile", "width", "height"), extrude("base_solid", "base_profile", "thickness"),
         {"id": "grid", "op": "linear_hole_pattern", "body_ref": "base_solid", "diameter_ref": "hole_diameter",
          "count_x_ref": "count_x", "count_y_ref": "count_y", "pitch_x_ref": "pitch_x", "pitch_y_ref": "pitch_y"}]
centers = [[x, y] for x in (-40, 0, 40) for y in (-20, 20)]
add("P03", "plate", "Plate 120x80x6 with a 3x2 grid of 6.6 mm holes",
    recipe("Grid plate", params, feats, ["width", "height", "thickness"], [{"diameter_ref": "hole_diameter", "count": 6}]),
    (120, 80, 6), 120 * 80 * 6 - 6 * circ(6.6) * 6, {6.6: 6}, {"diameter": 6.6, "centers": centers})


# ------------------------------------------------------------------ spacers


def spacer_rev(id, od, idia, length, desc):
    params = {"outer_diameter": od, "inner_diameter": idia, "length": length}
    feats = [{"id": "body", "op": "stepped_shaft", "sections": [{"diameter_ref": "outer_diameter", "length_ref": "length"}],
              "bore_diameter_ref": "inner_diameter"}]
    add(id, "spacer", desc, recipe(desc, params, feats, ["outer_diameter", "outer_diameter", "length"]),
        (od, od, length), (circ(od) - circ(idia)) * length, {idia: 1})


def spacer_ext(id, od, idia, length, desc, chamfer=None):
    params = {"outer_diameter": od, "inner_diameter": idia, "length": length}
    feats = [circle("outer", "outer_diameter"), extrude("blank", "outer", "length")]
    body = "blank"
    vol = (circ(od) - circ(idia)) * length
    if chamfer:
        params["chamfer"] = chamfer
        feats.append({"id": "edge_break", "op": "chamfer", "body_ref": body, "distance_ref": "chamfer",
                      "edges": {"curve": "circle", "location": "top", "boundary": "outer", "expected_count": 1}})
        body = "edge_break"
        r = od / 2
        vol -= 2 * PI * (r - chamfer / 3) * chamfer * chamfer / 2  # Pappus on the removed triangle
    feats.append({"id": "bore", "op": "hole", "body_ref": body, "diameter_ref": "inner_diameter"})
    add(id, "spacer", desc, recipe(desc, params, feats, ["outer_diameter", "outer_diameter", "length"],
                                   [{"diameter_ref": "inner_diameter", "count": 1}]),
        (od, od, length), vol, {idia: 1})


spacer_rev("S01", 20, 10, 5, "Revolved spacer OD20 ID10 L5")
spacer_ext("S02", 30, 12.5, 15, "Extruded spacer OD30 ID12.5 L15")
spacer_rev("S03", 12, 6.4, 8, "Small spacer OD12 ID6.4 L8")
spacer_ext("S04", 50, 25, 3, "Thin washer OD50 ID25 T3")
spacer_ext("S05", 40, 20, 10, "Spacer OD40 ID20 L10 with 1 mm outer chamfer", chamfer=1)


# ------------------------------------------------------------------ shafts


def shaft(id, sections, desc, bore=None, chamfer=None):
    params, secs = {}, []
    for i, (d, l) in enumerate(sections, 1):
        params[f"d{i}"], params[f"l{i}"] = d, l
        secs.append({"diameter_ref": f"d{i}", "length_ref": f"l{i}"})
    f = {"id": "shaft", "op": "stepped_shaft", "sections": secs}
    vol = sum(circ(d) * l for d, l in sections)
    total = sum(l for _, l in sections)
    holes = None
    if bore:
        params["bore"] = bore
        f["bore_diameter_ref"] = "bore"
        vol -= circ(bore) * total
        holes = {bore: 1}
    feats = [f]
    if chamfer:
        params["end_chamfer"] = chamfer
        feats.append({"id": "end_break", "op": "chamfer", "body_ref": "shaft", "distance_ref": "end_chamfer",
                      "edges": {"curve": "circle", "location": "top", "boundary": "any", "expected_count": 1}})
        r = sections[-1][0] / 2
        vol -= 2 * PI * (r - chamfer / 3) * chamfer * chamfer / 2
    dmax = max(d for d, _ in sections)
    add(id, "shaft", desc, recipe(desc, params, feats), (dmax, dmax, total), vol, holes)


shaft("H01", [(20, 30), (12, 20)], "Two-step shaft 20x30 / 12x20")
shaft("H02", [(25, 10), (18, 40), (12, 25)], "Three-step shaft")
shaft("H03", [(30, 15), (24, 30), (20, 40), (16, 20)], "Four-step hollow shaft with 6 mm bore", bore=6)
shaft("H04", [(10, 100)], "Dowel pin D10 L100")
shaft("H05", [(22, 20), (16, 35)], "Stepped shaft with 1 mm end chamfer", chamfer=1)


# ------------------------------------------------------------------ flanges


def flange(id, od, t, bore, n, d, pcd, desc, start=None, start_unit=None):
    params = {"outer_diameter": od, "thickness": t, "bore_diameter": bore, "bolt_diameter": d, "pitch_diameter": pcd,
              "bolt_count": {"value": n, "kind": "count"}}
    pat = {"id": "bolts", "op": "polar_hole_pattern", "body_ref": "disc", "diameter_ref": "bolt_diameter",
           "count_ref": "bolt_count", "pitch_diameter_ref": "pitch_diameter"}
    a0 = 0.0
    if start is not None:
        params["start_angle"] = {"value": start, "kind": "angle", "unit": start_unit or "deg"}
        pat["start_angle_ref"] = "start_angle"
        a0 = start if (start_unit or "deg") == "rad" else math.radians(start)
    feats = [circle("disc_profile", "outer_diameter"), extrude("disc", "disc_profile", "thickness"), pat,
             {"id": "bore", "op": "hole", "body_ref": "bolts", "diameter_ref": "bore_diameter"}]
    centers = [[pcd / 2 * math.cos(a0 + 2 * PI * k / n), pcd / 2 * math.sin(a0 + 2 * PI * k / n)] for k in range(n)]
    vol = (circ(od) - circ(bore) - n * circ(d)) * t
    add(id, "flange", desc, recipe(desc, params, feats, ["outer_diameter", "outer_diameter", "thickness"],
                                   [{"diameter_ref": "bolt_diameter", "count": n}, {"diameter_ref": "bore_diameter", "count": 1}]),
        (od, od, t), vol, {d: n, bore: 1}, {"diameter": d, "centers": centers})


flange("F01", 100, 12, 40, 4, 10, 70, "Flange OD100 with 4x10 on PCD70")
flange("F02", 150, 16, 60, 6, 14, 115, "Flange OD150 with 6x14 on PCD115 rotated 30 deg", start=30)
flange("F04", 80, 10, 30, 8, 6, 60, "Flange OD80 with 8x6 rotated pi/8 rad", start=math.pi / 8, start_unit="rad")

# F03 hub flange
params = {"outer_diameter": 120, "thickness": 12, "hub_diameter": 60, "hub_length": 25, "bore_diameter": 35,
          "bolt_diameter": 12, "pitch_diameter": 90, "bolt_count": {"value": 4, "kind": "count"}}
feats = [circle("disc_profile", "outer_diameter"), extrude("disc", "disc_profile", "thickness"),
         {"id": "bolts", "op": "polar_hole_pattern", "body_ref": "disc", "diameter_ref": "bolt_diameter",
          "count_ref": "bolt_count", "pitch_diameter_ref": "pitch_diameter"},
         circle("hub_profile", "hub_diameter"), extrude("hub", "hub_profile", "hub_length", offset="thickness"),
         {"id": "joined", "op": "boolean", "operation": "union", "target_ref": "bolts", "tool_ref": "hub"},
         {"id": "bore", "op": "hole", "body_ref": "joined", "diameter_ref": "bore_diameter"}]
vol = circ(120) * 12 + circ(60) * 25 - 4 * circ(12) * 12 - circ(35) * 37
add("F03", "flange", "Hub flange OD120 with hub D60x25 and 35 bore",
    recipe("Hub flange", params, feats, ["outer_diameter", "outer_diameter", "thickness + hub_length"]),
    (120, 120, 37), vol, {12: 4, 35: 1}, {"diameter": 12, "centers": [[45, 0], [0, 45], [-45, 0], [0, -45]]})

# F05 square flange
params = {"width": 100, "thickness": 12, "bore_diameter": 50, "bolt_diameter": 10, "edge_offset": 12}
feats = [rect("plate_profile", "width", "width"), extrude("plate", "plate_profile", "thickness"),
         {"id": "bolts", "op": "corner_hole_pattern", "body_ref": "plate", "diameter_ref": "bolt_diameter", "edge_offset_ref": "edge_offset"},
         {"id": "bore", "op": "hole", "body_ref": "bolts", "diameter_ref": "bore_diameter"}]
add("F05", "flange", "Square flange 100x100x12 with 50 bore and 4x10 corners",
    recipe("Square flange", params, feats, ["width", "width", "thickness"]),
    (100, 100, 12), (100 * 100 - circ(50) - 4 * circ(10)) * 12, {10: 4, 50: 1},
    {"diameter": 10, "centers": [[sx * 38, sy * 38] for sx in (-1, 1) for sy in (-1, 1)]})


# ------------------------------------------------------------------ brackets


def l_bracket(id, w, dep, t, h, desc, holes=None, fillet=None):
    params = {"width": w, "depth": dep, "thickness": t, "height": h}
    feats = [rect("base_profile", "width", "depth"), extrude("base", "base_profile", "thickness")]
    base = "base"
    vol = w * dep * t + w * t * (h - t)
    hole_map = None
    centers = None
    if holes:
        hd, pitch = holes
        params["hole_diameter"], params["hole_pitch"] = hd, pitch
        params["hole_count"] = {"value": 2, "kind": "count"}
        params["one"] = {"value": 1, "kind": "count"}
        feats.append({"id": "base_holes", "op": "linear_hole_pattern", "body_ref": "base", "diameter_ref": "hole_diameter",
                      "count_x_ref": "hole_count", "count_y_ref": "one", "pitch_x_ref": "hole_pitch", "pitch_y_ref": "hole_pitch",
                      "center_y_ref": "-thickness / 2"})
        base = "base_holes"
        vol -= 2 * circ(hd) * t
        hole_map = {hd: 2}
        centers = {"diameter": hd, "centers": [[-pitch / 2, -t / 2], [pitch / 2, -t / 2]]}
    feats += [rect("leg_profile", "width", "thickness", cy="depth / 2 - thickness / 2"),
              extrude("leg", "leg_profile", "height - thickness", offset="thickness"),
              {"id": "bracket", "op": "boolean", "operation": "union", "target_ref": base, "tool_ref": "leg"}]
    if fillet:
        params["inner_radius"] = fillet
        feats.append({"id": "inner_round", "op": "fillet", "body_ref": "bracket", "radius_ref": "inner_radius",
                      "edges": {"direction": "perpendicular_z", "location": "between", "curve": "line", "boundary": "inner", "expected_count": 1}})
        vol += w * fillet * fillet * (1 - PI / 4)
    add(id, "bracket", desc, recipe(desc, params, feats, ["width", "depth", "height"]), (w, dep, h), vol, hole_map, centers)


l_bracket("B01", 60, 50, 6, 50, "L bracket 60 wide, 50 deep, 50 high, 6 thick")
l_bracket("B02", 80, 60, 8, 60, "L bracket with two 8.5 mm base holes", holes=(8.5, 50))
l_bracket("B03", 50, 40, 5, 45, "L bracket with R4 inner fillet", fillet=4)
l_bracket("B04", 100, 70, 10, 80, "Heavy L bracket with holes and R6 inner fillet", holes=(10.5, 60), fillet=6)

# B05 strap bracket
params = {"length": 120, "width": 25, "thickness": 5, "hole_diameter": 6.5, "hole_pitch": 90,
          "hole_count": {"value": 2, "kind": "count"}, "one": {"value": 1, "kind": "count"}}
feats = [rect("strap_profile", "length", "width"), extrude("strap", "strap_profile", "thickness"),
         {"id": "holes", "op": "linear_hole_pattern", "body_ref": "strap", "diameter_ref": "hole_diameter", "count_x_ref": "hole_count",
          "count_y_ref": "one", "pitch_x_ref": "hole_pitch", "pitch_y_ref": "hole_pitch"}]
add("B05", "bracket", "Flat strap bracket 120x25x5 with two holes",
    recipe("Strap bracket", params, feats, ["length", "width", "thickness"]),
    (120, 25, 5), 120 * 25 * 5 - 2 * circ(6.5) * 5, {6.5: 2}, {"diameter": 6.5, "centers": [[-45, 0], [45, 0]]})


# ------------------------------------------------------------------ enclosures


def enclosure(id, w, dep, h, wall, floor, desc, outer_r=None, inner_r=None, chamfer=None, fillet=None):
    params = {"width": w, "depth": dep, "height": h, "wall": wall, "floor": floor}
    feats = [rect("outline", "width", "depth", r="outer_radius" if outer_r else None), extrude("box", "outline", "height")]
    if outer_r:
        params["outer_radius"] = outer_r
    body = "box"
    area = w * dep - ((4 - PI) * outer_r ** 2 if outer_r else 0)
    vol = area * h
    if fillet:
        params["corner_fillet"] = fillet
        feats.append({"id": "rounded", "op": "fillet", "body_ref": body, "radius_ref": "corner_fillet",
                      "edges": {"direction": "parallel_z", "boundary": "outer", "expected_count": 4}})
        body = "rounded"
        vol -= (4 - PI) * fillet ** 2 * h
    if chamfer:
        params["top_chamfer"] = chamfer
        feats.append({"id": "top_break", "op": "chamfer", "body_ref": body, "distance_ref": "top_chamfer",
                      "edges": {"direction": "perpendicular_z", "location": "top", "curve": "line", "boundary": "outer", "expected_count": 4}})
        body = "top_break"
        vol -= chamfer ** 2 / 2 * (2 * w + 2 * dep) - 4 * chamfer ** 3 / 3
    pocket = {"id": "cavity", "op": "pocket", "body_ref": body, "width_ref": "width - 2 * wall", "height_ref": "depth - 2 * wall",
              "depth_ref": "height - floor"}
    pw, pd = w - 2 * wall, dep - 2 * wall
    parea = pw * pd
    if inner_r:
        params["inner_radius"] = inner_r
        pocket["corner_radius_ref"] = "inner_radius"
        parea -= (4 - PI) * inner_r ** 2
    feats.append(pocket)
    vol -= parea * (h - floor)
    add(id, "enclosure", desc, recipe(desc, params, feats, ["width", "depth", "height"]), (w, dep, h), vol)


enclosure("E01", 100, 60, 40, 3, 3, "Open box 100x60x40, 3 mm walls")
enclosure("E02", 120, 80, 35, 2.5, 3, "Rounded box R6 with R3.5 inner corners", outer_r=6, inner_r=3.5)
enclosure("E03", 50, 50, 30, 2, 2, "Small open box 50x50x30")
enclosure("E04", 90, 70, 30, 3, 4, "Box with 1.5 mm top outer chamfer", chamfer=1.5)
enclosure("E05", 110, 75, 45, 3, 3, "Box with R5 filleted vertical corners", fillet=5)

assert len(fixtures) == 30, len(fixtures)
OUT.mkdir(parents=True, exist_ok=True)
for old in OUT.glob("*.json"):
    old.unlink()
for f in fixtures:
    (OUT / f"{f['id']}.json").write_text(json.dumps(f, indent=2), encoding="utf-8")
print(f"wrote {len(fixtures)} fixtures to {OUT}")
