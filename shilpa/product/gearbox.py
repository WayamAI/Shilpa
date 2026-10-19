"""Product checks and repair rules for the gearbox template ``gearbox.spur_single_v1``.

``check_gearbox`` reads the gear, shaft and bearing data from the parts as
built (catalog meta), not from the skeleton, so a check measures what was
actually made. Checks:

* ``ratio``: built ratio within ``ratio_tol_pct`` of the request (design).
* ``tooth_bending_pinion`` / ``tooth_bending_gear``: Lewis root stress (design: module).
* ``tooth_contact``: Hertz pitch-point stress (part: face width, then design: module).
* ``bearing_spacing``: at least ``bore_web_min`` of side plate between the two bearing
  housings, read from the skeleton so it reports even when overlapping bores stop the
  plates building (design: module, which spreads the shafts).
* ``pinion_bore``: the input shaft leaves a web of one module under the pinion roots (design: module).
* ``shaft_torsion_in`` / ``shaft_torsion_out`` (design: shaft diameter).
* ``bearing_life_in`` / ``bearing_life_out``: L10h against the life target
  (part: 62xx series, then design: next shaft and bearing bore).
* ``mesh``: the placed shaft axes are one centre distance apart, the gears share
  a plane and the mesh-port contracts agree.
* ``ports_on_geometry``: every declared port of every built part sits on its feature.
* ``pitch_velocity`` (warning): above ``pitch_velocity_max`` cut spur gears need a finer grade.
* ``bom_complete``, ``product_static`` and the generic assembly report
  (interference, contact, clearances to the housing, DOF).

``RULES`` maps a failed check to the repair the router applies; the router
module dispatches here for gearbox specs.
"""

from __future__ import annotations

import math
import time
import numpy as np

from ..assembly.build import AssemblyBuild
from ..contracts.assembly import contracts_compatible
from ..contracts.product import ProductSpec, check_product
from ..validators.assembly import AssemblyReport, validate_assembly
from .checks import ProductCheck, ProductReport, assembly_checks
from ..catalog.bearings import DEEP_GROOVE
from .templates import gearbox as tpl


def _meta(build: AssemblyBuild, iid: str) -> dict:
    part = build.parts.get(iid)
    return part.meta if part else {}


def _mesh(spec: ProductSpec, build: AssemblyBuild) -> ProductCheck:
    table = build.placement_table()
    if "pinion" not in table or "gear" not in table:
        return ProductCheck("mesh", False, "drivetrain", None, note="gears not placed", level="design")
    Tp, Tg = np.array(table["pinion"]), np.array(table["gear"])
    zp, zg = Tp[:3, 2], Tg[:3, 2]
    d = Tg[:3, 3] - Tp[:3, 3]
    axial = float(np.dot(d, zp))
    radial = float(np.linalg.norm(d - axial * zp))
    mp, mg = _meta(build, "pinion"), _meta(build, "gear")
    want = mp.get("module", 0) * (mp.get("teeth", 0) + mg.get("teeth", 0)) / 2
    parallel = float(np.degrees(np.arccos(min(1.0, abs(float(np.dot(zp, zg)))))))
    bad = contracts_compatible(build.parts["pinion"].ports["mesh"].contract, build.parts["gear"].ports["mesh"].contract)
    ok = abs(radial - want) <= 0.01 and abs(axial) <= 0.01 and parallel <= 0.01 and not bad
    note = (f"centre distance {radial:.3f} mm (m(z1+z2)/2 = {want:g}), axial offset {axial:.3f} mm, "
            f"axes {parallel:.3f} deg apart" + (f"; mesh contracts disagree: {bad}" if bad else ""))
    return ProductCheck("mesh", ok, "drivetrain", round(radial, 4), want, "mm", level="design",
                        responsible=["pinion", "gear"], note=note)


def _ports(build: AssemblyBuild) -> ProductCheck:
    from ..validators.ports import check_ports

    bad = []
    seen = set()
    for iid, part in build.parts.items():
        if part is None or part.solid is None or id(part) in seen:
            continue
        seen.add(id(part))
        bad += [f"{iid}.{c.name}" for c in check_ports(part) if not c.passed]
    return ProductCheck("ports_on_geometry", not bad, "static", bad or None, None, None, level="part",
                        responsible=sorted({b.split(".")[0] for b in bad}),
                        note="every declared port sits on its feature" if not bad else f"misplaced ports: {bad}")


def _bom(spec: ProductSpec, build: AssemblyBuild) -> ProductCheck:
    missing, wrong = [], []
    for leaf in spec.tree.leaves():
        for iid in leaf.instances:
            part = build.parts.get(iid)
            if part is None or part.solid is None or part.solid.volume <= 1e-6:
                missing.append(iid)
                continue
            want = "recipe" if leaf.procurement == "make" else "catalog"
            if spec.assembly.root_of(iid).source != want:
                wrong.append(f"{iid}: {leaf.procurement} part from {spec.assembly.root_of(iid).source}")
    ok = not missing and not wrong
    return ProductCheck("bom_complete", ok, "bom", {"leaves": len(spec.tree.leaves())}, None, None, level="part",
                        responsible=missing, note="; ".join(wrong) or (f"no geometry: {missing}" if missing else None))


