"""Headless build123d (Open CASCADE) adapter for Shilpa IR 1.1 (blueprint sections 4.1, 7).

Each operation is a trusted implementation over validated numbers from
``compile_recipe``. The adapter never executes generated code. Preconditions that
would otherwise produce a broken but "valid" solid are checked explicitly and
reported as typed failures.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from itertools import combinations

import build123d as bd

from ..contracts.compile import CompiledFeature, CompiledRecipe, compile_recipe
from ..contracts.errors import ErrorCode, ShilpaError
from ..contracts.ir import EdgeSelector
from . import CAPABILITY_MATRIX

ADAPTER_NAME = "build123d"
CAPABILITIES: set[str] = CAPABILITY_MATRIX[ADAPTER_NAME]["operations"]
EXPORTS = {"STEP", "STL", "GLB"}

TOL = 1e-6
EPS = 1.0  # mm of overshoot for through cuts
PLANES = {"XY": bd.Plane.XY, "XZ": bd.Plane.XZ, "YZ": bd.Plane.YZ}
AXES = {"X": bd.Axis.X, "Y": bd.Axis.Y, "Z": bd.Axis.Z}
UNIT = {"X": bd.Vector(1, 0, 0), "Y": bd.Vector(0, 1, 0), "Z": bd.Vector(0, 0, 1)}
# Hole entry sides: (axis index, outward sign, in-face (u, v) axis indices).
SIDES = {"top": (2, 1, (0, 1)), "bottom": (2, -1, (0, 1)), "x_max": (0, 1, (1, 2)), "x_min": (0, -1, (1, 2)),
         "y_max": (1, 1, (0, 2)), "y_min": (1, -1, (0, 2))}
# Body ops whose tools keep the pre-1.1 rule that a boolean cut may not break a side wall.
WALL_CHECKED_TOOLS = {"extrude", "stepped_shaft"}


def engine_versions() -> dict[str, str]:
    import OCP

    return {
        "adapter": ADAPTER_NAME,
        "build123d": getattr(bd, "__version__", "unknown"),
        "ocp": getattr(OCP, "__version__", "unknown"),
    }


@dataclass
class FeatureResult:
    id: str
    op: str
    status: str  # "ok" | "failed" | "skipped"
    ms: float = 0.0
    volume: float | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class BuildResult:
    shape: bd.Part | None
    compiled: CompiledRecipe
    features: list[FeatureResult]
    error: ShilpaError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.shape is not None


def build(recipe, cancel_check=None) -> BuildResult:
    """Compile and execute a recipe. Compilation errors raise; geometry errors are returned."""
    compiled = compile_recipe(recipe, CAPABILITIES)
    objects: dict[str, object] = {}
    results: list[FeatureResult] = []
    for cf in compiled.features:
        if cancel_check and cancel_check():
            raise ShilpaError(ErrorCode.CANCELLED, "cancelled between modeling operations", feature_id=cf.id)
        t0 = time.perf_counter()
        try:
            out, detail = _OPS[cf.op](cf, objects)
        except ShilpaError as exc:
            exc.info.feature_id = exc.info.feature_id or cf.id
            results.append(FeatureResult(cf.id, cf.op, "failed", (time.perf_counter() - t0) * 1000, detail={"error": exc.info.message}))
            results += [FeatureResult(c.id, c.op, "skipped") for c in compiled.features[len(results):]]
            return BuildResult(None, compiled, results, exc)
        except Exception as exc:  # kernel exceptions from OCP
            err = ShilpaError(ErrorCode.KERNEL_FAILURE, f"{cf.op} failed in the geometry kernel: {exc}", feature_id=cf.id)
            results.append(FeatureResult(cf.id, cf.op, "failed", (time.perf_counter() - t0) * 1000, detail={"error": str(exc)}))
            results += [FeatureResult(c.id, c.op, "skipped") for c in compiled.features[len(results):]]
            return BuildResult(None, compiled, results, err)
        objects[cf.id] = out
        roots = objects.setdefault("__root__", {})
        src = cf.spec.body_ref if cf.op in ("mirror", "linear_pattern", "polar_pattern") else None
        roots[cf.id] = roots.get(src, cf.op) if src else cf.op
        if cf.meta:
            detail = {**detail, **cf.meta}
        vol = out.volume if isinstance(out, bd.Part) else None
        if isinstance(out, bd.Part):
            _check_solid(out, cf.id)
            bb = out.bounding_box()
            detail = {**detail, "bbox": {"min": [bb.min.X, bb.min.Y, bb.min.Z], "max": [bb.max.X, bb.max.Y, bb.max.Z]}}
        results.append(FeatureResult(cf.id, cf.op, "ok", (time.perf_counter() - t0) * 1000, vol, detail))
    shape = objects[compiled.output_id]
    return BuildResult(shape, compiled, results)


# ---------------------------------------------------------------- helpers


def _v(cf: CompiledFeature, name: str, default: float = 0.0) -> float:
    return cf.values.get(name, default)


def _as_part(shape) -> bd.Part:
    """Normalise kernel results (Solid, Compound, ShapeList) to a Part holding their solids."""
    if isinstance(shape, bd.Part):
        return shape
    if isinstance(shape, bd.Solid):
        return bd.Part([shape])
    return bd.Part(list(shape.solids()))


def _check_solid(part: bd.Part, fid: str) -> None:
    solids = part.solids()
    if len(solids) == 0 or part.volume <= TOL:
        raise ShilpaError(ErrorCode.KERNEL_FAILURE, "operation produced no solid volume", feature_id=fid)
    if not part.is_valid:
        raise ShilpaError(ErrorCode.KERNEL_FAILURE, "operation produced an invalid BREP", feature_id=fid)


def _bbox(part):
    return part.bounding_box()


def _sketch_plane(cf: CompiledFeature) -> bd.Plane:
    return PLANES[cf.spec.plane].offset(_v(cf, "offset_ref"))


def _segment_edges(cf: CompiledFeature, plane: bd.Plane) -> list[bd.Edge]:
    """Exact edges from the compiler's resolved segments (shared with the FreeCAD lowering)."""
    edges = []
    for s in cf.segments:
        p0, p1 = plane.from_local_coords(s.p0), plane.from_local_coords(s.p1)
        if s.kind == "line":
            edges.append(bd.Edge.make_line(p0, p1))
        else:
            edges.append(bd.Edge.make_three_point_arc(p0, plane.from_local_coords(s.mid), p1))
    return edges


