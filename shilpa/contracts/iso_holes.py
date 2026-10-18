"""ISO metric hole dimensions for the hole series (IR 1.1), encoded from the standards.

- Clearance holes: ISO 273, fine / medium / coarse series.
- Counterbores for ISO 4762 socket head cap screws: diameter and depth per DIN 974-1
  (head diameter dk max plus clearance; depth = head height k plus about 0.4-0.6 mm).
- Countersinks for ISO 10642 countersunk socket screws: 90 deg, diameter = theoretical
  head diameter dk max (ISO 10642 has no M18).
- Tapped holes: coarse pitch per ISO 261, tap drill per ISO 2306 (about d - P).

Values are millimetres. Engineers can override any value with an explicit *_ref.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricHole:
    size: str
    nominal: float
    pitch: float  # coarse
    tap_drill: float
    clearance: dict[str, float]  # ISO 273 fine / medium / coarse
    cbore_diameter: float
    cbore_depth: float
    csk_diameter: float | None
    csk_angle: float = 90.0

    @property
    def thread(self) -> str:
        return f"{self.size}x{self.pitch:g}"


def _h(size, d, p, tap, fine, medium, coarse, cb_d, cb_t, csk):
    return MetricHole(size, d, p, tap, {"fine": fine, "medium": medium, "coarse": coarse}, cb_d, cb_t, csk)


TABLE: dict[str, MetricHole] = {h.size: h for h in (
    #   size   d    P     tap   ISO 273 f/m/c        cbore d, t     csk d
    _h("M3", 3, 0.5, 2.5, 3.2, 3.4, 3.6, 6.5, 3.4, 6.72),
    _h("M4", 4, 0.7, 3.3, 4.3, 4.5, 4.8, 8.0, 4.4, 8.96),
    _h("M5", 5, 0.8, 4.2, 5.3, 5.5, 5.8, 10.0, 5.4, 11.20),
    _h("M6", 6, 1.0, 5.0, 6.4, 6.6, 7.0, 11.0, 6.4, 13.44),
    _h("M8", 8, 1.25, 6.8, 8.4, 9.0, 10.0, 15.0, 8.6, 17.92),
    _h("M10", 10, 1.5, 8.5, 10.5, 11.0, 12.0, 18.0, 10.6, 22.40),
    _h("M12", 12, 1.75, 10.2, 13.0, 13.5, 14.5, 20.0, 12.6, 26.88),
    _h("M14", 14, 2.0, 12.0, 15.0, 15.5, 16.5, 24.0, 14.6, 30.80),
    _h("M16", 16, 2.0, 14.0, 17.0, 17.5, 18.5, 26.0, 16.6, 33.60),
    _h("M18", 18, 2.5, 15.5, 19.0, 20.0, 21.0, 30.0, 18.6, None),
    _h("M20", 20, 2.5, 17.5, 21.0, 22.0, 24.0, 33.0, 20.6, 40.32),
)}


def lookup(size: str) -> MetricHole:
    return TABLE[size]
