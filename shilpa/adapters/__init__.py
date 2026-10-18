"""CAD adapters. Each declares its operation vocabulary and export capabilities.

The capability matrix lives here (not in the adapter module) so control-plane
processes can check plans without importing the geometry kernel.
"""

from ..contracts.ir import ALL_OPS

CAPABILITY_MATRIX: dict[str, dict] = {
    "build123d": {"operations": set(ALL_OPS), "exports": {"STEP", "STL", "GLB"}},
}

DEFAULT_ADAPTER = "build123d"
CAPABILITIES: set[str] = CAPABILITY_MATRIX[DEFAULT_ADAPTER]["operations"]