def _profile_face(cf: CompiledFeature) -> bd.Face:
    from ..contracts import profile2d

    plane = _sketch_plane(cf)
    try:
        face = bd.Face(bd.Wire(_segment_edges(cf, plane)))
    except Exception as exc:
        raise ShilpaError(ErrorCode.PRECONDITION_FAILED, f"profile does not form a closed outline ({exc})", feature_id=cf.id)
    want = abs(profile2d.signed_area(cf.segments))
    # A self-crossing outline can still produce a "valid" face; its area gives it away.
    if not face.is_valid or abs(face.area - want) > 1e-6 * max(want, 1.0):
        raise ShilpaError(ErrorCode.PRECONDITION_FAILED, "profile outline crosses itself", feature_id=cf.id,
                          details={"face_area": face.area, "enclosed_area": want})
    return face


def _sketch_face(cf: CompiledFeature):
    if cf.op == "profile":
        return _profile_face(cf)
    plane = _sketch_plane(cf)
    cx, cy = _v(cf, "center_x_ref"), _v(cf, "center_y_ref")
    if cf.op == "slot":
        sk = bd.SlotCenterToCenter(cf.values["length_ref"], cf.values["width_ref"], _v(cf, "rotation_angle_ref"))
    elif cf.op == "centered_rectangle":
        w, h = cf.values["width_ref"], cf.values["height_ref"]
        r = cf.values.get("corner_radius_ref")
        if r is not None:
            if r * 2 >= min(w, h) - TOL:
                raise ShilpaError(
                    ErrorCode.PRECONDITION_FAILED,
                    f"corner radius {r:g} is too large for a {w:g} x {h:g} rectangle",
                    field="corner_radius_ref",
                )
            sk = bd.RectangleRounded(w, h, r)
        else:
            sk = bd.Rectangle(w, h)
    else:
        sk = bd.Circle(cf.values["diameter_ref"] / 2)
        if "inner_diameter_ref" in cf.values:
            sk = sk - bd.Circle(cf.values["inner_diameter_ref"] / 2)
    return plane * bd.Pos(cx, cy) * sk


def _top_faces(part, z):
    return [f for f in part.faces() if abs(f.center().Z - z) < 1e-4 and abs(abs(f.normal_at().Z) - 1) < 1e-6]


