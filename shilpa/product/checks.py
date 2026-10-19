"""Product-level checks for the bicycle template (roadmap layer 5 plus S4 swept-motion checks).

``check_bicycle`` measures the placed assembly with the same OCCT passes as
``validators/assembly.py`` (BRepExtrema distances, boolean commons) and adds
the checks a bicycle designer would run:

* tyre clearance to frame and fork (target from ``ProductSpec.targets``), with
  the frame or fork member nearest the tyre named so the router can repair it;
* ground contact: both tyres touch one ground plane (front-axle level error);
* steering sweep: fork, front wheel and cockpit against the frame over the lock;
* crank sweep: the crankset against the frame over a full turn;
* toe overlap: the front tyre against a shoe-toe envelope at the forward pedal
  over the lock range, reported as a warning as on many real small bikes;
* pedal ground clearance, standover, seatpost insertion, chainline;
* BOM completeness and governing standards against the built port contracts.

Every check names what it holds responsible (instances or skeleton keys) and a
``level``: ``part`` when one part's parameters can fix it, ``design`` when the
skeleton must change. Severity ``warning`` never fails the product.
"""

from __future__ import annotations

import json
import math
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import build123d as bd
import numpy as np
from OCP.BRepExtrema import BRepExtrema_DistShapeShape

from ..assembly.build import AssemblyBuild, port_matrix
from ..contracts.assembly import part_number
from ..contracts.product import ProductSpec, check_product
from ..validators.assembly import AssemblyReport, common_volume, validate_assembly

STEER_MOVING = ("fork", "front_hub", "front_rim", "front_tyre", "stem", "handlebar")
# Shoe envelope around the pedal axle (approx, EU 43 road shoe): mm behind the axle, width, gap outboard of
# the pedal-thread face, sole/cleat below the axle and toe-box height above it.
SHOE = {"heel": 30.0, "width": 100.0, "inboard": 8.0, "sole_below": 10.0, "above": 55.0}


@dataclass
class ProductCheck:
    name: str
    passed: bool
    category: str  # static | assembly | clearance | ground | motion | fit | drivetrain | bom | standards
    actual: Any = None
    target: Any = None
    unit: str | None = None
    severity: Literal["error", "warning"] = "error"
    level: Literal["part", "design"] | None = None
    responsible: list[str] = field(default_factory=list)
    note: str | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class ProductReport:
    passed: bool
    checks: list[ProductCheck]
    assembly: AssemblyReport | None = None
    timings_s: dict[str, float] = field(default_factory=dict)

    @property
    def failed(self) -> list[ProductCheck]:
        return [c for c in self.checks if not c.passed and c.severity == "error"]

    @property
    def warnings(self) -> list[ProductCheck]:
        return [c for c in self.checks if not c.passed and c.severity == "warning"]

    def check(self, name: str) -> ProductCheck:
        return next(c for c in self.checks if c.name == name)

    def summary(self) -> dict[str, str]:
        return {c.name: ("pass" if c.passed else ("warn" if c.severity == "warning" else "FAIL")) for c in self.checks}

    def to_dict(self) -> dict:
        out = {"passed": self.passed, "checks": [asdict(c) for c in self.checks], "timings_s": self.timings_s,
               "assembly": self.assembly.to_dict() if self.assembly else None}
        return json.loads(json.dumps(out, default=float))


# ---------------------------------------------------------------- geometry helpers


def _dist_points(s1, s2) -> tuple[float, np.ndarray, np.ndarray]:
    d = BRepExtrema_DistShapeShape(s1.wrapped, s2.wrapped)
    if not d.IsDone():
        raise RuntimeError("BRepExtrema failed")
    p1, p2 = d.PointOnShape1(1), d.PointOnShape2(1)
    return d.Value(), np.array([p1.X(), p1.Y(), p1.Z()]), np.array([p2.X(), p2.Y(), p2.Z()])


