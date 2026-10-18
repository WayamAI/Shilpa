"""Shilpa modeling IR, schema version 1.0 (blueprint section 8).

The IR is the contract between the planner and every CAD adapter. Every numeric
field is a ``*_ref`` string that names a parameter or is a restricted expression
over parameters (see ``expr.py``). That keeps every dimension editable by name and
makes conversational edits a parameter change rather than a geometry rewrite.

Coordinate conventions: millimetres internally, Z up. Hole, pattern and pocket
features cut downward (-Z) from the top face (max Z) of their target body.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"

FeatureId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
ParamName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Ref = Annotated[str, Field(min_length=1, max_length=200)]
Plane = Literal["XY", "XZ", "YZ"]
LengthUnit = Literal["mm", "cm", "m", "in"]
AngleUnit = Literal["deg", "rad"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Param(_Strict):
    """A named design parameter. Either a value or a derived expression."""

    value: float | None = None
    expr: Ref | None = None
    kind: Literal["length", "angle", "count", "ratio"] = "length"
    unit: LengthUnit | AngleUnit | None = None
    critical: bool = True
    source: Literal["user", "drawing", "assumed", "derived", "default"] = "user"
    note: str | None = None

    @field_validator("expr")
    @classmethod
    def _one_of(cls, v, info):
        if v is not None and info.data.get("value") is not None:
            raise ValueError("give either value or expr, not both")
        return v


class Frame(_Strict):
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    normal: tuple[float, float, float] = (0.0, 0.0, 1.0)


# ---------------------------------------------------------------- sketches


class CenteredRectangle(_Strict):
    id: FeatureId
    op: Literal["centered_rectangle"]
    plane: Plane = "XY"
    width_ref: Ref
    height_ref: Ref
    center_x_ref: Ref | None = None
    center_y_ref: Ref | None = None
    corner_radius_ref: Ref | None = None


class Circle(_Strict):
    id: FeatureId
    op: Literal["circle"]
    plane: Plane = "XY"
    diameter_ref: Ref
    center_x_ref: Ref | None = None
    center_y_ref: Ref | None = None


# ---------------------------------------------------------------- solids


class Extrude(_Strict):
    id: FeatureId
    op: Literal["extrude"]
    profile_ref: FeatureId
    distance_ref: Ref
    direction: Literal["positive_z", "negative_z", "positive_normal", "negative_normal", "symmetric"] = (
        "positive_normal"
    )
    offset_ref: Ref | None = None  # start offset along the sketch normal


class ShaftSection(_Strict):
    diameter_ref: Ref
    length_ref: Ref


class SteppedShaft(_Strict):
    """Trusted revolve primitive: coaxial cylinders stacked along +Z from offset."""

    id: FeatureId
    op: Literal["stepped_shaft"]
    sections: list[ShaftSection] = Field(min_length=1, max_length=20)
    bore_diameter_ref: Ref | None = None
    offset_ref: Ref | None = None


# ---------------------------------------------------------------- cuts

HoleMode = Literal["through_all", "blind"]


class Hole(_Strict):
    id: FeatureId
    op: Literal["hole"]
    body_ref: FeatureId
    diameter_ref: Ref
    center_x_ref: Ref | None = None
    center_y_ref: Ref | None = None
    mode: HoleMode = "through_all"
    depth_ref: Ref | None = None


class CornerHolePattern(_Strict):
    """Four holes inset ``edge_offset`` from each side of the body's XY extent."""

    id: FeatureId
    op: Literal["corner_hole_pattern"]
    body_ref: FeatureId
    diameter_ref: Ref
    edge_offset_ref: Ref
    mode: HoleMode = "through_all"
    depth_ref: Ref | None = None


class LinearHolePattern(_Strict):
    id: FeatureId
    op: Literal["linear_hole_pattern"]
    body_ref: FeatureId
    diameter_ref: Ref
    count_x_ref: Ref
    count_y_ref: Ref
    pitch_x_ref: Ref
    pitch_y_ref: Ref
    center_x_ref: Ref | None = None
    center_y_ref: Ref | None = None
    mode: HoleMode = "through_all"
    depth_ref: Ref | None = None