def _require_inside_top(part, footprint: bd.Sketch | bd.Face, what: str, fid: str) -> None:
    """The 2D footprint of a cut must lie entirely on the body's top face."""
    top = _bbox(part).max.Z
    faces = _top_faces(part, top)
    placed = bd.Pos(0, 0, top) * footprint
    area = sum(f.area for f in placed.faces())
    if not faces:
        raise ShilpaError(ErrorCode.PRECONDITION_FAILED, f"{what}: target body has no planar top face", feature_id=fid)
    covered = sum((placed & f).area for f in faces) if faces else 0.0
    if covered < area * (1 - 1e-6) - 1e-6:
        raise ShilpaError(
            ErrorCode.PRECONDITION_FAILED,
            f"{what} is not fully supported by the top face (clearance to an edge or existing cut is too small)",
            feature_id=fid,
            details={"footprint_area": area, "supported_area": covered},
        )


def _vec(i: int, s: float = 1.0) -> bd.Vector:
    return bd.Vector(*[s if k == i else 0.0 for k in range(3)])


def _bb_lo_hi(bb, i: int) -> tuple[float, float]:
    return (bb.min.X, bb.min.Y, bb.min.Z)[i], (bb.max.X, bb.max.Y, bb.max.Z)[i]


def side_extent(bb, side: str) -> tuple[tuple[float, float], tuple[float, float]]:
    """In-face (u, v) extent of a body for a hole entry side."""
    _, _, (iu, iv) = SIDES[side]
    return _bb_lo_hi(bb, iu), _bb_lo_hi(bb, iv)


def _side_faces(part, side: str) -> list:
    axis, sign, _ = SIDES[side]
    lo, hi = _bb_lo_hi(_bbox(part), axis)
    at = hi if sign > 0 else lo
    out = []
    for f in part.faces():
        if f.geom_type.name != "PLANE":
            continue
        n, c = f.normal_at(), f.center()
        if abs(abs((n.X, n.Y, n.Z)[axis]) - 1) < 1e-6 and abs((c.X, c.Y, c.Z)[axis] - at) < 1e-4:
            out.append(f)
    return out


def _common_area(a, b) -> float:
    if not _boxes_touch(a.bounding_box(), b.bounding_box()):
        return 0.0
    common = a & b
    return common.area if common is not None else 0.0


def _cut_holes(cf: CompiledFeature, objects, centers: list[tuple[float, float]]):
    """Drill a hole series into a body from one bounding-box side (top by default)."""
    body = _as_part(objects[cf.spec.body_ref])
    v, kind, side = cf.values, cf.spec.hole_type, cf.spec.face
    d = v["diameter_ref"]
    r = d / 2
    outer = {"counterbore": v.get("cbore_diameter_ref"), "countersink": v.get("csk_diameter_ref")}.get(kind) or d
    for (x1, y1), (x2, y2) in combinations(centers, 2):
        dist = math.hypot(x1 - x2, y1 - y2)
        if dist < TOL:
            raise ShilpaError(ErrorCode.PRECONDITION_FAILED, f"duplicate hole centre at ({x1:g}, {y1:g})", feature_id=cf.id)
        if dist <= outer + TOL:
            raise ShilpaError(
                ErrorCode.PRECONDITION_FAILED,
                f"holes at ({x1:g}, {y1:g}) and ({x2:g}, {y2:g}) overlap (spacing {dist:g} <= diameter {outer:g})",
                feature_id=cf.id,
            )
    bb = _bbox(body)
    axis, sign, (iu, iv) = SIDES[side]
    lo, hi = _bb_lo_hi(bb, axis)
    entry, extent = (hi if sign > 0 else lo), hi - lo
    inward = _vec(axis, -sign)
    points = [_vec(iu, u) + _vec(iv, w) + _vec(axis, entry) for u, w in centers]
    what = f"{kind} hole pattern of diameter {d:g}" if kind != "simple" else f"hole pattern of diameter {d:g}"
    faces = _side_faces(body, side)
    if faces:
        # The largest circle of each hole must lie on the flat entry face.
        placed = [bd.Plane(origin=p, z_dir=-inward) * bd.Face(bd.Wire([bd.Edge.make_circle(outer / 2)])) for p in points]
        area = sum(f.area for f in placed)
        covered = sum(_common_area(f, s) for f in placed for s in faces)
        if covered < area * (1 - 1e-6) - 1e-6:
            raise ShilpaError(
                ErrorCode.PRECONDITION_FAILED,
                f"{what} is not fully supported by the {side} face (clearance to an edge or existing cut is too small)",
                feature_id=cf.id,
                details={"footprint_area": area, "supported_area": covered},
            )
    else:
        # Curved entry (a cross hole in a round shaft): through holes only, and inside the silhouette box.
        if cf.spec.mode != "through_all" or kind not in ("simple", "tapped"):
            raise ShilpaError(ErrorCode.PRECONDITION_FAILED, f"the {side} side of the body is not flat; only plain "
                              "through holes can enter a curved face", feature_id=cf.id)
        (u0, u1), (w0, w1) = side_extent(bb, side)
        if any(u - r < u0 - TOL or u + r > u1 + TOL or w - r < w0 - TOL or w + r > w1 + TOL for u, w in centers):
            raise ShilpaError(ErrorCode.PRECONDITION_FAILED, f"{what} extends past the body", feature_id=cf.id)
    if cf.spec.mode == "through_all":
        depth = extent + EPS
    else:
        depth = v["depth_ref"]
        if depth >= extent - TOL:
            raise ShilpaError(
                ErrorCode.PRECONDITION_FAILED, f"blind depth {depth:g} reaches through the body; use through_all", feature_id=cf.id
            )
    tools = []
    for p in points:
        start = bd.Plane(origin=p - inward * EPS, z_dir=inward)
        tool = bd.Solid.make_cylinder(r, depth + EPS, start)
        if kind == "counterbore":
            tool = tool.fuse(bd.Solid.make_cylinder(v["cbore_diameter_ref"] / 2, v["cbore_depth_ref"] + EPS, start))
        elif kind == "countersink":
            half = math.radians(v["csk_angle_ref"] / 2)
            top_r = v["csk_diameter_ref"] / 2 + EPS * math.tan(half)
            tool = tool.fuse(bd.Solid.make_cone(top_r, r, v["csk_depth"] + EPS, start))
        tools.append(tool)
    out = _as_part(body.cut(*tools))
    removed = body.volume - out.volume
    if removed <= TOL:
        raise ShilpaError(ErrorCode.PRECONDITION_FAILED, "holes removed no material", feature_id=cf.id)
    return out, {"centers": [[round(x, 6), round(y, 6)] for x, y in centers], "diameter": d, "face": side,
                 "hole_type": kind, "removed_volume": removed}


