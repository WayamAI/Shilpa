"""Shilpa modeling IR, schema version 1.1 (blueprint section 8; 1.0 recipes stay valid).

The IR is the contract between the planner and every CAD adapter. Every numeric
field is a ``*_ref`` string that names a parameter or is a restricted expression
over parameters (see ``expr.py``). That keeps every dimension editable by name and
makes conversational edits a parameter change rather than a geometry rewrite.

Coordinate conventions: millimetres internally, Z up. Pocket features cut downward
(-Z) from the top face (max Z) of their target body. Hole features drill inward from
one bounding-box side of the body, the top face by default.

Sketch planes use the same local frames in every adapter: XY (x=X, y=Y, normal +Z),
XZ (x=X, y=Z, normal -Y) and YZ (x=Y, y=Z, normal +X). A sketch ``offset_ref`` moves
the plane along its normal.

Version 1.1 adds general profiles and slots, paths and helices, revolve, sweep, loft,
shell, mirror, body patterns and the counterbore / countersink / tapped hole series.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.1"
MAX_FEATURES = 200

FeatureId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
ParamName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Ref = Annotated[str, Field(min_length=1, max_length=200)]
Plane = Literal["XY", "XZ", "YZ"]
Axis = Literal["X", "Y", "Z"]
# Bounding-box side of a body: holes enter there, shells open there.
FaceSide = Literal["top", "bottom", "x_min", "x_max", "y_min", "y_max"]
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
    offset_ref: Ref | None = None  # plane offset along its normal


class Circle(_Strict):
    id: FeatureId
    op: Literal["circle"]
    plane: Plane = "XY"
    diameter_ref: Ref
    center_x_ref: Ref | None = None
    center_y_ref: Ref | None = None
    inner_diameter_ref: Ref | None = None  # makes a concentric ring (tube and washer sections)
    offset_ref: Ref | None = None


class Slot(_Strict):
    """Obround slot: two semicircles of diameter ``width`` whose centres are ``length`` apart."""

    id: FeatureId
    op: Literal["slot"]
    plane: Plane = "XY"
    length_ref: Ref  # centre-to-centre
    width_ref: Ref
    center_x_ref: Ref | None = None
    center_y_ref: Ref | None = None
    rotation_angle_ref: Ref | None = None  # counter-clockwise from the sketch x axis
    offset_ref: Ref | None = None


class Segment(_Strict):
    """One edge of a profile or path, from the previous point to (x, y) in sketch coordinates.

    line: straight. arc: circular arc through (mid_x, mid_y). tangent_arc: arc tangent to the
    previous segment. radius_arc: the shorter arc of radius_ref, counter-clockwise unless clockwise.
    """

    kind: Literal["line", "arc", "tangent_arc", "radius_arc"] = "line"
    x_ref: Ref
    y_ref: Ref
    mid_x_ref: Ref | None = None
    mid_y_ref: Ref | None = None
    radius_ref: Ref | None = None
    clockwise: bool = False


class Profile(_Strict):
    """General closed sketch: a chain of segments from (start_x, start_y).

    The loop is closed with a straight line if the last segment does not end at the start.
    The outline must not cross itself.
    """

    id: FeatureId
    op: Literal["profile"]
    plane: Plane = "XY"
    start_x_ref: Ref
    start_y_ref: Ref
    segments: list[Segment] = Field(min_length=1, max_length=400)
    offset_ref: Ref | None = None


# ---------------------------------------------------------------- paths (sweep spines)


class Path(_Strict):
    """Open planar chain of segments used as a sweep spine (same segment kinds as a profile)."""

    id: FeatureId
    op: Literal["path"]
    plane: Plane = "XZ"
    start_x_ref: Ref
    start_y_ref: Ref
    segments: list[Segment] = Field(min_length=1, max_length=50)
    offset_ref: Ref | None = None


class Helix(_Strict):
    """Helix about the Z axis, starting on +X at Z = offset and climbing by ``pitch`` per turn."""

    id: FeatureId
    op: Literal["helix"]
    diameter_ref: Ref
    pitch_ref: Ref
    height_ref: Ref
    offset_ref: Ref | None = None
    left_handed: bool = False


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


class Revolve(_Strict):
    """Revolve a sketch about a global axis through the origin that lies in the sketch plane."""

    id: FeatureId
    op: Literal["revolve"]
    profile_ref: FeatureId
    axis: Axis
    angle_ref: Ref | None = None  # default 360; partial revolves turn counter-clockwise about +axis


class Sweep(_Strict):
    """Sweep a sketch along a path or helix.

    For a path the sketch must sit at the path start, normal to it. For a helix the sketch is
    on the XZ plane, centred at the helix start (helix radius on +X, Z = helix offset).
    """

    id: FeatureId
    op: Literal["sweep"]
    profile_ref: FeatureId
    path_ref: FeatureId


class Loft(_Strict):
    """Loft through two or more parallel sketches on the same plane at increasing offsets."""

    id: FeatureId
    op: Literal["loft"]
    profile_refs: list[FeatureId] = Field(min_length=2, max_length=10)
    ruled: bool = False


# ---------------------------------------------------------------- cuts

HoleMode = Literal["through_all", "blind"]
HoleType = Literal["simple", "counterbore", "countersink", "tapped"]
MetricSize = Literal["M3", "M4", "M5", "M6", "M8", "M10", "M12", "M14", "M16", "M18", "M20"]


class _HoleSeries(_Strict):
    """Fields shared by every hole operation.

    Holes drill inward from ``face`` of the body's bounding box. Centres are in that face's
    coordinates: (X, Y) on top/bottom, (Y, Z) on x_min/x_max, (X, Z) on y_min/y_max.
    ``standard_size`` looks up ISO metric dimensions (clearance per ISO 273 ``fit``, counterbores
    for ISO 4762 heads, countersinks for ISO 10642 heads, tap drills for coarse threads); any
    explicit *_ref overrides the table. Tapped holes are drilled at the tap-drill diameter and
    carry the thread as metadata (no modelled thread). Depths are measured from the entry face.
    """

    # id and op lead every schema (subclasses narrow op in place): strict-mode decoding commits to a
    # union member from the leading keys, so they must name the operation first.
    id: FeatureId
    op: str
    body_ref: FeatureId
    diameter_ref: Ref | None = None  # required unless standard_size supplies it
    mode: HoleMode = "through_all"
    depth_ref: Ref | None = None
    face: FaceSide = "top"
    hole_type: HoleType = "simple"
    standard_size: MetricSize | None = None
    fit: Literal["fine", "medium", "coarse"] = "medium"
    cbore_diameter_ref: Ref | None = None
    cbore_depth_ref: Ref | None = None
    csk_diameter_ref: Ref | None = None
    csk_angle_ref: Ref | None = None  # included angle, default 90 deg
    thread_depth_ref: Ref | None = None  # tapped: usable thread length (metadata)


class Hole(_HoleSeries):
    id: FeatureId
    op: Literal["hole"]
    center_x_ref: Ref | None = None
    center_y_ref: Ref | None = None


class CornerHolePattern(_HoleSeries):
    """Four holes inset ``edge_offset`` from each side of the entry face's extent."""

    id: FeatureId
    op: Literal["corner_hole_pattern"]
    edge_offset_ref: Ref


