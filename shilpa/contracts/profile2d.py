"""Exact 2D geometry of profile and path segments (IR 1.1), shared by every adapter.

``resolve`` turns evaluated segment values into explicit lines and arcs (start, end,
centre, radius, direction and a point on the arc), so build123d and FreeCAD draw the
same curves and a tangent or radius arc never depends on one kernel's conventions.
Pure arithmetic: no CAD imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import ErrorCode, ShilpaError

TOL = 1e-9


@dataclass
class Seg:
    kind: str  # "line" | "arc"
    p0: tuple[float, float]
    p1: tuple[float, float]
    center: tuple[float, float] | None = None
    radius: float | None = None
    ccw: bool = True
    mid: tuple[float, float] | None = None  # a point on the arc halfway along it
    sweep: float = 0.0  # arc angle in radians, 0..2*pi
    source: int | None = None  # index of the IR segment, None for the implicit closing line

    def end_tangent(self) -> tuple[float, float]:
        return self._tangent(self.p1)

    def start_tangent(self) -> tuple[float, float]:
        return self._tangent(self.p0)

    def _tangent(self, at) -> tuple[float, float]:
        if self.kind == "line":
            return _unit(_sub(self.p1, self.p0))
        rx, ry = _sub(at, self.center)
        t = (-ry, rx) if self.ccw else (ry, -rx)
        return _unit(t)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _unit(v):
    n = math.hypot(*v)
    return (v[0] / n, v[1] / n)


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _fail(msg: str, fid: str, i: int | None) -> ShilpaError:
    return ShilpaError(ErrorCode.PRECONDITION_FAILED, msg, feature_id=fid, field=f"segments.{i}" if i is not None else "segments")


def _arc_from_center(p0, p1, c, ccw, i) -> Seg:
    r = math.hypot(*_sub(p0, c))
    a0 = math.atan2(p0[1] - c[1], p0[0] - c[0])
    a1 = math.atan2(p1[1] - c[1], p1[0] - c[0])
    sweep = (a1 - a0) % (2 * math.pi) if ccw else (a0 - a1) % (2 * math.pi)
    am = a0 + (sweep / 2 if ccw else -sweep / 2)
    return Seg("arc", p0, p1, c, r, ccw, (c[0] + r * math.cos(am), c[1] + r * math.sin(am)), sweep, i)


def resolve(start: tuple[float, float], segments: list[dict], closed: bool, fid: str) -> list[Seg]:
    """Each segment dict has kind, x, y and optionally mid_x, mid_y, radius, clockwise."""
    out: list[Seg] = []
    p = start
    for i, s in enumerate(segments):
        q = (s["x"], s["y"])
        chord = math.hypot(*_sub(q, p))
        if chord < 1e-6:
            raise _fail(f"segment {i} has zero length (ends where it starts)", fid, i)
        kind = s["kind"]
        if kind == "line":
            out.append(Seg("line", p, q, source=i))
        elif kind == "arc":
            m = (s["mid_x"], s["mid_y"])
            area2 = _cross(_sub(m, p), _sub(q, p))
            if abs(area2) < 1e-9 * max(1.0, chord * chord):
                raise _fail(f"arc segment {i}: the three points are collinear", fid, i)
            # Circumcentre of p, m, q.
            ax, ay = p
            bx, by = m
            cx, cy = q
            d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
            ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
            uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
            out.append(_arc_from_center(p, q, (ux, uy), area2 > 0, i))
        elif kind == "tangent_arc":
            if not out:
                raise _fail(f"tangent arc segment {i} has no previous segment to be tangent to", fid, i)
            t = out[-1].end_tangent()
            n = (-t[1], t[0])  # left normal
            dv = _sub(q, p)
            nd = n[0] * dv[0] + n[1] * dv[1]
            if abs(nd) < 1e-9 * chord:
                raise _fail(f"tangent arc segment {i} continues straight; use a line", fid, i)
            r_signed = (dv[0] ** 2 + dv[1] ** 2) / (2 * nd)
            c = (p[0] + n[0] * r_signed, p[1] + n[1] * r_signed)
            out.append(_arc_from_center(p, q, c, r_signed > 0, i))
        elif kind == "radius_arc":
            r = s["radius"]
            if r < chord / 2 - 1e-9:
                raise _fail(f"radius arc segment {i}: radius {r:g} is smaller than half the chord ({chord / 2:g})", fid, i)
            h = math.sqrt(max(r * r - chord * chord / 4, 0.0))
            u = _unit(_sub(q, p))
            left = (-u[1], u[0])
            ccw = not s.get("clockwise", False)
            side = 1 if ccw else -1  # the shorter arc's centre lies on the turning side
            mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
            out.append(_arc_from_center(p, q, (mx + side * h * left[0], my + side * h * left[1]), ccw, i))
        else:
            raise _fail(f"unknown segment kind {kind!r}", fid, i)
        p = q
    if closed:
        if math.hypot(*_sub(p, start)) > 1e-6:
            out.append(Seg("line", p, start))
        else:
            out[-1].p1 = start  # absorb rounding so the loop closes exactly
        if len(out) < 2 or (len(out) == 2 and all(s.kind == "line" for s in out)):
            raise _fail("a closed profile needs at least three sides or an arc", fid, None)
    return out


def require_smooth(segs: list[Seg], fid: str) -> None:
    """Sweep spines must be tangent-continuous so every adapter sweeps them the same way."""
    for i, (a, b) in enumerate(zip(segs, segs[1:]), start=1):
        if _cross(a.end_tangent(), b.start_tangent()) ** 2 > 1e-12 or sum(x * y for x, y in zip(a.end_tangent(), b.start_tangent())) < 0:
            raise ShilpaError(ErrorCode.INVALID_SCHEMA, f"path has a sharp corner before segment {i}; join straight runs with a "
                              "tangent_arc (bend radius) so the sweep stays smooth", feature_id=fid, field=f"segments.{i}")


def signed_area(segs: list[Seg]) -> float:
    """Area enclosed by a closed chain (positive when counter-clockwise)."""
    a = 0.0
    for s in segs:
        a += _cross(s.p0, s.p1) / 2
        if s.kind == "arc":
            seg_area = s.radius ** 2 / 2 * (s.sweep - math.sin(s.sweep))
            a += seg_area if s.ccw else -seg_area
    return a