# ---------------------------------------------------------------- operations


def op_sketch(cf, objects):
    return _sketch_face(cf), {}


def op_extrude(cf, objects):
    prof_cf = objects[cf.spec.profile_ref]
    plane = PLANES[prof_cf_plane(objects, cf)]
    d = cf.values["distance_ref"]
    direction = cf.spec.direction
    normal = plane.z_dir
    offset = _v(cf, "offset_ref")
    face = prof_cf
    if offset:
        face = bd.Pos(normal * offset) * face
    if direction == "symmetric":
        part = bd.extrude(face, amount=d / 2, both=True)
    else:
        sign = -1 if direction in ("negative_z", "negative_normal") else 1
        part = bd.extrude(face, amount=d, dir=normal * sign)
    return _as_part(part), {}


def prof_cf_plane(objects, cf) -> str:
    return objects["__planes__"][cf.spec.profile_ref]


def _faces(sketch) -> list:
    return list(sketch.faces()) if not isinstance(sketch, bd.Face) else [sketch]


def op_path(cf, objects):
    try:
        wire = bd.Wire(_segment_edges(cf, _sketch_plane(cf)))
    except Exception as exc:
        raise ShilpaError(ErrorCode.PRECONDITION_FAILED, f"path segments do not join ({exc})", feature_id=cf.id)
    return wire, {"length": wire.length}


def op_helix(cf, objects):
    v = cf.values
    if v["height_ref"] < v["pitch_ref"] / 100:
        raise ShilpaError(ErrorCode.PRECONDITION_FAILED, "helix is shorter than 1/100 of a turn", feature_id=cf.id)
    wire = bd.Edge.make_helix(v["pitch_ref"], v["height_ref"], v["diameter_ref"] / 2, center=(0, 0, _v(cf, "offset_ref")),
                              lefthand=cf.spec.left_handed)
    return wire, {"turns": v["height_ref"] / v["pitch_ref"]}


def op_revolve(cf, objects):
    from ..contracts.compile import PLANE_AXES

    sk = objects["__sketch__"][cf.spec.profile_ref]
    faces = _faces(objects[cf.spec.profile_ref])
    a, b = PLANE_AXES[sk.spec.plane]
    radial = "XYZ".index(b if cf.spec.axis == a else a)
    lo = min(_bb_lo_hi(f.bounding_box(), radial)[0] for f in faces)
    hi = max(_bb_lo_hi(f.bounding_box(), radial)[1] for f in faces)
    if lo < -TOL and hi > TOL:
        raise ShilpaError(ErrorCode.PRECONDITION_FAILED, f"profile {cf.spec.profile_ref!r} crosses the {cf.spec.axis} axis; "
                          "a revolved profile must stay on one side of its axis", feature_id=cf.id)
    angle = _v(cf, "angle_ref", 360.0)
    part = bd.revolve(faces, AXES[cf.spec.axis], angle)
    return _as_part(part), {"angle": angle}


