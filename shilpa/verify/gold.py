"""Gold requirement tests derived offline from a recipe, and a one-call ``verify_part``.

A recipe already says what the part must be: its ``Assertions`` (solid count, overall
size, analytic volume, hole counts) and its hole-series features (how many holes, of
what drill diameter, through or blind, on which pitch circle or edge offset). This
module turns those facts into ``RequirementTest`` objects that judge geometry alone, so
a nominal recipe yields an executable suite without a model in the loop (no LLM, no
network; unlike ``testgen`` this module never imports ``shilpa.agent``).

Frame. ``requirements`` measures in a canonical pose (X the longer horizontal side,
centred on X=Y=0, bottom at Z=0, positions compared up to sign). Only tests that are
invariant under that pose are derived from the recipe alone: sorted bounding box,
counts, diameters, axial depths, distances between hole axes, distance of a hole to
the nearest bounding-box side, pitch circle about the part centre. Absolute hole
positions need the final bounding box, so they are derived only when a nominal build
is given, by pushing the recipe's hole centres through the same canonical transform.

Diameters. A counterbore, countersink or tapped hole is measured at its drill (tap
drill) diameter, the compiled ``diameter_ref``; a counterbore also leaves a second,
shorter full cylinder at the counterbore diameter. Hole counts are summed per diameter
over every source (hole features, tube bores, shaft bores) because the measurement
cannot tell which feature made a cylinder.

Sanity filter. With a nominal ``BuildResult`` the derived suite is run on the nominal
part. A failing hole count that sees more holes than derived (another feature made a
cylinder of the same diameter) is relaxed to ``op: ge``; any other failing test is
dropped and reported in ``DerivedSuite.dropped`` with the measured value, never
silently.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import build123d as bd

from ..contracts.compile import CompiledRecipe, compile_recipe
from .requirements import LEN_TOL, RequirementTest, SuiteResult, run_tests

# Hole entry side -> global drilling axis and the global axes of the in-face (u, v) centre.
_SIDE_AXIS = {"top": "z", "bottom": "z", "x_min": "x", "x_max": "x", "y_min": "y", "y_max": "y"}
_SIDE_UV = {"top": (0, 1), "bottom": (0, 1), "x_min": (1, 2), "x_max": (1, 2), "y_min": (0, 2), "y_max": (0, 2)}
# Sketch plane -> (axis of an extrusion along the normal, global axes of sketch x and y).
_PLANE_AXIS = {"XY": ("z", (0, 1)), "XZ": ("y", (0, 2)), "YZ": ("x", (1, 2))}
_BODY_TRANSFORMS = {"mirror", "linear_pattern", "polar_pattern"}
_HOLE_OPS = {"hole", "corner_hole_pattern", "linear_hole_pattern", "polar_hole_pattern"}


# ---------------------------------------------------------------- verify_part


def _shape_from(source) -> Any:
    """STEP path, build123d shape, or anything with a ``.shape`` (a BuildResult)."""
    if source is None:
        raise ValueError("no geometry given")
    if isinstance(source, (str, Path)):
        p = Path(source)
        if not p.is_file():
            raise FileNotFoundError(f"STEP file not found: {p}")
        if p.suffix.lower() not in (".step", ".stp"):
            raise ValueError(f"expected a .step/.stp file, got {p.name}")
        return bd.import_step(str(p))
    if isinstance(source, bd.Shape):
        return source
    if hasattr(source, "shape"):
        if source.shape is None:
            err = getattr(source, "error", None)
            msg = getattr(getattr(err, "info", None), "message", None) or err
            raise ValueError(f"build has no shape{f': {msg}' if msg else ''}")
        return source.shape
    raise TypeError(f"cannot verify a {type(source).__name__}; pass a STEP path, a build123d shape or a BuildResult")


def _coerce_tests(tests) -> list[RequirementTest]:
    if isinstance(tests, DerivedSuite):
        tests = tests.tests
    if isinstance(tests, (RequirementTest, dict)):
        tests = [tests]
    out = []
    for i, t in enumerate(tests):
        if isinstance(t, RequirementTest):
            out.append(t)
            continue
        try:
            out.append(RequirementTest.model_validate(t))
        except Exception as exc:
            tid = t.get("id") if isinstance(t, dict) else None
            raise ValueError(f"requirement test #{i}{f' ({tid})' if tid else ''} is malformed: {exc}") from exc
    return out


def verify_part(step_or_shape, requirement_tests, canonical: bool = True) -> SuiteResult:
    """Run requirement tests against a STEP path, a build123d shape or a BuildResult.

    ``requirement_tests`` may be RequirementTest objects, dicts, a single test or a
    ``DerivedSuite``. Raises FileNotFoundError / ValueError / TypeError for an unusable
    source or a malformed test; a geometry that loads but fails tests is a SuiteResult.
    """
    tests = _coerce_tests(requirement_tests)
    shape = _shape_from(step_or_shape)
    return run_tests(tests, shape, canonical=canonical)


# ---------------------------------------------------------------- derivation


@dataclass
class DerivedSuite:
    """Tests derived from a recipe.

    ``dropped``: tests that were derived but removed, each "<id> <kind>: <reason>".
    ``notes``: tests that were kept in a weaker form (e.g. a hole count relaxed to ``ge``)
    and derivations that were skipped on purpose (e.g. holes multiplied by a mirror).
    """

    tests: list[RequirementTest] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __iter__(self):
        return iter(self.tests)

    def __len__(self) -> int:
        return len(self.tests)

    def to_dicts(self) -> list[dict]:
        return [t.model_dump(exclude_none=True) for t in self.tests]


@dataclass
class _Holes:
    """Holes of one diameter contributed by one feature."""

    source: str  # feature id
    role: str  # drill | cbore | bore
    diameter: float
    count: int
    axis: str  # global axis of the hole: x | y | z
    through: bool | None  # None: unknown (a counterbore over a drill)
    length: float | None  # expected axial length of the cylinder, when known
    centers: list[tuple[float, float, float]] | None = None  # global, axial coordinate 0
    transformed: bool = False  # multiplied or moved by a body pattern / mirror / tool boolean
    union_after: bool = False  # a later union may move the bounding box or fill a hole


def _fmt(x: float) -> str:
    return f"{x:g}"


def _to_global(uv: Iterable[float], axes: tuple[int, int]) -> tuple[float, float, float]:
    p = [0.0, 0.0, 0.0]
    for v, i in zip(uv, axes):
        p[i] = float(v)
    return (p[0], p[1], p[2])


def _feature_centers(cf, build_detail: dict | None) -> list[tuple[float, float]] | None:
    """In-face hole centres: from the build when given (corner patterns need the body's box)."""
    if build_detail and build_detail.get("centers"):
        return [tuple(c) for c in build_detail["centers"]]
    v = cf.values
    if cf.op == "hole":
        return [(v.get("center_x_ref", 0.0), v.get("center_y_ref", 0.0))]
    if cf.op == "linear_hole_pattern":
        nx, ny = int(v["count_x_ref"]), int(v["count_y_ref"])
        cx, cy = v.get("center_x_ref", 0.0), v.get("center_y_ref", 0.0)
        return [(cx + (i - (nx - 1) / 2) * v["pitch_x_ref"], cy + (j - (ny - 1) / 2) * v["pitch_y_ref"])
                for i in range(nx) for j in range(ny)]
    if cf.op == "polar_hole_pattern":
        n, rp = int(v["count_ref"]), v["pitch_diameter_ref"] / 2
        a0 = math.radians(v.get("start_angle_ref", 0.0))
        cx, cy = v.get("center_x_ref", 0.0), v.get("center_y_ref", 0.0)
        return [(cx + rp * math.cos(a0 + 2 * math.pi * k / n), cy + rp * math.sin(a0 + 2 * math.pi * k / n)) for k in range(n)]
    return None  # corner pattern without a build: centres depend on the body's bounding box


def _hole_count(cf) -> int:
    v = cf.values
    return {"hole": 1, "corner_hole_pattern": 4, "polar_hole_pattern": int(v.get("count_ref", 0)),
            "linear_hole_pattern": int(v.get("count_x_ref", 0)) * int(v.get("count_y_ref", 0))}[cf.op]


def _downstream(compiled: CompiledRecipe, fid: str) -> tuple[bool, bool, str | None]:
    """Follow a body to the output: (transformed, union_after, reason)."""
    tr, union, why, _ = _trace(compiled, fid)
    return tr, union, why


def _trace(compiled: CompiledRecipe, fid: str) -> tuple[bool, bool, str | None, set[str]]:
    """Follow a body to the output: (transformed, union_after, reason, ops applied after it)."""
    consumers: dict[str, list[tuple[Any, str]]] = defaultdict(list)
    for c in compiled.features:
        for role in ("body_ref", "target_ref", "tool_ref"):
            ref = getattr(c.spec, role, None)
            if ref:
                consumers[ref].append((c, role))
    cur, union = fid, False
    seen: set[str] = set()
    ops: set[str] = set()
    while cur != compiled.output_id and cur not in seen:
        seen.add(cur)
        cons = consumers.get(cur, [])
        if len(cons) != 1:
            return True, union, f"{fid} feeds {len(cons)} later features", ops
        c, role = cons[0]
        ops.add(c.op)
        if c.op in _BODY_TRANSFORMS:
            return True, union, f"{fid} is copied by {c.op} {c.id}", ops
        if c.op == "boolean":
            op = c.spec.operation
            if op == "intersect" or (op == "cut" and role == "tool_ref"):
                return True, union, f"{fid} is the {role.split('_')[0]} of boolean {op} {c.id}", ops
            if op == "union":
                union = True
        cur = c.id
    return False, union, None, ops


def _hole_records(compiled: CompiledRecipe, details: dict[str, dict]) -> list[_Holes]:
    out: list[_Holes] = []
    for cf in compiled.features:
        v = cf.values
        if cf.op in _HOLE_OPS:
            spec = cf.spec
            axis, uv = _SIDE_AXIS[spec.face], _SIDE_UV[spec.face]
            n = _hole_count(cf)
            cen = _feature_centers(cf, details.get(cf.id))
            centers = [_to_global(c, uv) for c in cen] if cen else None
            through = spec.mode == "through_all"
            depth = v.get("depth_ref") if not through else None
            d = v["diameter_ref"]
            drill_len = None
            if depth is not None:
                drill_len = depth - {"counterbore": v.get("cbore_depth_ref", 0.0),
                                     "countersink": v.get("csk_depth", 0.0)}.get(spec.hole_type, 0.0)
            tr, un, _ = _downstream(compiled, cf.id)
            out.append(_Holes(cf.id, "drill", d, n, axis, through, drill_len, centers, tr, un))
            if spec.hole_type == "counterbore":
                out.append(_Holes(cf.id, "cbore", v["cbore_diameter_ref"], n, axis, None, v["cbore_depth_ref"],
                                  centers, tr, un))
        elif cf.op == "stepped_shaft" and "bore_diameter_ref" in v:
            tr, un, _ = _downstream(compiled, cf.id)
            if un:  # a body merged onto the shaft can interrupt the bore
                continue
            out.append(_Holes(cf.id, "bore", v["bore_diameter_ref"], 1, "z", True, None, [(0.0, 0.0, 0.0)], tr, un))
        elif cf.op == "extrude":
            prof = next((p for p in compiled.features if p.id == cf.spec.profile_ref), None)
            if prof is not None and prof.op == "circle" and "inner_diameter_ref" in prof.values:
                axis, uv = _PLANE_AXIS[prof.spec.plane]
                c = _to_global((prof.values.get("center_x_ref", 0.0), prof.values.get("center_y_ref", 0.0)), uv)
                tr, un, _ = _downstream(compiled, cf.id)
                if un:  # spokes or a hub merged into a ring interrupt its bore
                    continue
                out.append(_Holes(cf.id, "bore", prof.values["inner_diameter_ref"], 1, axis, True, None, [c], tr, un))
    return out


class _Builder:
    def __init__(self, prefix: str):
        self.prefix = prefix
        self.tests: list[RequirementTest] = []

    def add(self, requirement: str, kind: str, **args) -> RequirementTest:
        tol = args.pop("_tol", None)
        rel = args.pop("_rel_tol", None)
        t = RequirementTest(id=f"{self.prefix}-{len(self.tests) + 1:02d}", requirement=requirement, kind=kind,
                            args={k: v for k, v in args.items() if v is not None}, tol=tol, rel_tol=rel)
        self.tests.append(t)
        return t


def _canonical_transform(shape):
    """The pose ``requirements.canonicalize`` applies, as a function on global points."""
    bb = shape.bounding_box()
    rotated = bb.size.Y > bb.size.X + LEN_TOL
    c = bb.center()

    def f(p: tuple[float, float, float]) -> tuple[float, float, float]:
        x, y, z = p[0] - c.X, p[1] - c.Y, p[2] - bb.min.Z
        return (-y, x, z) if rotated else (x, y, z)

    return f, rotated


def _plane_xy(p: tuple[float, float, float], axis: str) -> tuple[float, float]:
    return {"z": (p[0], p[1]), "x": (p[1], p[2]), "y": (p[0], p[2])}[axis]


def _key(d: float) -> float:
    return round(d, 3)


def derive_tests(recipe_or_compiled, build=None, prefix: str = "A", fillets: bool = True,
                 nominal: bool = False) -> DerivedSuite:
    """Derive offline requirement tests from a recipe (dict, JSON, Recipe or CompiledRecipe).

    ``build``: an optional nominal ``BuildResult`` of the same recipe. When given it adds
    hole-position tests (canonical frame), fillet/chamfer size tests (``fillets``) and
    runs the suite on the nominal part, relaxing or dropping any test that fails there.
    ``nominal``: also pin overall size and volume to the nominal build when the recipe's
    assertions do not state them (makes the suite a regression oracle for that build).
    """
    if isinstance(recipe_or_compiled, CompiledRecipe):
        compiled = recipe_or_compiled
    elif hasattr(recipe_or_compiled, "compiled") and hasattr(recipe_or_compiled, "shape"):
        build = build or recipe_or_compiled
        compiled = recipe_or_compiled.compiled
    else:
        compiled = compile_recipe(recipe_or_compiled)
    if build is not None and not getattr(build, "ok", build.shape is not None):
        raise ValueError("the nominal build failed; derive without build= or fix the recipe")

    B = _Builder(prefix)
    suite = DerivedSuite()
    av = compiled.assertion_values

    # -- assertions
    if av.get("valid_brep", True) and av.get("solid_count", 1) == 1:
        B.add("valid closed B-rep with one solid", "valid_solid")
    B.add(f"{av.get('solid_count', 1)} solid(s)", "solid_count", count=int(av.get("solid_count", 1)))
    bbox = av.get("bbox")
    if bbox:
        B.add("overall size " + " x ".join(_fmt(x) for x in bbox), "bbox", values=[float(x) for x in bbox])
    if av.get("volume") is not None:
        B.add(f"volume {_fmt(av['volume'])} mm^3", "volume", value=float(av["volume"]))
    if nominal and build is not None:
        s = build.shape
        if not bbox:
            bb = s.bounding_box()
            vals = [round(bb.size.X, 6), round(bb.size.Y, 6), round(bb.size.Z, 6)]
            B.add("overall size (nominal build)", "bbox", values=vals)
        if av.get("volume") is None:
            B.add("volume (nominal build)", "volume", value=round(float(s.volume), 6))

    # -- holes
    details = {fr.id: fr.detail for fr in build.features if fr.status == "ok"} if build is not None else {}
    records = _hole_records(compiled, details)
    for r in records:
        if r.transformed:
            _, _, why = _downstream(compiled, r.source)
            suite.notes.append(f"no hole tests for Ø{_fmt(r.diameter)} from {r.source}: {why}")
    groups: dict[float, list[_Holes]] = defaultdict(list)
    for r in records:
        groups[_key(r.diameter)].append(r)
    unsafe = {k for k, rs in groups.items() if any(r.transformed for r in rs)}

    asserted: dict[float, int] = {}
    for h in av.get("holes", []):
        k = _key(h["diameter"])
        asserted[k] = asserted.get(k, 0) + int(h["count"])
    for k, n in asserted.items():
        B.add(f"{n} x Ø{_fmt(k)} holes (assertion)", "hole_count", diameter=k, count=n)

    for k, rs in sorted(groups.items()):
        if k in unsafe:
            continue
        n = sum(r.count for r in rs)
        srcs = ", ".join(sorted({r.source for r in rs}))
        modes = {r.through for r in rs}
        if k in asserted:
            if asserted[k] != n:
                suite.notes.append(f"Ø{_fmt(k)}: assertion says {asserted[k]} holes, features give {n}; kept the assertion")
        elif len(modes) == 1 and None not in modes:
            through = modes.pop()
            B.add(f"{n} x Ø{_fmt(k)} {'through' if through else 'blind'} holes ({srcs})", "hole_count",
                  diameter=k, count=n, through=through)
        else:
            B.add(f"{n} x Ø{_fmt(k)} holes ({srcs})", "hole_count", diameter=k, count=n)
        if len(modes) > 1 and None not in modes:
            for through in (True, False):
                m = sum(r.count for r in rs if r.through is through)
                B.add(f"{m} x Ø{_fmt(k)} {'through' if through else 'blind'} holes", "hole_count",
                      diameter=k, count=m, through=through)
        if k in asserted and len(modes) == 1 and None not in modes:
            through = next(iter(modes))
            B.add(f"Ø{_fmt(k)} holes are {'through' if through else 'blind'}", "hole_count",
                  diameter=k, count=n, through=through)
        lengths = {None if r.length is None else round(r.length, 6) for r in rs}
        if len(lengths) == 1 and None not in lengths:
            L = lengths.pop()
            B.add(f"Ø{_fmt(k)} holes {_fmt(L)} deep", "hole_depth", diameter=k, value=L)

    # -- hole patterns (only when one feature owns every hole of that diameter)
    for cf in compiled.features:
        if cf.op not in _HOLE_OPS:
            continue
        k = _key(cf.values["diameter_ref"])
        rs = groups.get(k, [])
        if k in unsafe or len(rs) != 1 or rs[0].source != cf.id:
            if cf.op != "hole" and k not in unsafe:
                suite.notes.append(f"no pattern tests for {cf.id}: other features also make Ø{_fmt(k)} holes")
            continue
        v, r = cf.values, rs[0]
        if cf.op == "polar_hole_pattern" and r.count >= 2:
            # The test measures about the part centre; without a build only a pattern about the origin is safe.
            centred = v.get("center_x_ref", 0.0) == 0.0 and v.get("center_y_ref", 0.0) == 0.0
            if centred or build is not None:
                B.add(f"{r.count} x Ø{_fmt(k)} equally spaced on PCD {_fmt(v['pitch_diameter_ref'])} ({cf.id})",
                      "hole_pattern_circle", pcd=v["pitch_diameter_ref"], diameter=k, count=r.count, equal_spacing=True)
        elif cf.op == "corner_hole_pattern":
            if build is not None or not r.union_after:
                B.add(f"Ø{_fmt(k)} holes {_fmt(v['edge_offset_ref'])} from the edges ({cf.id})", "hole_edge_offset",
                      value=v["edge_offset_ref"], diameter=k)
        elif cf.op == "linear_hole_pattern" and r.count >= 2:
            nx, ny = int(v["count_x_ref"]), int(v["count_y_ref"])
            pitches = ([v["pitch_x_ref"]] if nx > 1 else []) + ([v["pitch_y_ref"]] if ny > 1 else [])
            pitches = [p for p in pitches if p > 0]
            if pitches:
                B.add(f"Ø{_fmt(k)} holes on a {_fmt(min(pitches))} pitch ({cf.id})", "hole_distance",
                      value=min(pitches), diameter=k, mode="nearest")
                if nx > 1 and ny > 1:  # overall span along the diagonal pins both pitches
                    span = math.hypot((nx - 1) * v["pitch_x_ref"], (ny - 1) * v["pitch_y_ref"])
                    B.add(f"Ø{_fmt(k)} pattern diagonal {span:.4g} ({cf.id})", "hole_distance", value=round(span, 6),
                          diameter=k, mode="any")
                else:
                    span = (max(nx, ny) - 1) * pitches[0]
                    if max(nx, ny) > 2:
                        B.add(f"Ø{_fmt(k)} pattern span {_fmt(span)} ({cf.id})", "hole_distance", value=span,
                              diameter=k, mode="any")

    # -- shells and plain cylinders (frame invariant). A union downstream splits outer cylinders
    # (they stop being full bosses); a later fillet or chamfer shortens them.
    by_id = {c.id: c for c in compiled.features}
    for cf in compiled.features:
        if cf.op not in ("shell", "stepped_shaft", "extrude"):
            continue
        v = cf.values
        tr, un, _, after = _trace(compiled, cf.id)
        shortened = bool(after & {"fillet", "chamfer"})
        if cf.op == "shell":
            # Walls of lofted, revolved or swept bodies are not between parallel planes.
            if not tr and by_id[cf.spec.body_ref].op in ("extrude", "boolean", "pocket", "fillet", "chamfer"):
                B.add(f"shell wall {_fmt(v['thickness_ref'])} ({cf.id})", "wall_thickness", value=v["thickness_ref"], mode="eq")
        elif cf.op == "stepped_shaft":
            if not tr and not un:
                for i in range(len(cf.spec.sections)):
                    d, L = v[f"sections.{i}.diameter"], v[f"sections.{i}.length"]
                    B.add(f"shaft section Ø{_fmt(d)} ({cf.id})", "cylinder", type="boss", diameter=d)
                    if not shortened:
                        B.add(f"shaft section Ø{_fmt(d)} x {_fmt(L)} long ({cf.id})", "cylinder", type="boss",
                              diameter=d, length=L)
        else:
            prof = by_id.get(cf.spec.profile_ref)
            if prof is not None and prof.op == "circle" and not tr and not un:
                d = prof.values["diameter_ref"]
                B.add(f"cylindrical body Ø{_fmt(d)} ({cf.id})", "cylinder", type="boss", diameter=d)
                if not shortened:
                    B.add(f"cylindrical body Ø{_fmt(d)} x {_fmt(v['distance_ref'])} ({cf.id})", "cylinder", type="boss",
                          diameter=d, length=v["distance_ref"])

    # -- build-dependent tests
    if build is not None:
        to_canon, rotated = _canonical_transform(build.shape)
        for k, rs in sorted(groups.items()):
            if k in unsafe or any(r.centers is None for r in rs):
                continue
            pts = []
            for r in rs:
                axis = {"x": "y", "y": "x"}.get(r.axis, r.axis) if rotated else r.axis
                pts += [[round(c, 6) for c in _plane_xy(to_canon(p), axis)] for p in r.centers]
            B.add(f"Ø{_fmt(k)} hole positions", "hole_positions", points=pts, diameter=k)
        if fillets:
            for cf in compiled.features:
                if cf.op == "fillet" and cf.spec.edges.curve != "circle":
                    B.add(f"R{_fmt(cf.values['radius_ref'])} fillet ({cf.id})", "edge_radius",
                          radius=cf.values["radius_ref"], convexity="any")
                elif cf.op == "chamfer":
                    B.add(f"{_fmt(cf.values['distance_ref'])} chamfer ({cf.id})", "chamfer", distance=cf.values["distance_ref"])
        _sanity_filter(B.tests, build.shape, suite)
    else:
        suite.tests = B.tests
    return suite


def _sanity_filter(tests: list[RequirementTest], shape, suite: DerivedSuite) -> None:
    """Keep what passes on the nominal part; relax over-counted holes; drop the rest with a reason."""
    res = run_tests(tests, shape)
    keep: list[RequirementTest] = []
    for t, r in zip(tests, res.results):
        if r.passed:
            keep.append(t)
            continue
        if t.kind == "hole_count" and (t.args.get("op") or "eq") == "eq" and isinstance(r.actual, int) \
                and r.actual > int(t.args["count"]):
            relaxed = t.model_copy(update={"args": {**t.args, "op": "ge"},
                                           "requirement": t.requirement + " (at least; other features add same-size holes)"})
            if run_tests([relaxed], shape).passed:
                keep.append(relaxed)
                suite.notes.append(f"{t.id} hole_count relaxed to >= {t.args['count']}: nominal part has {r.actual}")
                continue
        why = r.note or f"expected {r.expected}, nominal part gives {r.actual}"
        suite.dropped.append(f"{t.id} {t.kind} ({t.requirement}): {why}")
    suite.tests = keep