class LinearHolePattern(_HoleSeries):
    id: FeatureId
    op: Literal["linear_hole_pattern"]
    count_x_ref: Ref
    count_y_ref: Ref
    pitch_x_ref: Ref
    pitch_y_ref: Ref
    center_x_ref: Ref | None = None
    center_y_ref: Ref | None = None


class PolarHolePattern(_HoleSeries):
    id: FeatureId
    op: Literal["polar_hole_pattern"]
    count_ref: Ref
    pitch_diameter_ref: Ref
    start_angle_ref: Ref | None = None
    center_x_ref: Ref | None = None
    center_y_ref: Ref | None = None


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


# ---------------------------------------------------------------- body operations


class FaceSelector(_Strict):
    """Planar faces lying on one side of the body's bounding box; the count must match exactly."""

    side: FaceSide
    expected_count: int = Field(default=1, ge=1, le=50)


class Shell(_Strict):
    """Hollow a body to wall ``thickness``, removing the selected faces (open sides)."""

    id: FeatureId
    op: Literal["shell"]
    body_ref: FeatureId
    thickness_ref: Ref
    open_faces: list[FaceSelector] = Field(min_length=1, max_length=6)
    direction: Literal["inward", "outward"] = "inward"


class Mirror(_Strict):
    """Mirror a body across a principal plane.

    ``offset_ref`` places the mirror plane along its own axis: z = offset for XY, y = offset for
    XZ, x = offset for YZ. With keep_original the result is the body plus its mirror image. The
    two halves must touch, unless the result is a tool that a later boolean merges into a body.
    """

    id: FeatureId
    op: Literal["mirror"]
    body_ref: FeatureId
    plane: Plane
    offset_ref: Ref | None = None  # plane position along its axis, not along the sketch normal
    keep_original: bool = True