def op_sweep(cf, objects):
    path = objects[cf.spec.path_ref]
    path_cf = objects["__sketch__"][cf.spec.path_ref]
    sk = objects["__sketch__"][cf.spec.profile_ref]
    faces = _faces(objects[cf.spec.profile_ref])
    plane = _sketch_plane(sk)
    p0 = path.position_at(0)
    if path_cf.op == "helix":
        bb = faces[0].bounding_box()
        if not (bb.min.X - TOL <= p0.X <= bb.max.X + TOL and bb.min.Z - TOL <= p0.Z <= bb.max.Z + TOL and abs(p0.Y) < TOL):
            raise ShilpaError(ErrorCode.PRECONDITION_FAILED, "the helix must start inside the profile (profile on XZ, around "
                              f"X = helix radius, Z = helix offset); it starts at ({p0.X:g}, {p0.Y:g}, {p0.Z:g})", feature_id=cf.id)
        part = bd.sweep(faces, path=path, is_frenet=True)
    else:
        t0 = path.tangent_at(0)
        if plane.z_dir.cross(t0).length > 1e-6 or abs((p0 - plane.origin).dot(plane.z_dir)) > 1e-6:
            raise ShilpaError(ErrorCode.PRECONDITION_FAILED, f"profile {cf.spec.profile_ref!r} must lie in the plane through the "
                              f"path start ({p0.X:g}, {p0.Y:g}, {p0.Z:g}) normal to the path", feature_id=cf.id)
        part = bd.sweep(faces, path=path)
    return _as_part(part), {}


def op_loft(cf, objects):
    faces = []
    for p in cf.spec.profile_refs:
        fs = _faces(objects[p])
        if len(fs) != 1:
            raise ShilpaError(ErrorCode.PRECONDITION_FAILED, f"loft section {p!r} must be a single region", feature_id=cf.id)
        faces.append(fs[0])
    return _as_part(bd.loft(faces, ruled=cf.spec.ruled)), {}


def op_stepped_shaft(cf, objects):
    n = len(cf.spec.sections)
    radii = [cf.values[f"sections.{i}.diameter"] / 2 for i in range(n)]
    lengths = [cf.values[f"sections.{i}.length"] for i in range(n)]
    bore = cf.values.get("bore_diameter_ref", 0.0) / 2
    if bore and bore >= min(radii) - TOL:
        raise ShilpaError(
            ErrorCode.PRECONDITION_FAILED, f"bore diameter {2 * bore:g} must be smaller than every section diameter", feature_id=cf.id
        )
    z0 = _v(cf, "offset_ref")
    pts = [(bore, z0)]
    z = z0
    for r, length in zip(radii, lengths):
        pts += [(r, z), (r, z + length)]
        z += length
    pts.append((bore, z))
    # Collapse consecutive duplicates (equal adjacent radii).
    clean = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - clean[-1][0]) > TOL or abs(p[1] - clean[-1][1]) > TOL:
            clean.append(p)
    profile = bd.Plane.XZ * bd.Polygon(*clean, align=None)
    part = bd.revolve(profile, bd.Axis.Z, 360)
    return _as_part(part), {"total_length": z - z0}


def op_hole(cf, objects):
    return _cut_holes(cf, objects, [(_v(cf, "center_x_ref"), _v(cf, "center_y_ref"))])


def op_corner_hole_pattern(cf, objects):
    body = _as_part(objects[cf.spec.body_ref])
    (u0, u1), (w0, w1) = side_extent(_bbox(body), cf.spec.face)
    e, r = cf.values["edge_offset_ref"], cf.values["diameter_ref"] / 2
    if e <= r + TOL:
        raise ShilpaError(
            ErrorCode.PRECONDITION_FAILED,
            f"edge offset {e:g} leaves no material around holes of diameter {2 * r:g}",
            feature_id=cf.id,
            field="edge_offset_ref",
        )
    xs = (u0 + e, u1 - e)
    ys = (w0 + e, w1 - e)
    if xs[0] >= xs[1] - TOL or ys[0] >= ys[1] - TOL:
        raise ShilpaError(ErrorCode.PRECONDITION_FAILED, "edge offset is too large for the body", feature_id=cf.id)
    centers = [(x, y) for x in xs for y in ys]
    return _cut_holes(cf, objects, centers)