def _seg_dist(p: np.ndarray, a, b) -> float:
    a, b = np.array(a, float), np.array(b, float)
    ab = b - a
    t = float(np.clip((p - a).dot(ab) / ab.dot(ab), 0.0, 1.0))
    return float(np.linalg.norm(p - (a + t * ab)))


def _nearest_member(spec_fn, params: dict, p_local: np.ndarray) -> str:
    """Name of the weldment member or shell whose axis passes nearest a part-local point."""
    ws = spec_fn(params)
    nodes = ws.resolve_nodes()
    best, name = math.inf, "?"
    for m in ws.members:
        d = _seg_dist(p_local, nodes[m.start_node], nodes[m.end_node])
        if d < best:
            best, name = d, m.id
    for s in ws.shells:
        if s.node:
            d = float(np.linalg.norm(p_local - np.array(nodes[s.node])))
            if d < best:
                best, name = d, s.id
    return name


def _frame_spec(params):
    from ..weldment.bike_frame import FrameGeometry, frame_spec

    return frame_spec(FrameGeometry.model_validate(params))


def _fork_spec(params):
    from ..weldment.bike_frame import ForkGeometry, fork_spec

    return fork_spec(ForkGeometry.model_validate(params))


def _to_local(build: AssemblyBuild, iid: str, p_world: np.ndarray, T: np.ndarray | None = None) -> np.ndarray:
    T = build.matrices[iid] if T is None else T
    return (np.linalg.inv(T) @ np.append(p_world, 1.0))[:3]


def _port_world(build: AssemblyBuild, iid: str, port: str, T: np.ndarray | None = None) -> np.ndarray:
    T = build.matrices[iid] if T is None else T
    return T @ port_matrix(build.parts[iid].port(port))


def _zmin(shape) -> float:
    return shape.bounding_box(optimal=True).min.Z


# ---------------------------------------------------------------- checks


def _tyre_clearance(spec: ProductSpec, build: AssemblyBuild, tyre: str, other: str, target: float) -> ProductCheck:
    name = f"tyre_clearance[{tyre}~{other}]"
    if tyre not in build.placed or other not in build.placed:
        return ProductCheck(name, False, "clearance", note="not placed")
    d, p_tyre, p_other = _dist_points(build.placed[tyre], build.placed[other])
    overlap = 0.0
    if d <= 1e-9:
        overlap = common_volume(build.placed[tyre], build.placed[other])
        d = 0.0
    root = spec.assembly.root_of(other)
    member = _nearest_member(_frame_spec if other == "frame" else _fork_spec, root.ref.params,
                             _to_local(build, other, p_other)) if other in ("frame", "fork") else other
    # Fork crown or blades, chainstays, seat stays or seat tube decide the repair (see router.py).
    return ProductCheck(name, d >= target, "clearance", round(d, 3), target, "mm", level="design",
                        responsible=[other, member], note=f"nearest {other} member: {member}" +
                        (f"; overlapping {overlap:.1f} mm^3" if overlap else ""),
                        detail={"member": member, "deficit": round(max(0.0, target - d), 3), "overlap_mm3": round(overlap, 3),
                                "point": [round(float(c), 2) for c in p_other]})


def _ground(spec: ProductSpec, build: AssemblyBuild, tol: float) -> ProductCheck:
    gz = spec.derived["ground_z"]
    zf, zr = _zmin(build.placed["front_tyre"]), _zmin(build.placed["rear_tyre"])
    lowest = min((_zmin(s), iid) for iid, s in build.placed.items() if iid not in ("front_tyre", "rear_tyre"))
    ok = abs(zf - gz) <= tol and abs(zr - gz) <= tol and lowest[0] > gz + tol
    return ProductCheck("ground_contact", ok, "ground", {"front_tyre": round(zf - gz, 3), "rear_tyre": round(zr - gz, 3),
                                                          "front_axle_level_error": spec.derived.get("front_axle_level_error")},
                        tol, "mm", level="design", responsible=["head_tube_length", "fork_a2c", "bb_drop"],
                        note=f"ground plane z = {gz:g}; lowest non-tyre point {lowest[1]} {lowest[0] - gz:.1f} mm above it",
                        detail={"ground_z": gz, "lowest_other": lowest[1]})