class PolarHolePattern(_Strict):
    id: FeatureId
    op: Literal["polar_hole_pattern"]
    body_ref: FeatureId
    diameter_ref: Ref
    count_ref: Ref
    pitch_diameter_ref: Ref
    start_angle_ref: Ref | None = None
    center_x_ref: Ref | None = None
    center_y_ref: Ref | None = None
    mode: HoleMode = "through_all"
    depth_ref: Ref | None = None


class Pocket(_Strict):
    """Rectangular pocket cut downward from the body's top face."""

    id: FeatureId
    op: Literal["pocket"]
    body_ref: FeatureId
    width_ref: Ref
    height_ref: Ref
    depth_ref: Ref
    center_x_ref: Ref | None = None
    center_y_ref: Ref | None = None
    corner_radius_ref: Ref | None = None


class Boolean(_Strict):
    id: FeatureId
    op: Literal["boolean"]
    operation: Literal["union", "cut", "intersect"]
    target_ref: FeatureId
    tool_ref: FeatureId


# ---------------------------------------------------------------- edge treatments


class EdgeSelector(_Strict):
    """Semantic edge query, re-evaluated against the current solid on every build.

    ``expected_count`` is mandatory: if the query resolves to a different number of
    edges the build fails instead of silently treating different edges.
    """

    direction: Literal["parallel_z", "perpendicular_z", "any"] = "any"
    location: Literal["top", "bottom", "between", "any"] = "any"
    curve: Literal["line", "circle", "any"] = "any"
    boundary: Literal["outer", "inner", "any"] = "any"
    expected_count: int = Field(ge=1, le=500)


class Fillet(_Strict):
    id: FeatureId
    op: Literal["fillet"]
    body_ref: FeatureId
    radius_ref: Ref
    edges: EdgeSelector


class Chamfer(_Strict):
    id: FeatureId
    op: Literal["chamfer"]
    body_ref: FeatureId
    distance_ref: Ref
    edges: EdgeSelector


Feature = Annotated[
    Union[
        CenteredRectangle,
        Circle,
        Extrude,
        SteppedShaft,
        Hole,
        CornerHolePattern,
        LinearHolePattern,
        PolarHolePattern,
        Pocket,
        Boolean,
        Fillet,
        Chamfer,
    ],
    Field(discriminator="op"),
]

SKETCH_OPS = {"centered_rectangle", "circle"}
ALL_OPS = {
    "centered_rectangle",
    "circle",
    "extrude",
    "stepped_shaft",
    "hole",
    "corner_hole_pattern",
    "linear_hole_pattern",
    "polar_hole_pattern",
    "pocket",
    "boolean",
    "fillet",
    "chamfer",
}


# ---------------------------------------------------------------- recipe


class HoleAssertion(_Strict):
    diameter_ref: Ref
    count: int = Field(ge=1)


class Assertions(_Strict):
    solid_count: int = 1
    valid_brep: bool = True
    bbox_ref: tuple[Ref, Ref, Ref] | None = None
    volume: float | None = None  # mm^3, only when an analytic oracle exists
    holes: list[HoleAssertion] = Field(default_factory=list)


class Assumption(_Strict):
    parameter: ParamName
    reason: str


class Recipe(_Strict):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    name: str | None = None
    intent: Literal["engineering_cad"] = "engineering_cad"
    units: LengthUnit = "mm"
    parameters: dict[ParamName, float | Param]
    frame: Frame = Field(default_factory=Frame)
    features: list[Feature] = Field(min_length=1, max_length=50)
    output: FeatureId | None = None
    assertions: Assertions = Field(default_factory=Assertions)
    exports: list[Literal["STEP", "STL", "GLB", "FCSTD"]] = Field(default_factory=lambda: ["STEP", "STL", "GLB"])
    assumptions: list[Assumption] = Field(default_factory=list)