def op_linear_hole_pattern(cf, objects):
    nx, ny = int(cf.values["count_x_ref"]), int(cf.values["count_y_ref"])
    px, py = cf.values["pitch_x_ref"], cf.values["pitch_y_ref"]
    cx, cy = _v(cf, "center_x_ref"), _v(cf, "center_y_ref")
    centers = [
        (cx + (i - (nx - 1) / 2) * px, cy + (j - (ny - 1) / 2) * py) for i in range(nx) for j in range(ny)
    ]
    return _cut_holes(cf, objects, centers)


def op_polar_hole_pattern(cf, objects):
    n = int(cf.values["count_ref"])
    rp = cf.values["pitch_diameter_ref"] / 2
    a0 = math.radians(_v(cf, "start_angle_ref"))
    cx, cy = _v(cf, "center_x_ref"), _v(cf, "center_y_ref")
    centers = [(cx + rp * math.cos(a0 + 2 * math.pi * k / n), cy + rp * math.sin(a0 + 2 * math.pi * k / n)) for k in range(n)]
    return _cut_holes(cf, objects, centers)


def op_pocket(cf, objects):
    body = _as_part(objects[cf.spec.body_ref])
    bb = _bbox(body)
    w, h, depth = cf.values["width_ref"], cf.values["height_ref"], cf.values["depth_ref"]
    cx, cy = _v(cf, "center_x_ref"), _v(cf, "center_y_ref")
    r = cf.values.get("corner_radius_ref")
    if depth >= bb.size.Z - TOL:
        raise ShilpaError(
            ErrorCode.PRECONDITION_FAILED, f"pocket depth {depth:g} would cut through the body (height {bb.size.Z:g})", feature_id=cf.id
        )
    if r is not None and r * 2 >= min(w, h) - TOL:
        raise ShilpaError(ErrorCode.PRECONDITION_FAILED, "pocket corner radius too large", feature_id=cf.id)
    sk = bd.RectangleRounded(w, h, r) if r else bd.Rectangle(w, h)
    footprint = bd.Pos(cx, cy) * sk
    _require_inside_top(body, footprint, "pocket", cf.id)
    # Require a wall: the pocket outline may not touch the outer boundary.
    if (cx - w / 2 <= bb.min.X + TOL) or (cx + w / 2 >= bb.max.X - TOL) or (cy - h / 2 <= bb.min.Y + TOL) or (cy + h / 2 >= bb.max.Y - TOL):
        raise ShilpaError(ErrorCode.PRECONDITION_FAILED, "pocket leaves no wall at the body boundary", feature_id=cf.id)
    tool = bd.extrude(bd.Pos(0, 0, bb.max.Z - depth) * footprint, amount=depth + EPS)
    out = _as_part(body - tool)
    return out, {"removed_volume": body.volume - out.volume}


def _boxes_touch(a, b, tol: float = 1e-6) -> bool:
    # Explicit test: BoundBox.overlaps does not mean "intersects" (it missed G2 L051).
    return (a.min.X <= b.max.X + tol and b.min.X <= a.max.X + tol and a.min.Y <= b.max.Y + tol
            and b.min.Y <= a.max.Y + tol and a.min.Z <= b.max.Z + tol and b.min.Z <= a.max.Z + tol)


def _require_cut_inside_walls(target, tool, fid: str) -> None:
    """A generic cut may not break through the target's side walls.

    Hole and pocket operations check their own footprints; this applies the same
    rule to boolean cuts so an impossible hole cannot be built as an edge notch.
    """
    for face in target.faces():
        if abs(face.normal_at().Z) > 1 - 1e-6:
            continue  # top and bottom faces are where holes and pockets enter and exit
        touched = (tool & face).area if _boxes_touch(tool.bounding_box(), face.bounding_box()) else 0.0
        if touched > 1e-6:
            raise ShilpaError(
                ErrorCode.PRECONDITION_FAILED,
                "cut breaks through a side wall of the target body; check hole positions and edge clearance, "
                "and drill openings through a side wall with a hole op on that face (x_min, x_max, y_min, y_max)",
                feature_id=fid,
                details={"breached_area": touched},
            )


def op_boolean(cf, objects):
    a, b = _as_part(objects[cf.spec.target_ref]), _as_part(objects[cf.spec.tool_ref])
    if cf.spec.operation == "cut" and objects["__root__"].get(cf.spec.tool_ref) in WALL_CHECKED_TOOLS:
        _require_cut_inside_walls(a, b, cf.id)
    if cf.spec.operation == "union":
        out = a + b
    elif cf.spec.operation == "cut":
        out = a - b
    else:
        out = a & b
    out = _as_part(out)
    if cf.spec.operation == "union" and len(out.solids()) > 1:
        raise ShilpaError(ErrorCode.PRECONDITION_FAILED, "union produced disconnected solids; the bodies do not touch", feature_id=cf.id)
    return out, {}


