"""SQL Statement Execution API layer for async SQL execution.

Provides async client for Databricks SQL Warehouse via Statement Execution API.
Handles statement submission, polling, result fetching with external links.
"""
from __future__ import annotations

from coco.sql.errors import (
    ResultLinkExpired,
    StatementFailed,
    StatementTimeout,
)
from coco.sql.models import (
    ColumnMeta,
    ExternalLink,
    StatementResult,
    StatementStatus,
    StatementSubmission,
)
from coco.sql.statement_client import StatementClient

__all__ = [
    "StatementClient",
    "StatementSubmission",
    "StatementStatus",
    "StatementResult",
    "ExternalLink",
    "ColumnMeta",
    "StatementFailed",
    "StatementTimeout",
    "ResultLinkExpired",
]
