"""Tests for the Databricks SQL Statement Execution API client.

StatementClient is async and talks to the Statement Execution REST API
directly via httpx (not via the SDK's statement_execution helper). The
tests here focus on construction, auth header resolution, and URL
shaping — the parts a reader can validate without real
Databricks credentials. Full async HTTP flow testing is deferred to
integration tests that run against a real warehouse.
"""

import pytest

from coco.sql.errors import (
    ResultLinkExpired,
    StatementExecutionError,
    StatementFailed,
    StatementTimeout,
)
from coco.sql.statement_client import StatementClient


@pytest.mark.unit
class TestStatementClientConstruction:
    """Construction, config resolution, and URL shaping."""

    def test_with_explicit_token_and_warehouse(self) -> None:
        client = StatementClient(
            access_token="dapi-test-token",
            warehouse_id="wh-123",
        )
        assert client.warehouse_id == "wh-123"
        assert client.access_token == "dapi-test-token"
        assert client.api_base.endswith("/api/2.0/sql")

    def test_auth_header_prefers_obo_token(self) -> None:
        client = StatementClient(
            access_token="dapi-test-token",
            warehouse_id="wh-123",
        )
        headers = client._build_auth_headers()
        assert headers["Authorization"] == "Bearer dapi-test-token"

    def test_auth_header_without_token_falls_back_gracefully(self) -> None:
        """Without a token the SDK fallback kicks in. In a unit-test env
        with no Databricks credentials the fallback returns a placeholder
        rather than raising, so the client can still be constructed."""
        client = StatementClient(warehouse_id="wh-123")
        headers = client._build_auth_headers()
        # Either real resolved auth (CI with creds) or placeholder (local)
        assert "Authorization" in headers

    def test_missing_warehouse_id_raises(self) -> None:
        import os

        prior = os.environ.pop("COCO_WAREHOUSE_ID", None)
        try:
            with pytest.raises(ValueError, match="warehouse_id"):
                StatementClient(access_token="dapi-test-token")
        finally:
            if prior is not None:
                os.environ["COCO_WAREHOUSE_ID"] = prior


@pytest.mark.unit
class TestStatementErrorHierarchy:
    """The custom exceptions the client raises."""

    def test_failed_includes_statement_id_and_message(self) -> None:
        err = StatementFailed(
            statement_id="stmt-123",
            error_message="Table not found",
        )
        assert err.statement_id == "stmt-123"
        assert "Table not found" in str(err)
        assert isinstance(err, StatementExecutionError)

    def test_timeout_includes_max_wait(self) -> None:
        err = StatementTimeout(statement_id="stmt-123", max_wait_seconds=1800)
        assert err.max_wait_seconds == 1800
        assert isinstance(err, StatementExecutionError)

    def test_link_expired_carries_file_link(self) -> None:
        err = ResultLinkExpired(
            statement_id="stmt-123",
            file_link="https://example/chunk.arrow",
        )
        assert err.file_link.endswith("chunk.arrow")
        assert isinstance(err, StatementExecutionError)