def op_shell(cf, objects):
    body = _as_part(objects[cf.spec.body_ref])
    openings = []
    for sel in cf.spec.open_faces:
        faces = _side_faces(body, sel.side)
        if len(faces) != sel.expected_count:
            code = ErrorCode.SELECTOR_EMPTY if not faces else ErrorCode.SELECTOR_AMBIGUOUS
            raise ShilpaError(code, f"face selector {sel.side} matched {len(faces)} planar faces but {sel.expected_count} "
                              "were expected", feature_id=cf.id, field="open_faces",
                              details={"matched": len(faces), "expected": sel.expected_count})
        openings += faces
    t = cf.values["thickness_ref"]
    amount = -t if cf.spec.direction == "inward" else t
    try:
        out = _as_part(bd.offset(body, amount=amount, openings=openings, kind=bd.Kind.INTERSECTION))
    except Exception as exc:
        raise ShilpaError(ErrorCode.KERNEL_FAILURE, f"shell of thickness {t:g} failed; the wall may be thicker than the "
                          f"local geometry allows ({exc})", feature_id=cf.id, field="thickness_ref")
    if len(out.solids()) != 1 or out.volume >= body.volume * (1 - 1e-9) and cf.spec.direction == "inward":
        raise ShilpaError(ErrorCode.KERNEL_FAILURE, f"shell of thickness {t:g} did not produce one hollow solid", feature_id=cf.id)
    return out, {"open_faces": len(openings)}


def _principal_plane(plane: str, at: float) -> bd.Plane:
    """Mirror plane at a coordinate along its own axis (z for XY, y for XZ, x for YZ)."""
    i = {"XY": 2, "XZ": 1, "YZ": 0}[plane]
    return bd.Plane(origin=_vec(i, at), z_dir=_vec(i))


def op_mirror(cf, objects):
    body = _as_part(objects[cf.spec.body_ref])
    image = _as_part(bd.mirror(body, about=_principal_plane(cf.spec.plane, _v(cf, "offset_ref"))))
    out = _as_part(body.fuse(image)) if cf.spec.keep_original else image
    return out, {"solids": len(out.solids())}


def _pattern(body: bd.Part, placements: list) -> bd.Part:
    if not placements:
        return body
    return _as_part(body.fuse(*[loc * body for loc in placements]))


def op_linear_pattern(cf, objects):
    body = _as_part(objects[cf.spec.body_ref])
    n, s = int(cf.values["count_ref"]), cf.values["spacing_ref"]
    out = _pattern(body, [bd.Location(UNIT[cf.spec.direction] * s * i) for i in range(1, n)])
    return out, {"copies": n, "solids": len(out.solids())}


def polar_step(n: int, angle: float) -> float:
    if abs(angle - 360.0) < 1e-9:
        return 360.0 / n
    return angle / (n - 1) if n > 1 else 0.0


def op_polar_pattern(cf, objects):
    body = _as_part(objects[cf.spec.body_ref])
    n = int(cf.values["count_ref"])
    step = polar_step(n, _v(cf, "angle_ref", 360.0))
    rot = {"X": lambda a: bd.Rot(a, 0, 0), "Y": lambda a: bd.Rot(0, a, 0), "Z": lambda a: bd.Rot(0, 0, a)}[cf.spec.axis]
    out = _pattern(body, [rot(step * i) for i in range(1, n)])
    return out, {"copies": n, "step_deg": step, "solids": len(out.solids())}