def _pieces(build: AssemblyBuild, iid: str) -> dict[str, Any]:
    """Part-local solids per weldment piece, or the whole part when it has no pieces."""
    part = build.parts[iid]
    return part.meta.get("pieces") or {iid: part.solid}


SAMPLE_SPACING = 1.5  # mm between surface samples in the coarse sweep pass
SWEEP_HORIZON = 25.0  # mm; sample pairs farther apart are not resolved (KD-tree queries stop there)
SAMPLE_CACHE = 256  # part-local solids whose samples are kept (a bicycle has ~40 pieces)
_SAMPLES: OrderedDict[int, tuple[Any, np.ndarray]] = OrderedDict()


def _surface_samples(solid) -> np.ndarray:
    """Points on a solid's surface about ``SAMPLE_SPACING`` apart (mesh vertices plus seeded area samples).

    Cached per part-local solid (parts are memoised by their source, so a router loop re-samples only
    rebuilt parts). The cache holds the solid itself so its ``id`` cannot be reused while cached.
    """
    key = id(solid.wrapped)
    hit = _SAMPLES.get(key)
    if hit is None or hit[0] is not solid.wrapped:
        import trimesh

        verts, tris = solid.tessellate(0.1, 0.2)
        mesh = trimesh.Trimesh(np.array([tuple(v) for v in verts]), np.array(tris), process=False)
        n = int(mesh.area / SAMPLE_SPACING**2 * 1.3) + 1
        pts, _ = trimesh.sample.sample_surface(mesh, n, seed=0)
        hit = _SAMPLES[key] = (solid.wrapped, np.vstack([mesh.vertices, pts]))
        while len(_SAMPLES) > SAMPLE_CACHE:
            _SAMPLES.popitem(last=False)
    else:
        _SAMPLES.move_to_end(key)
    return hit[1]


class _Swept:
    """Distances between moving parts and a static weldment over a set of joint poses.

    Exact BRepExtrema between coped tubes costs 0.3-3 s per pair, so a sweep first measures sampled
    surface points with a KD-tree (error below about one sample spacing), then re-measures exactly only
    the piece pairs that come within ``refine`` mm (three spacings) of the closest coarse result, each at
    its closest sampled pose, plus every pose where a pair may touch. The reported minimum is exact
    BRepExtrema at sampled poses; between poses it is not interpolated.
    """

    def __init__(self, build: AssemblyBuild, static: str):
        from scipy.spatial import cKDTree

        self.build, self.static = build, static
        T = build.matrices[static]
        self.pieces = _pieces(build, static)
        pts, labels = [], []
        for name, solid in self.pieces.items():
            p = _surface_samples(solid)
            pts.append(p @ T[:3, :3].T + T[:3, 3])
            labels += [name] * len(p)
        self.tree = cKDTree(np.vstack(pts))
        self.names = list(self.pieces)
        self.label_idx = np.array([self.names.index(n) for n in labels] + [-1])  # -1: KD-tree "no hit" index
        self.world = {n: s.moved(_loc(T)) for n, s in self.pieces.items()}

    def coarse(self, iid: str, T: np.ndarray) -> list[tuple[float, str, str]]:
        """(distance, moving piece, static piece) for every static piece within the horizon of each moving piece."""
        out = []
        for name, solid in _pieces(self.build, iid).items():
            p = _surface_samples(solid) @ T[:3, :3].T + T[:3, 3]
            d, idx = self.tree.query(p, k=1, distance_upper_bound=SWEEP_HORIZON, workers=-1)
            hit = np.isfinite(d)
            if not hit.any():
                continue
            dmin = np.full(len(self.names), np.inf)
            np.minimum.at(dmin, self.label_idx[idx[hit]], d[hit])
            out += [(float(dmin[k]), name, self.names[k]) for k in np.flatnonzero(np.isfinite(dmin))]
        return out

    def exact(self, iid: str, piece: str, static_piece: str, T: np.ndarray) -> float:
        solid = _pieces(self.build, iid)[piece].moved(_loc(T))
        return BRepExtrema_DistShapeShape(solid.wrapped, self.world[static_piece].wrapped).Value()

    def sweep(self, poses: list[tuple[float, dict]], moving: tuple[str, ...], refine: float = 3 * SAMPLE_SPACING):
        rows = []
        for value, T in poses:
            for mv in moving:
                if mv in self.build.placed:
                    rows += [(d, value, mv, pc, sp) for d, pc, sp in self.coarse(mv, T[mv])]
        if not rows:
            return SWEEP_HORIZON, None, None, []  # nothing within the horizon: clearance is at least that
        floor = min(r[0] for r in rows)
        # Refine each near pair once, at its closest pose, plus every pose that may be in contact (so the
        # router learns the first contact angle). Pairs that stay equally close over the sweep (crown to
        # head tube while steering, chainring to chainstay while pedalling) cost one exact call, not one per pose.
        nearest: dict[tuple, tuple] = {}
        for r in rows:
            key = (r[2], r[3], r[4])
            if r[0] <= floor + refine and (key not in nearest or r[0] < nearest[key][0]):
                nearest[key] = r
        todo = {(r[1], *k) for k, r in nearest.items()} | {(r[1], r[2], r[3], r[4]) for r in rows if r[0] <= SAMPLE_SPACING}
        exact = []
        for value, mv, pc, sp in sorted(todo, key=lambda t: (t[0], t[1], t[2], t[3])):
            T = dict(poses)[value]
            exact.append({"value": round(value, 2), "pair": f"{mv}.{pc}+{self.static}.{sp}",
                          "distance": round(self.exact(mv, pc, sp, T[mv]), 3)})
        best = min(exact, key=lambda r: r["distance"])
        return best["distance"], best["value"], best["pair"], exact


