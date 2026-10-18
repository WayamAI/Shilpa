"""Restricted, typed expression language for recipe references (blueprint section 8).

A reference is a string such as ``"width"`` or ``"width / 2 - edge_offset"``.
It is parsed with Python's ``ast`` module purely as a syntax tree and walked by a
whitelist interpreter: numeric constants, parameter names, + - * / and unary minus.
Nothing is ever passed to ``eval``. Each value carries a quantity kind so a length
can never be silently used as an angle.
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from typing import Literal

from .errors import ErrorCode, ShilpaError

Kind = Literal["length", "angle", "count", "ratio"]
SCALAR_KINDS = ("count", "ratio")
MAX_DEPTH = 12
MAX_LEN = 200


@dataclass(frozen=True)
class Quantity:
    value: float
    kind: Kind


def _fail(code: ErrorCode, msg: str) -> ShilpaError:
    return ShilpaError(code, msg)


def parse(text: str) -> ast.expr:
    if not isinstance(text, str) or not text.strip():
        raise _fail(ErrorCode.INVALID_PARAMETER, "empty reference")
    if len(text) > MAX_LEN:
        raise _fail(ErrorCode.INVALID_PARAMETER, f"reference longer than {MAX_LEN} characters")
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as exc:
        raise _fail(ErrorCode.INVALID_PARAMETER, f"cannot parse reference {text!r}: {exc.msg}")
    _check(tree.body, 0)
    return tree.body


def _check(node: ast.AST, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise _fail(ErrorCode.INVALID_PARAMETER, "reference expression too deep")
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        _check(node.left, depth + 1)
        _check(node.right, depth + 1)
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        _check(node.operand, depth + 1)
    elif isinstance(node, ast.Name):
        pass
    elif isinstance(node, ast.Constant) and type(node.value) in (int, float):
        pass
    else:
        raise _fail(
            ErrorCode.INVALID_PARAMETER,
            f"unsupported syntax {type(node).__name__} in reference; only numbers, "
            "parameter names, + - * / and parentheses are allowed",
        )


def names(text: str) -> set[str]:
    return {n.id for n in ast.walk(parse(text)) if isinstance(n, ast.Name)}


def evaluate(text: str, scope: dict[str, Quantity]) -> Quantity:
    return _eval(parse(text), scope)


def _eval(node: ast.AST, scope: dict[str, Quantity]) -> Quantity:
    if isinstance(node, ast.Constant):
        # Bare constants are dimensionless; they adopt the kind of their partner in + and -.
        return Quantity(float(node.value), "ratio")
    if isinstance(node, ast.Name):
        if node.id not in scope:
            raise _fail(ErrorCode.UNKNOWN_REFERENCE, f"unknown parameter {node.id!r}")
        return scope[node.id]
    if isinstance(node, ast.UnaryOp):
        q = _eval(node.operand, scope)
        return Quantity(-q.value if isinstance(node.op, ast.USub) else q.value, q.kind)
    assert isinstance(node, ast.BinOp)
    a, b = _eval(node.left, scope), _eval(node.right, scope)
    if isinstance(node.op, (ast.Add, ast.Sub)):
        kind = _additive_kind(a, b, node)
        v = a.value + b.value if isinstance(node.op, ast.Add) else a.value - b.value
        return Quantity(v, kind)
    if isinstance(node.op, ast.Mult):
        if a.kind in SCALAR_KINDS:
            return Quantity(a.value * b.value, b.kind if b.kind not in SCALAR_KINDS else "ratio")
        if b.kind in SCALAR_KINDS:
            return Quantity(a.value * b.value, a.kind)
        raise _fail(ErrorCode.UNIT_MISMATCH, f"cannot multiply {a.kind} by {b.kind} in {ast.unparse(node)!r}")
    # Division
    if b.value == 0:
        raise _fail(ErrorCode.INVALID_PARAMETER, f"division by zero in {ast.unparse(node)!r}")
    if b.kind in SCALAR_KINDS:
        return Quantity(a.value / b.value, a.kind)
    if a.kind == b.kind:
        return Quantity(a.value / b.value, "ratio")
    raise _fail(ErrorCode.UNIT_MISMATCH, f"cannot divide {a.kind} by {b.kind} in {ast.unparse(node)!r}")


def _additive_kind(a: Quantity, b: Quantity, node: ast.AST) -> Kind:
    if a.kind == b.kind:
        return a.kind
    if a.kind in SCALAR_KINDS and b.kind in SCALAR_KINDS:
        return "ratio"
    # Allow a bare constant next to a dimensioned value: "width - 10" means 10 of the same kind.
    if a.kind in SCALAR_KINDS and isinstance(getattr(node, "left", None), ast.Constant):
        return b.kind
    if b.kind in SCALAR_KINDS and isinstance(getattr(node, "right", None), ast.Constant):
        return a.kind
    raise _fail(ErrorCode.UNIT_MISMATCH, f"cannot add {a.kind} and {b.kind} in {ast.unparse(node)!r}")


def finite(q: Quantity, where: str) -> Quantity:
    if not math.isfinite(q.value):
        raise _fail(ErrorCode.INVALID_PARAMETER, f"non-finite value for {where}")
    return q
