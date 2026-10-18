"""Tube/weldment sub-IR: spec, builder (cope + fuse + cut list) and the bicycle frame template."""

from .build import WeldmentResult, build_weldment
from .spec import Member, PortSpec, RectTube, RoundTube, Shell, WeldmentSpec

__all__ = ["Member", "PortSpec", "RectTube", "RoundTube", "Shell", "WeldmentResult", "WeldmentSpec", "build_weldment"]