def _loc(T: np.ndarray):
    from ..assembly.build import to_location

    return to_location(T)


def _steering(spec: ProductSpec, build: AssemblyBuild, steps: int) -> ProductCheck:
    lock = float(spec.value("steer_lock"))
    angles = [float(a) for a in np.linspace(-lock, lock, steps)]
    poses = [(a, build.pose({"steering": {"angle": a}})) for a in angles]
    d, at, pair, rows = _Swept(build, "frame").sweep(poses, ("front_tyre", "fork", "handlebar", "stem"))
    hits = sorted({r["value"] for r in rows if r["distance"] <= 1e-6}, key=abs)
    target = spec.targets.get("steer_clearance_min", 0.0)
    return ProductCheck("steering_sweep", d > target, "motion", round(d, 3), target, "mm", level="design",
                        responsible=["steer_lock", pair.split(".")[0] if pair else "fork"],
                        note=(f"min distance over +-{lock:g} deg at {at:g} deg ({pair})" if pair else
                              f"nothing within {SWEEP_HORIZON:g} mm over +-{lock:g} deg") + (f"; contact at {hits}" if hits else ""),
                        detail={"lock": lock, "contact_angles": hits, "min_at": at, "pair": pair, "refined": len(rows)})


def _cranks(spec: ProductSpec, build: AssemblyBuild, steps: int) -> ProductCheck:
    angles = [float(a) for a in np.linspace(0, 360, steps, endpoint=False)]
    poses = [(a, build.pose({"cranks": {"angle": a}})) for a in angles]
    d, at, pair, _ = _Swept(build, "frame").sweep(poses, ("crankset",))
    target = spec.targets.get("crank_clearance_min", 2.0)
    return ProductCheck("crank_sweep", d >= target, "motion", round(d, 3), target, "mm", level="design",
                        responsible=["cs_bend", "q_factor", "chainline"],
                        note=f"min crankset-frame distance at {at:g} deg ({pair})" if pair else
                        f"nothing within {SWEEP_HORIZON:g} mm over a full turn")


