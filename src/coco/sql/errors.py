"""Custom exceptions for SQL layer."""
from __future__ import annotations


class StatementExecutionError(Exception):
    """Base class for statement execution errors."""

    pass


class StatementFailed(StatementExecutionError):
    """Statement execution failed with error message."""

    def __init__(
        self,
        statement_id: str,
        error_message: str,
    ):
        self.statement_id = statement_id
        self.error_message = error_message
        super().__init__(
            f"Statement {statement_id} failed: {error_message}"
        )


class StatementTimeout(StatementExecutionError):
    """Statement polling exceeded max_wait_seconds."""

    def __init__(
        self,
        statement_id: str,
        max_wait_seconds: int,
    ):
        self.statement_id = statement_id
        self.max_wait_seconds = max_wait_seconds
        super().__init__(
            f"Statement {statement_id} timed out after "
            f"{max_wait_seconds}s"
        )


class ResultLinkExpired(StatementExecutionError):
    """Presigned URL for result chunk expired (403 Forbidden).

    Client should retry getStatement to get fresh links.
    """

    def __init__(
        self,
        statement_id: str,
        file_link: str,
    ):
        self.statement_id = statement_id
        self.file_link = file_link
        super().__init__(
            f"Result link expired for statement {statement_id}. "
            f"Re-fetch result links via getStatement."
        )
