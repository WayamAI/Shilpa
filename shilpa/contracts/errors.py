"""Typed failures shared by the planner, adapters, validators and API.

Every failure that crosses a boundary is a ShilpaError with a stable code, so the
repair planner, the job state machine and the studio can act on it without
parsing message text.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class ErrorCode(str, Enum):
    # Recipe / specification problems (422 class, not retryable without a change)
    INVALID_SCHEMA = "invalid_schema"
    INVALID_PARAMETER = "invalid_parameter"
    UNKNOWN_REFERENCE = "unknown_reference"
    REFERENCE_CYCLE = "reference_cycle"
    UNIT_MISMATCH = "unit_mismatch"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    PRECONDITION_FAILED = "precondition_failed"
    # Geometry execution problems (repairable by the planner)
    SELECTOR_EMPTY = "selector_empty"
    SELECTOR_AMBIGUOUS = "selector_ambiguous"
    KERNEL_FAILURE = "kernel_failure"
    # Post-build checks
    VALIDATION_FAILED = "validation_failed"
    EXPORT_FAILED = "export_failed"
    # Workflow
    BUDGET_EXHAUSTED = "budget_exhausted"
    MODEL_REFUSAL = "model_refusal"
    MODEL_TRUNCATED = "model_truncated"
    MODEL_TIMEOUT = "model_timeout"
    CLARIFICATION_REQUIRED = "clarification_required"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


# Errors the repair planner is allowed to attempt to fix (blueprint section 9).
REPAIRABLE = {
    ErrorCode.KERNEL_FAILURE,
    ErrorCode.SELECTOR_EMPTY,
    ErrorCode.SELECTOR_AMBIGUOUS,
    ErrorCode.PRECONDITION_FAILED,
    ErrorCode.INVALID_SCHEMA,
    ErrorCode.UNKNOWN_REFERENCE,
    ErrorCode.UNSUPPORTED_OPERATION,
}


class ErrorInfo(BaseModel):
    code: ErrorCode
    message: str
    feature_id: str | None = None
    field: str | None = None
    retryable: bool = False
    details: dict[str, Any] | None = None


class ShilpaError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        feature_id: str | None = None,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.info = ErrorInfo(
            code=code,
            message=message,
            feature_id=feature_id,
            field=field,
            retryable=code in REPAIRABLE,
            details=details,
        )

    @property
    def code(self) -> ErrorCode:
        return self.info.code

    def __str__(self) -> str:
        where = f" [{self.info.feature_id}.{self.info.field}]" if self.info.feature_id else ""
        return f"{self.info.code.value}{where}: {self.info.message}"
