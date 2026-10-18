"""Generate the golden reference recipes with analytic oracles (blueprint G1, T019).

P/S/H/F/B/E (30 parts) use IR 1.0 operations; N01-N15 exercise the IR 1.1 vocabulary
(profiles, slots, revolve, sweep, helix, loft, shell, mirror, body patterns, hole series).

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


def recipe(name, params, features, bbox_ref=None, holes=None, version="1.0"):
    r = {"schema_version": version, "name": name, "intent": "engineering_cad", "units": "mm", "parameters": params, "features": features}
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


# ------------------------------------------------------------------ IR 1.1 parts (N01-N15)
#
# Oracles below are closed form or exact quadrature of the recipe's own numbers: polygon
# areas by the shoelace formula, revolved volumes by Pappus, frusta, bicylinder
# intersections and circular segments. None of it calls the CAD path or profile2d.


def r11(name, params, features, bbox_ref=None, holes=None):
    return recipe(name, params, features, bbox_ref, holes, version="1.1")


def seg(x, y, kind="line", **kw):
    s = {"kind": kind, "x_ref": x, "y_ref": y}
    s.update({f"{k}_ref" if k != "clockwise" else k: v for k, v in kw.items()})
    return s


def poly_area_centroid(pts):
    """Signed area and centroid of a closed polygon."""
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        c = x0 * y1 - x1 * y0
        a += c / 2
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    return a, cx / (6 * a), cy / (6 * a)


def arc_segment_area(p0, pm, p1):
    """Signed area between chord p0-p1 and the circular arc through pm (+ when the arc runs counter-clockwise)."""
    ax, ay = p0
    bx, by = pm
    qx, qy = p1
    d = 2 * (ax * (by - qy) + bx * (qy - ay) + qx * (ay - by))
    ux = ((ax * ax + ay * ay) * (by - qy) + (bx * bx + by * by) * (qy - ay) + (qx * qx + qy * qy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (qx - bx) + (bx * bx + by * by) * (ax - qx) + (qx * qx + qy * qy) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    ccw = (bx - ax) * (qy - ay) - (by - ay) * (qx - ax) > 0
    a0, a1 = math.atan2(ay - uy, ax - ux), math.atan2(qy - uy, qx - ux)
    sweep = (a1 - a0) % (2 * PI) if ccw else (a0 - a1) % (2 * PI)
    s = r * r / 2 * (sweep - math.sin(sweep))
    return s if ccw else -s


# N01 V-belt pulley: polygon half-section on XZ revolved about Z (Pappus).
params = {"bore_diameter": 12, "outer_diameter": 80, "width": 20, "groove_top": 14, "groove_bottom": 7, "groove_depth": 10}
P = params
R, W = P["outer_diameter"] / 2, P["width"]
pts = [(P["bore_diameter"] / 2, 0), (R, 0), (R, (W - P["groove_top"]) / 2), (R - P["groove_depth"], (W - P["groove_bottom"]) / 2),
       (R - P["groove_depth"], (W + P["groove_bottom"]) / 2), (R, (W + P["groove_top"]) / 2), (R, W), (P["bore_diameter"] / 2, W)]
area, xc, _ = poly_area_centroid(pts)
feats = [{"id": "half_section", "op": "profile", "plane": "XZ", "start_x_ref": "bore_diameter / 2", "start_y_ref": "0 * width",
          "segments": [seg("outer_diameter / 2", "0 * width"), seg("outer_diameter / 2", "(width - groove_top) / 2"),
                       seg("outer_diameter / 2 - groove_depth", "(width - groove_bottom) / 2"),
                       seg("outer_diameter / 2 - groove_depth", "(width + groove_bottom) / 2"),
                       seg("outer_diameter / 2", "(width + groove_top) / 2"), seg("outer_diameter / 2", "width"),
                       seg("bore_diameter / 2", "width")]},
         {"id": "pulley", "op": "revolve", "profile_ref": "half_section", "axis": "Z"}]
add("N01", "pulley", "V-belt pulley OD80 x 20 with a 14/7 x 10 groove and 12 bore (revolved profile)",
    r11("V-belt pulley", params, feats, ["outer_diameter", "outer_diameter", "width"]), (80, 80, 20), 2 * PI * xc * abs(area), {12: 1})

# N02 swept tube bend: ring section along line - R40 bend - line (Pappus on the bend).
params = {"outer_diameter": 20, "inner_diameter": 16, "rise": 50, "bend_radius": 40, "run": 60}
feats = [{"id": "section", "op": "circle", "diameter_ref": "outer_diameter", "inner_diameter_ref": "inner_diameter"},
         {"id": "centreline", "op": "path", "plane": "XZ", "start_x_ref": "0 * rise", "start_y_ref": "0 * rise",
          "segments": [seg("0 * rise", "rise"), seg("bend_radius", "rise + bend_radius", "tangent_arc"),
                       seg("bend_radius + run", "rise + bend_radius")]},
         {"id": "tube", "op": "sweep", "profile_ref": "section", "path_ref": "centreline"}]
add("N02", "tube", "Swept tube OD20 ID16: 50 rise, R40 90-degree bend, 60 run",
    r11("Tube bend", params, feats), (110, 20, 100), (circ(20) - circ(16)) * (50 + PI * 40 / 2 + 60))

# N03 lofted nozzle: ruled loft between offset circles is an oblique frustum (Cavalieri).
params = {"inlet_diameter": 60, "outlet_diameter": 36, "length": 50, "outlet_offset": 10}
feats = [{"id": "inlet", "op": "circle", "diameter_ref": "inlet_diameter"},
         {"id": "outlet", "op": "circle", "diameter_ref": "outlet_diameter", "center_x_ref": "outlet_offset", "offset_ref": "length"},
         {"id": "nozzle", "op": "loft", "profile_refs": ["inlet", "outlet"], "ruled": True}]
add("N03", "duct", "Lofted transition nozzle Ø60 to Ø36 over 50 with the outlet 10 off-axis",
    r11("Offset nozzle", params, feats), (60, 60, 50), PI * 50 / 3 * (30 ** 2 + 30 * 18 + 18 ** 2))

# N04 shelled hopper: ruled square loft 80 -> 40 over 60, shelled 3 mm with top and bottom open.
params = {"bottom_width": 80, "top_width": 40, "height": 60, "wall": 3}
off = 3 / (60 / math.hypot(60, 20))  # wall / cos(face inclination): inward shift of each sloped face
a_in, b_in = 80 - 2 * off, 40 - 2 * off
feats = [{"id": "base", "op": "centered_rectangle", "width_ref": "bottom_width", "height_ref": "bottom_width"},
         {"id": "mouth", "op": "centered_rectangle", "width_ref": "top_width", "height_ref": "top_width", "offset_ref": "height"},
         {"id": "solid", "op": "loft", "profile_refs": ["base", "mouth"], "ruled": True},
         {"id": "hopper", "op": "shell", "body_ref": "solid", "thickness_ref": "wall",
          "open_faces": [{"side": "top", "expected_count": 1}, {"side": "bottom", "expected_count": 1}]}]
add("N04", "duct", "Lofted square hopper 80 to 40 over 60, shelled to 3 mm walls, open top and bottom",
    r11("Shelled hopper", params, feats, ["bottom_width", "bottom_width", "height"]), (80, 80, 60),
    60 / 3 * (80 ** 2 + 80 * 40 + 40 ** 2) - 60 / 3 * (a_in ** 2 + a_in * b_in + b_in ** 2))

# N05 shelled enclosure: R8 vertical corners, shelled 2.5 mm open at the top (inner corners R5.5).
params = {"width": 120, "depth": 80, "height": 40, "corner_radius": 8, "wall": 2.5}
feats = [{"id": "outline", "op": "centered_rectangle", "width_ref": "width", "height_ref": "depth"},
         {"id": "block", "op": "extrude", "profile_ref": "outline", "distance_ref": "height"},
         {"id": "rounded", "op": "fillet", "body_ref": "block", "radius_ref": "corner_radius",
          "edges": {"direction": "parallel_z", "boundary": "outer", "expected_count": 4}},
         {"id": "enclosure", "op": "shell", "body_ref": "rounded", "thickness_ref": "wall", "open_faces": [{"side": "top"}]}]
outer_a = 120 * 80 - (4 - PI) * 64
inner_a = 115 * 75 - (4 - PI) * 5.5 ** 2
add("N05", "enclosure", "Shelled enclosure 120x80x40 with R8 corners, 2.5 mm walls, open top",
    r11("Shelled enclosure", params, feats, ["width", "depth", "height"]), (120, 80, 40), outer_a * 40 - inner_a * 37.5)

# N06 countersunk plate: four M5 ISO 10642 countersinks (ISO 273 medium 5.5 clearance, Ø11.2 x 90 deg).
params = {"width": 100, "depth": 60, "thickness": 8, "edge_offset": 10}
feats = [rect("outline", "width", "depth"), extrude("plate", "outline", "thickness"),
         {"id": "csk_holes", "op": "corner_hole_pattern", "body_ref": "plate", "edge_offset_ref": "edge_offset",
          "hole_type": "countersink", "standard_size": "M5"}]
h = (11.2 - 5.5) / 2
add("N06", "plate", "Plate 100x60x8 with four M5 countersunk holes 10 from the edges",
    r11("Countersunk plate", params, feats, ["width", "depth", "thickness"]), (100, 60, 8),
    100 * 60 * 8 - 4 * (circ(5.5) * (8 - h) + PI * h / 12 * (11.2 ** 2 + 11.2 * 5.5 + 5.5 ** 2)), {5.5: 4},
    {"diameter": 5.5, "centers": [[sx * 40, sy * 20] for sx in (-1, 1) for sy in (-1, 1)]})

# N07 counterbored block: two M8 ISO 4762 counterbores (Ø15 x 8.6, Ø9 through) and an M10 tapped side hole.
params = {"length": 80, "width": 50, "height": 20, "pitch": 50, "port_y": 15, "port_z": 10, "tap_depth": 15, "thread_length": 12,
          "count": {"value": 2, "kind": "count"}, "one": {"value": 1, "kind": "count"}}
feats = [rect("outline", "length", "width"), extrude("block", "outline", "height"),
         {"id": "cbores", "op": "linear_hole_pattern", "body_ref": "block", "count_x_ref": "count", "count_y_ref": "one",
          "pitch_x_ref": "pitch", "pitch_y_ref": "pitch", "hole_type": "counterbore", "standard_size": "M8"},
         {"id": "side_tap", "op": "hole", "body_ref": "cbores", "face": "x_max", "center_x_ref": "port_y", "center_y_ref": "port_z",
          "mode": "blind", "depth_ref": "tap_depth", "hole_type": "tapped", "standard_size": "M10", "thread_depth_ref": "thread_length"}]
add("N07", "block", "Block 80x50x20 with two M8 counterbored holes and an M10 tapped side port",
    r11("Counterbored block", params, feats, ["length", "width", "height"]), (80, 50, 20),
    80 * 50 * 20 - 2 * (circ(15) * 8.6 + circ(9) * 11.4) - circ(8.5) * 15, {9: 2, 15: 2, 8.5: 1},
    {"diameter": 9, "centers": [[-25, 0], [25, 0]]})

# N08 mirrored bracket: half outline (line, tangent semicircle, line), a hole, mirrored about YZ.
params = {"end_radius": 15, "half_length": 30, "thickness": 8, "hole_diameter": 8, "hole_x": 35}
feats = [{"id": "half_outline", "op": "profile", "start_x_ref": "0 * end_radius", "start_y_ref": "-end_radius",
          "segments": [seg("half_length", "-end_radius"), seg("half_length", "end_radius", "tangent_arc"),
                       seg("0 * end_radius", "end_radius")]},
         {"id": "half", "op": "extrude", "profile_ref": "half_outline", "distance_ref": "thickness"},
         {"id": "half_drilled", "op": "hole", "body_ref": "half", "diameter_ref": "hole_diameter", "center_x_ref": "hole_x"},
         {"id": "link", "op": "mirror", "body_ref": "half_drilled", "plane": "YZ"}]
add("N08", "bracket", "Link bracket 90x30x8 with round ends and two Ø8 holes, built as a mirrored half",
    r11("Mirrored link", params, feats), (90, 30, 8), (60 * 30 + PI * 15 ** 2) * 8 - 2 * circ(8) * 8, {8: 2},
    {"diameter": 8, "centers": [[-35, 0], [35, 0]]})


def strip_in_disc(r, w):
    """Area of the part of a disc of radius r with |y| <= w/2."""
    return (w / 2) * math.sqrt(r * r - w * w / 4) + r * r * math.asin(w / (2 * r))


# N09 spoked wheel: rim, one spoke patterned six times about Z, hub with bore.
params = {"rim_diameter": 100, "rim_inner": 90, "hub_diameter": 30, "bore": 12, "thickness": 10, "spoke_width": 6,
          "spoke_length": 34, "spoke_centre": 30, "spokes": {"value": 6, "kind": "count"}}
feats = [circle("rim_ring", "rim_diameter"), extrude("rim", "rim_ring", "thickness"),
         rect("spoke_outline", "spoke_length", "spoke_width", cx="spoke_centre"), extrude("spoke", "spoke_outline", "thickness"),
         {"id": "spoke_set", "op": "polar_pattern", "body_ref": "spoke", "count_ref": "spokes"},
         {"id": "rim_spokes", "op": "boolean", "operation": "union", "target_ref": "rim", "tool_ref": "spoke_set"},
         circle("hub_ring", "hub_diameter"), extrude("hub", "hub_ring", "thickness"),
         {"id": "wheel", "op": "boolean", "operation": "union", "target_ref": "rim_spokes", "tool_ref": "hub"}]
feats[0]["inner_diameter_ref"] = "rim_inner"
feats[6]["inner_diameter_ref"] = "bore"
spoke_area = strip_in_disc(45, 6) - strip_in_disc(15, 6)
add("N09", "wheel", "Spoked wheel Ø100 x 10: rim 5 wide, six 6 mm spokes, Ø30 hub with 12 bore",
    r11("Spoked wheel", params, feats), (100, 100, 10), ((circ(100) - circ(90)) + (circ(30) - circ(12)) + 6 * spoke_area) * 10, {12: 1})

# N10 bossed rail: one boss linearly patterned four times along X, then drilled through every boss.
params = {"length": 120, "width": 30, "thickness": 6, "boss_diameter": 10, "boss_height": 8, "pitch": 30,
          "hole_diameter": 5.5, "bosses": {"value": 4, "kind": "count"}, "one": {"value": 1, "kind": "count"}}
feats = [rect("rail_outline", "length", "width"), extrude("rail", "rail_outline", "thickness"),
         circle("boss_outline", "boss_diameter", cx="-(bosses - 1) / 2 * pitch"),  # the row stays centred like the holes
         extrude("boss", "boss_outline", "boss_height", offset="thickness"),
         {"id": "boss_row", "op": "linear_pattern", "body_ref": "boss", "direction": "X", "count_ref": "bosses", "spacing_ref": "pitch"},
         {"id": "bossed", "op": "boolean", "operation": "union", "target_ref": "rail", "tool_ref": "boss_row"},
         {"id": "holes", "op": "linear_hole_pattern", "body_ref": "bossed", "diameter_ref": "hole_diameter", "count_x_ref": "bosses",
          "count_y_ref": "one", "pitch_x_ref": "pitch", "pitch_y_ref": "pitch"}]
add("N10", "bracket", "Rail 120x30x6 with four Ø10 x 8 bosses at 30 pitch, each drilled Ø5.5 through",
    r11("Bossed rail", params, feats), (120, 30, 14), 120 * 30 * 6 + 4 * circ(10) * 8 - 4 * circ(5.5) * 14, {5.5: 4},
    {"diameter": 5.5, "centers": [[x, 0] for x in (-45, -15, 15, 45)]})

# N11 compression spring: Ø2 wire in the axial plane swept along a Ø20 helix, 4 turns (Pappus per turn).
params = {"wire_diameter": 2, "mean_diameter": 20, "pitch": 5, "free_length": 20}
feats = [{"id": "wire", "op": "circle", "plane": "XZ", "diameter_ref": "wire_diameter", "center_x_ref": "mean_diameter / 2"},
         {"id": "coil", "op": "helix", "diameter_ref": "mean_diameter", "pitch_ref": "pitch", "height_ref": "free_length"},
         {"id": "spring", "op": "sweep", "profile_ref": "wire", "path_ref": "coil"}]
add("N11", "spring", "Helical spring, Ø2 wire, Ø20 mean diameter, 5 pitch, 4 turns",
    r11("Helical spring", params, feats), (22, 22, 22), circ(2) * 2 * PI * 10 * 4)


def spur_gear_tooth(z, alpha_deg, flank_points=5, sink=0.5):
    """One involute tooth in units of the module, centred on +X.

    Each flank is two circular arcs through involute points, with a tip arc and radial lines
    below the base circle. The tooth closes with an arc ``sink`` inside the root circle so it
    overlaps the root disc it is united with. Returns (start, segments, constants).
    """
    a = math.radians(alpha_deg)
    rb, ra, rf = z / 2 * math.cos(a), z / 2 + 1, z / 2 - 1.25
    r_in = rf - sink
    assert rf < rb, "outline assumes the root circle is inside the base circle"

    def inv(x):
        return math.tan(x) - x

    def theta(r):  # half angular thickness of the tooth at radius r
        return PI / (2 * z) + inv(a) - inv(math.acos(min(1.0, rb / r)))

    def p(r, ang):
        return (round(r * math.cos(ang), 10), round(r * math.sin(ang), 10))

    radii = [rb + (ra - rb) * k / (flank_points - 1) for k in range(flank_points)]
    right = [p(r, -theta(r)) for r in radii]
    left = [p(r, theta(r)) for r in reversed(radii)]
    start = p(r_in, -theta(rb))
    out = [("line", right[0], None), ("arc", right[2], right[1]), ("arc", right[4], right[3]), ("arc", left[0], p(ra, 0.0)),
           ("arc", left[2], left[1]), ("arc", left[4], left[3]), ("line", p(r_in, theta(rb)), None), ("arc", start, p(r_in, 0.0))]
    return start, out, {"rf": rf, "r_in": r_in, "theta_b": theta(rb)}


# N12 involute spur gear (Xometry benchmark style): module 2, 20 teeth, 20 deg, 10 wide, Ø10 bore.
# Root disc plus one profiled tooth patterned 20 times. The tooth coordinates are computed for
# z = 20 and scale with the module, so the recipe is parametric in module and face width.
Z = 20
start, outline, gc = spur_gear_tooth(Z, 20)
params = {"module": 2, "face_width": 10, "bore": 10,
          "teeth": {"value": Z, "kind": "count", "note": "tooth outline coordinates are computed for 20 teeth; edit module only"}}


def mref(v):
    return f"{v!r} * module"


segs, verts, area = [], [start], 0.0
prev = start
for kind, end, mid in outline:
    if kind == "line":
        segs.append(seg(mref(end[0]), mref(end[1])))
    else:
        segs.append(seg(mref(end[0]), mref(end[1]), "arc", mid_x=mref(mid[0]), mid_y=mref(mid[1])))
        area += arc_segment_area(prev, mid, end)
    verts.append(end)
    prev = end
assert verts[-1] == start
area += poly_area_centroid(verts[:-1])[0]
# Tooth area outside the root circle: drop the annular sector between r_in and rf it shares with the disc.
tooth_out = area - gc["theta_b"] * (gc["rf"] ** 2 - gc["r_in"] ** 2)
gear_area = (PI * gc["rf"] ** 2 + Z * tooth_out) * 4  # module 2 -> scale areas by 4
feats = [{"id": "root_circle", "op": "circle", "diameter_ref": mref(2 * gc["rf"])},
         extrude("root_disc", "root_circle", "face_width"),
         {"id": "tooth_outline", "op": "profile", "start_x_ref": mref(start[0]), "start_y_ref": mref(start[1]), "segments": segs},
         extrude("tooth", "tooth_outline", "face_width"),
         {"id": "teeth_set", "op": "polar_pattern", "body_ref": "tooth", "count_ref": "teeth"},
         {"id": "gear_blank", "op": "boolean", "operation": "union", "target_ref": "root_disc", "tool_ref": "teeth_set"},
         {"id": "gear", "op": "hole", "body_ref": "gear_blank", "diameter_ref": "bore"}]
add("N12", "gear", "Involute spur gear m2 z20 20 deg pressure angle, 10 wide, Ø10 bore (one profiled tooth, polar pattern)",
    r11("Spur gear m2 z20", params, feats), (44, 44, 10), gear_area * 10 - circ(10) * 10, {10: 1})


def bicylinder(r_small, r_big, n=4000):
    """Volume common to two perpendicular cylinders whose axes intersect, the thinner one passing fully
    through the other: 8 * integral_0^r sqrt(r^2 - x^2) sqrt(R^2 - x^2) dx (Simpson in x = r sin t)."""
    f = lambda t: r_small * r_small * math.cos(t) ** 2 * math.sqrt(r_big * r_big - (r_small * math.sin(t)) ** 2)  # noqa: E731
    hstep = (PI / 2) / n
    s = f(0) + f(PI / 2) + sum((4 if i % 2 else 2) * f(i * hstep) for i in range(1, n))
    return 8 * s * hstep / 3


# N13 hydraulic manifold block: through gallery along X, blind cross drilling from -Y that breaks into it,
# and a blind Ø8 port from the top that breaks into the cross drilling.
params = {"length": 60, "width": 40, "height": 40, "gallery": 10, "gallery_z": 20, "cross_x": 10, "cross_depth": 28,
          "port": 8, "port_y": -12, "port_depth": 28}
feats = [rect("outline", "length", "width"), extrude("block", "outline", "height"),
         {"id": "gallery_bore", "op": "hole", "body_ref": "block", "face": "x_min", "diameter_ref": "gallery",
          "center_x_ref": "0 * width", "center_y_ref": "gallery_z"},
         {"id": "cross_bore", "op": "hole", "body_ref": "gallery_bore", "face": "y_min", "diameter_ref": "gallery",
          "center_x_ref": "cross_x", "center_y_ref": "gallery_z", "mode": "blind", "depth_ref": "cross_depth"},
         {"id": "manifold", "op": "hole", "body_ref": "cross_bore", "diameter_ref": "port", "center_x_ref": "cross_x",
          "center_y_ref": "port_y", "mode": "blind", "depth_ref": "port_depth"}]
removed = circ(10) * 60 + circ(10) * 28 + circ(8) * 28 - 16 * 5 ** 3 / 3 - bicylinder(4, 5)
add("N13", "manifold", "Manifold block 60x40x40: Ø10 gallery along X, intersecting Ø10 cross drilling and Ø8 top port",
    r11("Manifold block", params, feats, ["length", "width", "height"]), (60, 40, 40), 60 * 40 * 40 - removed)

# N14 slotted plate: one slot cut and mirrored about XZ, plus a slot rotated 90 degrees.
params = {"length": 100, "width": 60, "thickness": 8, "slot_length": 30, "slot_width": 8, "slot_y": 15,
          "cross_length": 20, "cross_x": 35, "quarter_turn": {"value": 90, "kind": "angle"}}
feats = [rect("outline", "length", "width"), extrude("plate", "outline", "thickness"),
         {"id": "slot_outline", "op": "slot", "length_ref": "slot_length", "width_ref": "slot_width", "center_y_ref": "slot_y"},
         {"id": "slot_cutter", "op": "extrude", "profile_ref": "slot_outline", "distance_ref": "3 * thickness", "direction": "symmetric"},
         {"id": "slot_pair", "op": "mirror", "body_ref": "slot_cutter", "plane": "XZ"},
         {"id": "slotted", "op": "boolean", "operation": "cut", "target_ref": "plate", "tool_ref": "slot_pair"},
         {"id": "cross_outline", "op": "slot", "length_ref": "cross_length", "width_ref": "slot_width", "center_x_ref": "cross_x",
          "rotation_angle_ref": "quarter_turn"},
         {"id": "cross_cutter", "op": "extrude", "profile_ref": "cross_outline", "distance_ref": "3 * thickness", "direction": "symmetric"},
         {"id": "slotted_plate", "op": "boolean", "operation": "cut", "target_ref": "slotted", "tool_ref": "cross_cutter"}]
slot_a = lambda L, Wd: L * Wd + circ(Wd)  # noqa: E731
add("N14", "plate", "Plate 100x60x8 with two mirrored 30 x 8 slots and one 20 x 8 slot turned 90 degrees",
    r11("Slotted plate", params, feats, ["length", "width", "thickness"]), (100, 60, 8),
    (100 * 60 - 2 * slot_a(30, 8) - slot_a(20, 8)) * 8)

# N15 quarter elbow: ring section revolved 90 degrees about Z (counter-clockwise from +X).
params = {"outer_diameter": 20, "inner_diameter": 14, "bend_radius": 40, "sweep": {"value": 90, "kind": "angle"}}
feats = [{"id": "section", "op": "circle", "plane": "XZ", "diameter_ref": "outer_diameter", "inner_diameter_ref": "inner_diameter",
          "center_x_ref": "bend_radius"},
         {"id": "elbow", "op": "revolve", "profile_ref": "section", "axis": "Z", "angle_ref": "sweep"}]
add("N15", "tube", "Quarter elbow: OD20 ID14 ring revolved 90 degrees on a 40 bend radius",
    r11("Quarter elbow", params, feats), (50, 50, 20), (circ(20) - circ(14)) * 2 * PI * 40 / 4)

assert len(fixtures) == 45, len(fixtures)
OUT.mkdir(parents=True, exist_ok=True)
for old in OUT.glob("*.json"):
    old.unlink()
for f in fixtures:
    (OUT / f"{f['id']}.json").write_text(json.dumps(f, indent=2), encoding="utf-8")
print(f"wrote {len(fixtures)} fixtures to {OUT}")