def check_gearbox(spec: ProductSpec, build: AssemblyBuild, assembly_report: AssemblyReport | None = None,
                  run_assembly: bool = True, steps: int = 9) -> ProductReport:
    t: dict[str, float] = {}
    checks: list[ProductCheck] = []
    t0 = time.perf_counter()
    issues = check_product(spec)
    errs = [i for i in issues if i.severity == "error"]
    checks.append(ProductCheck("product_static", not errs, "static", [i.code for i in issues] or None, level="design",
                               note="; ".join(i.message for i in issues) or "tree leaves map to instances"))
    if assembly_report is None and run_assembly:
        assembly_report = validate_assembly(build)
    t["assembly"] = round(time.perf_counter() - t0, 2)
    checks += assembly_checks(spec, assembly_report)
    t0 = time.perf_counter()
    v = {k: p.value for k, p in spec.skeleton.items()}
    # From the skeleton, so it still reports when the side plates fail to build because the bores overlap.
    web = v["centre_distance"] - (DEEP_GROOVE[v["bearing_in"]][1] + DEEP_GROOVE[v["bearing_out"]][1]) / 2
    web_min = spec.targets.get("bore_web_min", 3.0)
    checks.append(ProductCheck("bearing_spacing", web >= web_min, "fit", round(web, 2), web_min, "mm", level="design",
                               responsible=["module"], note=f"side-plate web between the {v['bearing_in']} and "
                               f"{v['bearing_out']} housings at {v['centre_distance']:g} mm centres"))

    needed = {"pinion", "gear", "shaft_in", "shaft_out", "bearing_in_a", "bearing_out_a"}
    if not needed <= set(build.parts) or any(build.parts[i] is None for i in needed):
        checks.append(ProductCheck("parts_built", False, "assembly", sorted(needed - set(build.parts)),
                                   note="cannot run gearbox checks"))
        return ProductReport(False, checks, assembly_report, t)

    T, rpm, life = v["input_torque"], v["input_rpm"], v["life_hours"]
    mat =tpl.MATERIALS[v["gear_material"]]
    mp, mg = _meta(build, "pinion"), _meta(build, "gear")
    m, z1, z2, b = mp["module"], mp["teeth"], mg["teeth"], min(mp["face_width"], mg["face_width"])
    ratio = z2 / z1
    t_out = T * ratio
    err = abs(ratio - v["ratio"]) / v["ratio"] * 100
    tol = spec.targets.get("ratio_tol_pct", 2.0)
    checks.append(ProductCheck("ratio", err <= tol, "drivetrain", round(ratio, 4), v["ratio"], None, level="design",
                               responsible=["pinion_teeth"], note=f"{z1}:{z2}, {err:.2f} % from the request (max {tol:g} %)"))

    for name, z, n, torque in (("pinion", z1, rpm, T), ("gear", z2, rpm / ratio, t_out)):
        s = tpl.bending_stress(torque, m, z, b, n)
        checks.append(ProductCheck(f"tooth_bending_{name}", s <= mat["bending"], "strength", round(s, 1),
                                   mat["bending"], "MPa", level="design", responsible=["module"],
                                   note=f"Lewis, Y = {tpl.lewis_y(z):.3f}, Kv = {tpl.kv(tpl.pitch_velocity(m, z, n)):.2f}"))
    sc = tpl.contact_stress(T, m, z1, z2, b, rpm)
    need_b = tpl.face_for_contact(T, m, z1, z2, rpm, mat["contact"])
    checks.append(ProductCheck("tooth_contact", sc <= mat["contact"], "strength", round(sc, 1), mat["contact"], "MPa",
                               level="part", responsible=["face_width", "module"],
                               note=f"Hertz at the pitch point; face {b:g} mm, needs {need_b:.1f} mm at m{m:g}",
                               detail={"face_needed": need_b, "face_max": tpl.MAX_FACE_FACTOR * m}))
    d_in = mp["bore_d"]
    web = tpl.pinion_web_ok(m, z1, d_in)
    checks.append(ProductCheck("pinion_bore", web, "fit", d_in, round(m * (z1 - 2.4) - 2 * m, 2), "mm", level="design",
                               responsible=["module"], note="input shaft vs pinion root minus one module of web"))

    for side, iid, torque, n in (("in", "shaft_in", T, rpm), ("out", "shaft_out", t_out, rpm / ratio)):
        d = v[f"shaft_d_{side}"]
        tau = tpl.shaft_stress(torque, d)
        checks.append(ProductCheck(f"shaft_torsion_{side}", tau <= tpl.TAU_ALLOW, "strength", round(tau, 1),
                                   tpl.TAU_ALLOW, "MPa", level="design", responsible=[f"shaft_d_{side}"],
                                   note=f"{d:g} mm shaft at {torque:g} N.m"))
        brg = _meta(build, f"bearing_{side}_a").get("designation", "").split("-")[0]
        load = tpl.bearing_load(T, m, z1)
        hours = tpl.bearing_life_h(brg, load, n)
        checks.append(ProductCheck(f"bearing_life_{side}", hours >= life, "strength", round(hours), life, "h",
                                   level="part", responsible=[f"bearing_series_{side}", f"shaft_d_{side}"],
                                   note=f"{brg} at {load:.0f} N radial, {n:.0f} rpm (L10)"))

    checks.append(_mesh(spec, build))
    checks.append(_ports(build))
    checks.append(_bom(spec, build))
    vmax = spec.targets.get("pitch_velocity_max", 20.0)
    vp = tpl.pitch_velocity(m, z1, rpm)
    checks.append(ProductCheck("pitch_velocity", vp <= vmax, "drivetrain", round(vp, 2), vmax, "m/s",
                               severity="warning", level="design", responsible=["module", "input_rpm"]))
    t["gearbox_checks"] = round(time.perf_counter() - t0, 2)
    passed = not any(not c.passed and c.severity == "error" for c in checks)
    return ProductReport(passed, checks, assembly_report, t)


