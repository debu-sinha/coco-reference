"""Pydantic models for Statement Execution API.

Represents statement submission, status polling, and result structures.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class StatementStatus(str, Enum):
    """Statement execution status."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class ColumnMeta(BaseModel):
    """Column metadata from Arrow schema."""

    name: str
    type_text: str  # Arrow type string
    nullable: bool = True
    type_json: Optional[dict] = None  # Full Arrow type as JSON


class ExternalLink(BaseModel):
    """Reference to external result chunk (>25 MiB disposition)."""

    file_link: str  # Presigned URL, expires in ~1 hour
    expiration: int  # Unix timestamp


class StatementSubmission(BaseModel):
    """Response from POST /api/2.0/sql/statements."""

    statement_id: str
    status: StatementStatus


class StatementResult(BaseModel):
    """Full result from completed statement."""

    statement_id: str
    status: StatementStatus
    result_set_metadata: dict = Field(
        default_factory=dict, description="Arrow schema + row count"
    )
    external_links: list[ExternalLink] = Field(
        default_factory=list,
        description="Chunks for large results",
    )
    manifest: Optional[dict] = Field(
        default=None, description="Row group manifests"
    )
    chunks: Optional[dict] = Field(
        default=None, description="Chunk metadata"
    )
    error_message: Optional[str] = None
    statement_type: Optional[str] = None
    row_count: Optional[int] = None
