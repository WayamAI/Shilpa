"""Nominal material densities for mass estimates on catalog parts and weldments.

Values are typical handbook densities in g/cm3. They are estimates for BOM mass
roll-ups, not a material database: alloys vary by a few percent.
"""

from __future__ import annotations

from ..contracts.errors import ErrorCode, ShilpaError

DENSITY_G_CM3: dict[str, float] = {
    "steel": 7.85,
    "chromoly": 7.85,  # AISI 4130
    "stainless": 8.00,
    "aluminium": 2.70,
    "aluminium_6061": 2.70,
    "aluminium_7075": 2.81,
    "titanium": 4.43,  # Ti-3Al-2.5V / Ti-6Al-4V
    "brass": 8.50,
    "bronze": 8.80,
    "carbon_fibre": 1.55,  # cured CFRP laminate
    "nylon": 1.15,
    "rubber": 1.20,
    "polyurethane": 1.20,
}

ALIASES = {"aluminum": "aluminium", "carbon": "carbon_fibre", "cfrp": "carbon_fibre", "4130": "chromoly", "ss": "stainless"}


def density(material: str) -> float:
    key = ALIASES.get(material.strip().lower(), material.strip().lower())
    try:
        return DENSITY_G_CM3[key]
    except KeyError:
        raise ShilpaError(
            ErrorCode.INVALID_PARAMETER,
            f"unknown material {material!r}; known: {sorted(DENSITY_G_CM3)}",
            field="material",
        ) from None


def mass_g(volume_mm3: float, material: str) -> float:
    """Mass in grams of ``volume_mm3`` of ``material`` (1 cm3 = 1000 mm3)."""
    return round(volume_mm3 * density(material) / 1000.0, 3)