# ---------------------------------------------------------------- repair rules


def _next_module(m: float) -> float | None:
    return next((x for x in tpl.MODULES if x > m + 1e-9), None)


def _next_bore(d: float) -> int | None:
    return next((x for x in tpl.BORES if x > d + 1e-9), None)


def _module_up(spec: ProductSpec, c: ProductCheck, why: str):
    from .router import Action

    m = spec.skeleton["module"].value
    nxt = _next_module(m)
    if nxt is None:
        return f"already at the largest module ({m:g}); the duty is beyond this template"
    actions = [Action("module", nxt, "design", c.name, f"{why}: module {m:g} -> {nxt:g}", "skeleton")]
    if spec.skeleton["face_width"].source in ("router", "user"):
        actions.append(Action("face_width", None, "design", c.name, "back to 10 x the new module", "skeleton"))
    return actions


def _contact(spec: ProductSpec, c: ProductCheck):
    from .router import Action

    need, cap = c.detail["face_needed"], c.detail["face_max"]
    if need <= cap:
        new = float(math.ceil(need))
        return [Action("face_width", new, "part", c.name,
                       f"contact {c.actual} MPa > {c.target} MPa: widen both gears to {new:g} mm", "pinion")]
    return _module_up(spec, c, f"contact needs a {need:.0f} mm face (> {cap:g} mm)")


def _torsion(side: str):
    def rule(spec: ProductSpec, c: ProductCheck):
        from .router import Action

        key = f"shaft_d_{side}"
        d = spec.skeleton[key].value
        nxt = _next_bore(d)
        if nxt is None:
            return f"{d:g} mm is the largest shaft and bearing bore this template stocks"
        return [Action(key, nxt, "design", c.name, f"torsion {c.actual} MPa: shaft {d:g} -> {nxt} mm", "skeleton")]
    return rule


def _life(side: str):
    def rule(spec: ProductSpec, c: ProductCheck):
        from .router import Action

        series = f"bearing_series_{side}"
        if spec.skeleton[series].value == "60":
            return [Action(series, "62", "part", c.name, f"life {c.actual} h < {c.target:g} h: 60xx -> 62xx",
                           f"bearing_{side}")]
        key = f"shaft_d_{side}"
        d = spec.skeleton[key].value
        nxt = _next_bore(d)
        if nxt is None:
            return f"62xx at {d:g} mm is the largest bearing this template stocks"
        return [Action(key, nxt, "design", c.name, f"life {c.actual} h with 62xx: bore {d:g} -> {nxt} mm", "skeleton")]
    return rule


RULES = {
    "tooth_bending_pinion": lambda s, c: _module_up(s, c, f"pinion bending {c.actual} MPa > {c.target} MPa"),
    "tooth_bending_gear": lambda s, c: _module_up(s, c, f"gear bending {c.actual} MPa > {c.target} MPa"),
    "tooth_contact": _contact,
    "pinion_bore": lambda s, c: _module_up(s, c, "the input shaft leaves too thin a pinion web"),
    "bearing_spacing": lambda s, c: _module_up(s, c, f"bearing housings {c.actual} mm apart (min {c.target:g})"),
    "shaft_torsion_in": _torsion("in"),
    "shaft_torsion_out": _torsion("out"),
    "bearing_life_in": _life("in"),
    "bearing_life_out": _life("out"),
    "ratio": lambda s, c: "no tooth pair within tolerance between 17 and 30 pinion teeth",
}

SUGGEST = {
    "pitch_velocity": "warning only: ground (finer-grade) teeth or a helical pair for this pitch-line speed",
}

COVERED: tuple[str, ...] = ()

