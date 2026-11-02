"""Units: normalise every quantity to mm (lengths) or degrees (angles), and question implausible ones.

Spec section 3.2. Each quantity is echoed as typed and normalised ("10 m → 10 000 mm"). A bare
number takes the project default unit (mm) with provenance ``assumed``. A length more than
``SUSPECT_RATIO`` times the largest part dimension in the composition raises a *unit-suspect*
blocker with three options (the value read as mm, as cm, or kept as typed); the build waits
for the answer, and keeping the value marks it ``confirmed`` with provenance ``user``.
"""

from __future__ import annotations

import math
import re

from ..contracts.composition import Qty

LENGTH_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}
ANGLE_DEG = {"deg": 1.0, "rad": 180.0 / math.pi}
SUSPECT_RATIO = 20.0  # [Assumption] spec 3.2: configurable
MAX_LENGTH_MM = 1e7  # 10 km: anything larger is refused outright
_QTY = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(mm|cm|m|in|ft|deg|rad|°)?\s*$", re.IGNORECASE)
_SPELLED = {"millimetre": "mm", "millimeter": "mm", "millimetres": "mm", "millimeters": "mm", "centimetre": "cm",
            "centimeter": "cm", "centimetres": "cm", "centimeters": "cm", "metre": "m", "meter": "m", "metres": "m",
            "meters": "m", "inch": "in", "inches": "in", "foot": "ft", "feet": "ft", "degree": "deg", "degrees": "deg",
            "radian": "rad", "radians": "rad"}


class UnitError(ValueError):
    pass


def is_angle(unit: str) -> bool:
    return unit in ANGLE_DEG


def parse(text: str, default_unit: str = "mm") -> Qty:
    """``"10 m"`` -> Qty(value=10, unit="m", mm=10000, as_typed="10 m"). A bare number is assumed ``default_unit``."""
    raw = (text or "").strip()
    low = raw.lower()
    for word, unit in _SPELLED.items():
        if low.endswith(" " + word) or (low.endswith(word) and low[: -len(word)].strip().replace(".", "").isdigit()):
            low = low[: -len(word)].strip() + " " + unit
            break
    m = _QTY.match(low)
    if not m:
        raise UnitError(f"cannot read {raw!r} as a quantity; write a number and a unit such as 10 mm")
    unit = m.group(2)
    if unit == "°":
        unit = "deg"
    provenance = "user" if unit else "assumed"
    return normalise(Qty(value=float(m.group(1)), unit=(unit or default_unit).lower(), as_typed=raw, provenance=provenance))


def normalise(q: Qty) -> Qty:
    """Recompute ``mm`` from value and unit (degrees for angles). Never trusts a supplied ``mm``."""
    if not math.isfinite(q.value):
        raise UnitError("quantity is not a finite number")
    if q.unit in LENGTH_MM:
        mm = q.value * LENGTH_MM[q.unit]
        if abs(mm) > MAX_LENGTH_MM:
            raise UnitError(f"{_fmt(q.value)} {q.unit} is beyond the supported range")
    elif q.unit in ANGLE_DEG:
        mm = q.value * ANGLE_DEG[q.unit]
    else:  # pragma: no cover - the Unit literal already restricts this
        raise UnitError(f"unknown unit {q.unit!r}")
    as_typed = q.as_typed or f"{_fmt(q.value)} {q.unit}"
    return q.model_copy(update={"mm": round(mm, 9), "as_typed": as_typed})


def _fmt(v: float) -> str:
    return f"{v:g}" if abs(v) < 1e6 else f"{v:.0f}"


def group(v: float) -> str:
    """10000 -> '10 000' (thin grouping with a plain space, as the card shows it)."""
    if abs(v - round(v)) < 1e-9:
        return f"{int(round(v)):,}".replace(",", " ")
    return f"{v:,.3f}".rstrip("0").rstrip(".").replace(",", " ")


def echo(q: Qty) -> str:
    """'10 m -> 10 000 mm' (or '30 deg' when nothing changed)."""
    q = normalise(q)
    target = "deg" if is_angle(q.unit) else "mm"
    if q.unit == target:
        return f"{group(q.mm)} {target}"
    return f"{q.as_typed} → {group(q.mm)} {target}"


def suspect(q: Qty, scene_mm: float, ratio: float = SUSPECT_RATIO) -> dict | None:
    """A unit-suspect finding for a length more than ``ratio`` times the scene size, else None.

    Returns ``{"message", "ratio", "options": [(label, Qty), ...]}``; the options are the value read as
    mm, as cm (when it was typed in another unit) and kept as typed.
    """
    q = normalise(q)
    if is_angle(q.unit) or q.confirmed or scene_mm <= 0:
        return None
    if abs(q.mm) <= ratio * scene_mm:
        return None
    times = abs(q.mm) / scene_mm
    opts: list[tuple[str, Qty]] = []
    for unit in ("mm", "cm"):
        if unit != q.unit:
            alt = normalise(Qty(value=q.value, unit=unit, as_typed=f"{_fmt(q.value)} {unit}", provenance="user", confirmed=True))
            opts.append((f"{_fmt(q.value)} {unit}", alt))
    keep = q.model_copy(update={"provenance": "user", "confirmed": True})
    opts.append((f"Keep {_fmt(q.value)} {q.unit}", keep))
    msg = (f"You wrote {q.as_typed} ({group(q.mm)} mm). Your parts are about {group(round(scene_mm))} mm across, "
           f"so this is {times:.0f}x the assembly size. Did you mean "
           + ", ".join(label for label, _ in opts[:-1]) + f", or keep {_fmt(q.value)} {q.unit}?")
    return {"message": msg, "ratio": round(times, 1), "options": opts}
