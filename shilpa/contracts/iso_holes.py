"""ISO metric hole dimensions for the hole series (IR 1.1), encoded from the standards.

- Clearance holes: ISO 273, fine / medium / coarse series.
- Counterbores for ISO 4762 socket head cap screws: diameter and depth per DIN 974-1
  (head diameter dk max plus clearance; depth = head height k plus about 0.4-0.6 mm).
- Countersinks for ISO 10642 countersunk socket screws: 90 deg, diameter = theoretical
  head diameter dk max (ISO 10642 has no M18).
- Tapped holes: coarse pitch per ISO 261, tap drill per ISO 2306 (about d - P).

Values are millimetres, read from ``shilpa/standards/data/iso_metric_holes.csv``. Engineers
can override any value with an explicit *_ref.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..standards import table


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


def _hole(row: dict) -> MetricHole:
    clearance = {k: float(row[f"clearance_{k}"]) for k in ("fine", "medium", "coarse")}
    csk = row["csk_d"]
    return MetricHole(row["size"], float(row["nominal_d"]), float(row["pitch"]), float(row["tap_drill"]), clearance,
                      float(row["cbore_d"]), float(row["cbore_depth"]), None if csk is None else float(csk))


# Size -> hole data, from shilpa/standards/data/iso_metric_holes.csv (sources in sources.json).
TABLE: dict[str, MetricHole] = {row["size"]: _hole(row) for row in table("iso_metric_holes.csv")}


def lookup(size: str) -> MetricHole:
    return TABLE[size]
