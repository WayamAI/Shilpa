"""Sheet-metal sub-IR: spec, builder (folded solid + flat pattern) and DFM checks."""

from shilpa.sheetmetal.builder import SheetMetalPart, build, build_part
from shilpa.sheetmetal.spec import (
    BendRelief,
    CornerRelief,
    Cutout,
    EdgeFlange,
    Hem,
    KFactorRow,
    PolyOutline,
    RectOutline,
    SheetMetalSpec,
    bend_allowance,
    din6935_k,
)

__all__ = [
    "BendRelief",
    "CornerRelief",
    "Cutout",
    "EdgeFlange",
    "Hem",
    "KFactorRow",
    "PolyOutline",
    "RectOutline",
    "SheetMetalPart",
    "SheetMetalSpec",
    "bend_allowance",
    "build",
    "build_part",
    "din6935_k",
]