def _toe_box(build: AssemblyBuild, T_crank: np.ndarray, side: str, toe_reach: float) -> bd.Solid:
    """Shoe envelope on the forward pedal, world-aligned: from the heel side of the pedal axle to
    ``toe_reach`` ahead of it, outboard of the crank arm face, sole to upper."""
    P = _port_world(build, "crankset", "pedal_right" if side == "right" else "pedal_left", T_crank)
    px, py, pz = P[:3, 3]
    out = 1.0 if py > 0 else -1.0  # left foot on +Y
    y0 = py + out * SHOE["inboard"]
    y1 = y0 + out * SHOE["width"]
    lo = (px - SHOE["heel"], min(y0, y1), pz - SHOE["sole_below"])
    return bd.Solid.make_box(SHOE["heel"] + toe_reach, SHOE["width"], SHOE["sole_below"] + SHOE["above"], bd.Plane(origin=lo))


def _toe_overlap(spec: ProductSpec, build: AssemblyBuild, steps: int) -> ProductCheck:
    reach = spec.targets.get("toe_reach", 95.0)
    lock = float(spec.value("steer_lock"))
    worst = (math.inf, None, None)
    overlaps = []
    for side, crank_angle in (("right", 0.0), ("left", 180.0)):
        T = build.pose({"cranks": {"angle": crank_angle}})
        toe = _toe_box(build, T["crankset"], side, reach)
        for a in np.linspace(-lock, lock, steps):
            Ts = build.pose({"steering": {"angle": float(a)}})
            tyre = build.world_solid("front_tyre", Ts["front_tyre"])
            d = BRepExtrema_DistShapeShape(tyre.wrapped, toe.wrapped).Value()
            if d < worst[0]:
                worst = (d, float(a), side)
            if d <= 1e-6:
                overlaps.append({"side": side, "steer": round(float(a), 2)})
    d0 = worst[0]
    ok = d0 > spec.targets.get("toe_overlap_min", 0.0)
    return ProductCheck("toe_overlap", ok, "fit", round(d0, 3), spec.targets.get("toe_overlap_min", 0.0), "mm",
                        severity="warning", level="design", responsible=["fork_offset", "reach", "crank_length"],
                        note=(f"front tyre reaches the {worst[2]} shoe toe ({reach:g} mm ahead of the pedal axle) when steered to "
                              f"{sorted({o['steer'] for o in overlaps}, key=abs)[0]:g} deg; usual on small frames, only at walking-pace "
                              "steering angles" if overlaps else f"closest {d0:.1f} mm at {worst[1]:g} deg ({worst[2]} foot)"),
                        detail={"overlaps": overlaps[:8], "toe_reach": reach})


def _pedal_ground(spec: ProductSpec, build: AssemblyBuild) -> ProductCheck:
    T = build.pose({"cranks": {"angle": 90.0}})  # drive arm straight down
    z = _zmin(build.world_solid("crankset", T["crankset"])) - spec.derived["ground_z"]
    target = spec.targets.get("pedal_ground_min", 60.0)
    return ProductCheck("pedal_ground_clearance", z >= target, "fit", round(z, 2), target, "mm", level="design",
                        responsible=["bb_drop", "crank_length"], note="crank arm tip above the ground, arm down (no pedal body)")


def _standover(spec: ProductSpec) -> ProductCheck:
    from ..weldment.bike_frame import FrameGeometry, frame_nodes

    params = spec.assembly.instance("frame").ref.params
    g = FrameGeometry.model_validate(params)
    nodes, _ = frame_nodes(g)
    mid = (np.array(nodes["tt_front"]) + np.array(nodes["tt_rear"])) / 2
    standover = mid[2] + g.tt[0] / 2 + spec.derived["bb_height"]
    inseam = float(spec.value("rider_inseam")) * 10
    gap = inseam - standover
    target = spec.targets.get("standover_min", 20.0)
    return ProductCheck("standover", gap >= target, "fit", round(gap, 1), target, "mm",
                        severity="error" if gap < 0 else "warning", level="design", responsible=["size", "stack", "tt_slope"],
                        note=f"top-tube top at mid length {standover:.0f} mm above ground vs inseam {inseam:.0f} mm"
                             + ("" if spec.skeleton["rider_inseam"].source == "user" else " (inseam estimated)"),
                        detail={"standover_mm": round(standover, 1), "inseam_mm": inseam})


