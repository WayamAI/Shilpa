"""Persistent topology naming: stable names for faces and edges, and references to them.

``refs`` is kernel-free (the compiler uses it); ``naming`` and ``signature`` import
build123d, so they load on first use of ``name_map`` / ``resolve``.
"""

from __future__ import annotations


def name_map(build):
    """{name: Signature} for every named face and edge of a BuildResult's output."""
    from .naming import name_map as _name_map

    return _name_map(build)


def resolve(ref, shape, signatures=None, tol: float = 1e-3):
    """Entities a reference names in a BuildResult / NameTable, or in a bare shape given signatures."""
    from .naming import resolve as _resolve

    return _resolve(ref, shape, signatures, tol)