def select_edges(part: bd.Part, sel: EdgeSelector, diameter: float | None = None) -> list:
    bb = _bbox(part)
    zt, zb = bb.max.Z, bb.min.Z
    out = []
    for e in part.edges():
        gt = e.geom_type
        gt_name = getattr(gt, "name", str(gt)).upper()
        if sel.curve == "line" and gt_name != "LINE":
            continue
        if sel.curve == "circle" and gt_name != "CIRCLE":
            continue
        if diameter is not None and (gt_name != "CIRCLE" or abs(2 * e.radius - diameter) > 1e-6):
            continue
        p0, p1, mid = e.position_at(0), e.position_at(1), e.position_at(0.5)
        if sel.direction == "parallel_z":
            if gt_name != "LINE" or abs(abs((p1 - p0).normalized().Z) - 1) > 1e-6:
                continue
        elif sel.direction == "perpendicular_z":
            if max(abs(p0.Z - mid.Z), abs(p1.Z - mid.Z)) > 1e-6:
                continue
        zs = [p0.Z, p1.Z, mid.Z]
        if sel.location == "top" and not all(abs(z - zt) < 1e-6 for z in zs):
            continue
        if sel.location == "bottom" and not all(abs(z - zb) < 1e-6 for z in zs):
            continue
        if sel.location == "between" and (any(abs(z - zt) < 1e-6 for z in zs) or any(abs(z - zb) < 1e-6 for z in zs)):
            continue
        on_box = min(abs(mid.X - bb.min.X), abs(mid.X - bb.max.X), abs(mid.Y - bb.min.Y), abs(mid.Y - bb.max.Y)) < 1e-6
        if gt_name == "CIRCLE" and not on_box:
            # A full circle's midpoint may sit off the box; test its radius against the extent instead.
            rad = e.radius
            c = e.arc_center
            on_box = abs(c.X - bb.center().X) < 1e-6 and abs(rad - bb.size.X / 2) < 1e-6
        if sel.boundary == "outer" and not on_box:
            continue
        if sel.boundary == "inner" and on_box:
            continue
        out.append(e)
    return out


def _resolve_selector(part, sel: EdgeSelector, fid: str, diameter: float | None = None):
    edges = select_edges(part, sel, diameter)
    if not edges:
        raise ShilpaError(ErrorCode.SELECTOR_EMPTY, f"edge selector matched no edges: {sel.model_dump()}", feature_id=fid, field="edges")
    if len(edges) != sel.expected_count:
        raise ShilpaError(
            ErrorCode.SELECTOR_AMBIGUOUS,
            f"edge selector matched {len(edges)} edges but {sel.expected_count} were expected",
            feature_id=fid,
            field="edges",
            details={"matched": len(edges), "expected": sel.expected_count},
        )
    return edges


def op_fillet(cf, objects):
    body = _as_part(objects[cf.spec.body_ref])
    edges = _resolve_selector(body, cf.spec.edges, cf.id, cf.values.get("edges.diameter"))
    r = cf.values["radius_ref"]
    try:
        out = _as_part(body.fillet(r, edges))
    except Exception as exc:
        raise ShilpaError(
            ErrorCode.KERNEL_FAILURE,
            f"fillet of radius {r:g} failed on {len(edges)} edges; the radius may exceed the local geometry ({exc})",
            feature_id=cf.id,
            field="radius_ref",
            details={"radius": r},
        )
    return out, {"edges": len(edges)}


def op_chamfer(cf, objects):
    body = _as_part(objects[cf.spec.body_ref])
    edges = _resolve_selector(body, cf.spec.edges, cf.id, cf.values.get("edges.diameter"))
    d = cf.values["distance_ref"]
    try:
        out = _as_part(body.chamfer(d, None, edges))
    except Exception as exc:
        raise ShilpaError(
            ErrorCode.KERNEL_FAILURE, f"chamfer of {d:g} failed on {len(edges)} edges ({exc})", feature_id=cf.id, field="distance_ref"
        )
    return out, {"edges": len(edges)}


def _with_plane(fn):
    def wrapped(cf, objects):
        if hasattr(cf.spec, "plane"):
            objects.setdefault("__planes__", {})[cf.id] = cf.spec.plane
        objects.setdefault("__sketch__", {})[cf.id] = cf
        return fn(cf, objects)

    return wrapped


_OPS = {
    "centered_rectangle": _with_plane(op_sketch),
    "circle": _with_plane(op_sketch),
    "slot": _with_plane(op_sketch),
    "profile": _with_plane(op_sketch),
    "path": _with_plane(op_path),
    "helix": _with_plane(op_helix),
    "extrude": op_extrude,
    "stepped_shaft": op_stepped_shaft,
    "revolve": op_revolve,
    "sweep": op_sweep,
    "loft": op_loft,
    "shell": op_shell,
    "mirror": op_mirror,
    "linear_pattern": op_linear_pattern,
    "polar_pattern": op_polar_pattern,
    "hole": op_hole,
    "corner_hole_pattern": op_corner_hole_pattern,
    "linear_hole_pattern": op_linear_hole_pattern,
    "polar_hole_pattern": op_polar_hole_pattern,
    "pocket": op_pocket,
    "boolean": op_boolean,
    "fillet": op_fillet,
    "chamfer": op_chamfer,
}
assert set(_OPS) == CAPABILITIES