class LinearPattern(_Strict):
    """``count`` copies of a body, ``spacing`` apart along +direction (the original is copy 1)."""

    id: FeatureId
    op: Literal["linear_pattern"]
    body_ref: FeatureId
    direction: Axis
    count_ref: Ref
    spacing_ref: Ref


class PolarPattern(_Strict):
    """``count`` copies of a body about a global axis through the origin.

    A full 360 deg pattern spaces copies 360/count apart; a smaller angle_ref is the angle from
    the first copy to the last.
    """

    id: FeatureId
    op: Literal["polar_pattern"]
    body_ref: FeatureId
    axis: Axis = "Z"
    count_ref: Ref
    angle_ref: Ref | None = None


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
    diameter_ref: Ref | None = None  # only circular edges of this diameter (e.g. the hub's Ø80 junction)
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


FEATURE_TYPES = (
    CenteredRectangle,
    Circle,
    Slot,
    Profile,
    Path,
    Helix,
    Extrude,
    SteppedShaft,
    Revolve,
    Sweep,
    Loft,
    Hole,
    CornerHolePattern,
    LinearHolePattern,
    PolarHolePattern,
    Pocket,
    Boolean,
    Shell,
    Mirror,
    LinearPattern,
    PolarPattern,
    Fillet,
    Chamfer,
)
Feature = Annotated[Union[FEATURE_TYPES], Field(discriminator="op")]

SKETCH_OPS = {"centered_rectangle", "circle", "slot", "profile"}
PATH_OPS = {"path", "helix"}
HOLE_OPS = {"hole", "corner_hole_pattern", "linear_hole_pattern", "polar_hole_pattern"}
ALL_OPS = {t.model_fields["op"].annotation.__args__[0] for t in FEATURE_TYPES}


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
    schema_version: Literal["1.0", "1.1"] = SCHEMA_VERSION
    name: str | None = None
    intent: Literal["engineering_cad"] = "engineering_cad"
    units: LengthUnit = "mm"
    parameters: dict[ParamName, float | Param]
    frame: Frame = Field(default_factory=Frame)
    features: list[Feature] = Field(min_length=1, max_length=MAX_FEATURES)
    output: FeatureId | None = None
    assertions: Assertions = Field(default_factory=Assertions)
    exports: list[Literal["STEP", "STL", "GLB", "FCSTD"]] = Field(default_factory=lambda: ["STEP", "STL", "GLB"])
    assumptions: list[Assumption] = Field(default_factory=list)