def _seatpost(spec: ProductSpec, build: AssemblyBuild) -> ProductCheck:
    mate = next(m for m in spec.assembly.mates if m.name == "seatpost")
    insertion = -mate.offset
    min_ins = float(spec.value("seatpost_min_insertion"))
    usable = float(spec.value("seat_tube_length")) - 90.0
    ok = min_ins <= insertion <= usable
    level = "part"
    return ProductCheck("seatpost_insertion", ok, "fit", round(insertion, 1), [min_ins, round(usable, 1)], "mm", level=level,
                        responsible=["seatpost", "seatpost_length"],
                        note=f"{spec.value('seatpost_length'):g} mm post, saddle height {spec.value('saddle_height'):.0f} mm",
                        detail={"insertion": insertion, "min": min_ins, "usable": usable})


def _chainline(spec: ProductSpec, build: AssemblyBuild) -> ProductCheck:
    part = build.parts["crankset"]
    rings = [n for n in part.ports if n.startswith("chainring_")]
    ys = [float(_port_world(build, "crankset", n)[1, 3]) for n in rings]
    front = -sum(ys) / len(ys)  # drive side is -Y
    rear = -float(_port_world(build, "rear_hub", "cassette")[1, 3])
    tol = spec.targets.get("chainline_tol", 2.5)
    diff = front - rear
    return ProductCheck("chainline", abs(diff) <= tol, "drivetrain", round(diff, 2), tol, "mm", level="part",
                        responsible=["crankset", "chainline"], note=f"front ring-pack centre {front:.1f} mm, cassette centre {rear:.1f} mm",
                        detail={"front": front, "rear": rear})


def _bom(spec: ProductSpec, build: AssemblyBuild) -> ProductCheck:
    missing, wrong_source = [], []
    for leaf in spec.tree.leaves():
        for iid in leaf.instances:
            part = build.parts.get(iid)
            if part is None or part.solid is None or part.solid.volume <= 1e-6:
                missing.append(iid)
                continue
            root = spec.assembly.root_of(iid)
            want = "weldment" if leaf.procurement == "make" else "catalog"
            if root.source != want:
                wrong_source.append(f"{iid}: {leaf.procurement} part from {root.source}")
    lines = {part_number(spec.assembly, i.id) for i in spec.assembly.instances}
    ok = not missing and not wrong_source
    return ProductCheck("bom_complete", ok, "bom", {"lines": len(lines), "leaves": len(spec.tree.leaves())}, None, None,
                        level="part", responsible=missing, note="; ".join(wrong_source) or (f"no geometry: {missing}" if missing else None))


# Requirement standard role -> (instance, port, contract key, how to read the requirement string)
STANDARD_PORTS = {
    "bb": [("frame", "bb_shell", "shell_width", lambda s: int(s[3:])), ("bb", "spindle_axis", "shell_width", lambda s: int(s[3:]))],
    "rear_axle": [("frame", "rear_dropout", "axle", str), ("rear_hub", "axle", "axle", str)],
    "front_axle": [("fork", "front_axle", "axle", str), ("front_hub", "axle", "axle", str)],
    "seatpost": [("frame", "seat_tube_top", "seatpost_d", float), ("seatpost", "post_axis", "seatpost_d", float)],
    "bar_clamp": [("stem", "bar_clamp", "clamp_d", float), ("handlebar", "stem_clamp", "clamp_d", float)],
}


