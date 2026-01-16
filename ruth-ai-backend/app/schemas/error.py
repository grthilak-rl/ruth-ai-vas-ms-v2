"""Pydantic schemas for API error responses.

Consistent error format for all API endpoints.
"""

from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard error response format."""

    error: str = Field(..., description="Error type/code")
    message: str = Field(..., description="Human-readable error message")
    status_code: int = Field(..., description="HTTP status code")
    details: dict[str, Any] | None = Field(
        None, description="Additional error details"
    )
    request_id: str | None = Field(None, description="Request ID for tracing")


class ValidationErrorDetail(BaseModel):
    """Detail for a single validation error."""

    loc: list[str | int] = Field(..., description="Error location path")
    msg: str = Field(..., description="Error message")
    type: str = Field(..., description="Error type")


class ValidationErrorResponse(BaseModel):
    """Response for validation errors (422)."""

    error: str = Field(default="validation_error", description="Error type")
    message: str = Field(
        default="Request validation failed", description="Error message"
    )
    status_code: int = Field(default=422, description="HTTP status code")
    details: list[ValidationErrorDetail] = Field(
        ..., description="Validation error details"
    )
