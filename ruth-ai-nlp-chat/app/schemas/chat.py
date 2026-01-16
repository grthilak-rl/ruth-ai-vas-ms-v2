"""Pydantic schemas for chat API endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request schema for POST /chat."""

    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Natural language question about the data",
        examples=[
            "How many violations occurred today?",
            "Show me all active devices",
            "What is the most common event type?",
        ],
    )
    include_raw_data: bool = Field(
        default=False,
        description="Include raw SQL results in response",
    )


class ChatResponse(BaseModel):
    """Response schema for POST /chat."""

    answer: str = Field(..., description="Natural language answer")
    question: str = Field(..., description="Original question")
    generated_sql: str | None = Field(
        None,
        description="Generated SQL query (for debugging)",
    )
    raw_data: list[dict[str, Any]] | None = Field(
        None,
        description="Raw query results (if requested)",
    )
    row_count: int = Field(..., description="Number of rows returned")
    execution_time_ms: int = Field(..., description="Query execution time in milliseconds")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Response timestamp",
    )


class ChatErrorDetail(BaseModel):
    """Error detail for chat endpoint errors."""

    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    question: str | None = Field(None, description="Original question")
    generated_sql: str | None = Field(
        None,
        description="Generated SQL (if available)",
    )