def _standards(spec: ProductSpec, build: AssemblyBuild) -> ProductCheck:
    bad = []
    for role, rows in STANDARD_PORTS.items():
        want = spec.requirements.standards.get(role)
        if want is None:
            continue
        for iid, port, key, parse in rows:
            part = build.parts.get(iid)
            got = part.ports.get(port).contract.get(key) if part and port in part.ports else None
            if got is None or str(got) != str(parse(want)) and not (isinstance(got, (int, float)) and math.isclose(got, parse(want))):
                bad.append(f"{iid}.{port} {key}={got!r} vs {role}={want}")
    return ProductCheck("standards", not bad, "standards", bad or None, dict(spec.requirements.standards), None, level="part",
                        responsible=[b.split(".")[0] for b in bad], note="; ".join(bad) or "every governing standard matches the built ports")


def check_bicycle(spec: ProductSpec, build: AssemblyBuild, assembly_report: AssemblyReport | None = None,
                  run_assembly: bool = True, steps: int = 9) -> ProductReport:
    t = {}
    checks: list[ProductCheck] = []
    t0 = time.perf_counter()
    from .templates.bicycle import ROLE_OF

    issues = check_product(spec, ROLE_OF)
    errs = [i for i in issues if i.severity == "error"]
    checks.append(ProductCheck("product_static", not errs, "static", [i.code for i in issues] or None,
                               note="; ".join(i.message for i in issues) or "tree leaves map to instances; standards consistent",
                               level="design"))
    if assembly_report is None and run_assembly:
        assembly_report = validate_assembly(build, skip_sweeps=("steering", "cranks"))  # exact sweeps below
    t["assembly"] = round(time.perf_counter() - t0, 2)
    if assembly_report is not None:
        for c in assembly_report.checks:
            if c.passed:
                continue
            resp = []
            if c.name.startswith(("interference[", "sweep[", "contact[", "part_built[")):
                inside = c.name[c.name.index("[") + 1:-1]
                resp = [x for x in inside.replace("~", "+").replace(".", "+").split("+") if x in {i.id for i in spec.assembly.instances}]
            checks.append(ProductCheck(f"assembly:{c.name}", False, "assembly", c.actual, c.requested, None, level="part",
                                       responsible=resp, note=c.note))
        checks.append(ProductCheck("assembly", assembly_report.passed, "assembly",
                                   len(assembly_report.failed), 0, None, level="part",
                                   note=None if assembly_report.passed else f"failed: {assembly_report.failed}"))
    placed = set(build.placed)
    needed = {"frame", "fork", "front_tyre", "rear_tyre", "crankset", "rear_hub", "seatpost"}
    if not needed <= placed:
        checks.append(ProductCheck("placed", False, "assembly", sorted(needed - placed), note="cannot run product checks"))
        return ProductReport(False, checks, assembly_report, t)

    t0 = time.perf_counter()
    target = spec.targets.get("tyre_clearance_min", 5.0)
    checks += [_tyre_clearance(spec, build, "front_tyre", "fork", target),
               _tyre_clearance(spec, build, "front_tyre", "frame", target),
               _tyre_clearance(spec, build, "rear_tyre", "frame", target)]
    checks.append(_ground(spec, build, spec.targets.get("ground_tol", 0.5)))
    t["static_checks"] = round(time.perf_counter() - t0, 2)
    t0 = time.perf_counter()
    checks.append(_steering(spec, build, steps))
    checks.append(_cranks(spec, build, 12))
    checks.append(_toe_overlap(spec, build, steps))
    t["sweeps"] = round(time.perf_counter() - t0, 2)
    checks += [_pedal_ground(spec, build), _standover(spec), _seatpost(spec, build), _chainline(spec, build),
               _bom(spec, build), _standards(spec, build)]
    trail = spec.derived.get("trail", 0.0)
    checks.append(ProductCheck("trail", 45.0 <= trail <= 80.0, "fit", trail, [45.0, 80.0], "mm", severity="warning",
                               level="design", responsible=["head_angle", "fork_offset"], note="handling sanity range (approx)"))
    passed = not any(not c.passed and c.severity == "error" for c in checks)
    return ProductReport(passed, checks, assembly_report, t)
