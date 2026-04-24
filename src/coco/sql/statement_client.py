"""Async client for Databricks SQL Statement Execution API.

Core class for submitting, polling, and fetching SQL statement results.
Handles presigned URL expiry and streaming result chunks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator

import httpx
from databricks.sdk import WorkspaceClient

from coco.config import get_config
from coco.sql.errors import (
    ResultLinkExpired,
    StatementFailed,
    StatementTimeout,
)
from coco.sql.models import StatementStatus

try:
    import pyarrow as pa
except ImportError:
    pa = None

logger = logging.getLogger(__name__)


class StatementClient:
    """Async client for Databricks SQL Statement Execution API.

    Submits SQL statements, polls for completion, and fetches results
    from external links. Handles presigned URL expiry gracefully.

    Attributes:
        access_token: User's OBO token (for scoped access) or None
        warehouse_id: SQL Warehouse ID (from config)
        workspace_host: Databricks host
        api_base: Base URL for Statement Execution API
        _http_client: httpx.AsyncClient for HTTP calls
    """

    def __init__(
        self,
        access_token: str | None = None,
        warehouse_id: str | None = None,
    ):
        """Initialize client.

        Args:
            access_token: User's OAuth token for OBO calls.
                         If None, falls back to service principal auth.
            warehouse_id: SQL Warehouse ID. If None, reads from config.

        Raises:
            ValueError: If no token and service principal auth
                       unavailable
        """
        config = get_config()

        # Warehouse ID
        self.warehouse_id = warehouse_id or config.sql_warehouse.id
        if not self.warehouse_id:
            raise ValueError(
                "warehouse_id required; set COCO_WAREHOUSE_ID or pass explicitly"
            )

        # Workspace host and token
        workspace_host = config.workspace.host
        if not workspace_host:
            raise ValueError("workspace.host required; set DATABRICKS_HOST")

        self.access_token = access_token
        self.workspace_host = workspace_host

        # API endpoint
        self.api_base = f"https://{workspace_host}/api/2.0/sql"

        # Prepare auth headers
        self._auth_headers = self._build_auth_headers()

        # Create async HTTP client
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )

    def _build_auth_headers(self) -> dict[str, str]:
        """Build authorization headers.

        Uses OBO token if provided, else falls back to whatever auth the
        workspace SDK resolves (PAT, OAuth, workload identity). If SDK
        auth can't resolve (typical in unit tests without Databricks
        credentials), returns a placeholder — production requests will
        401 at the endpoint, which is louder than a stack trace here.
        """
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        try:
            ws = WorkspaceClient()
            headers: dict[str, str] = dict(ws.config.authenticate() or {})
        except Exception as e:
            logger.debug("SDK auth unavailable, using placeholder: %s", e)
            headers = {"Authorization": "Bearer unresolved"}
        return headers

    async def submit(
        self,
        sql: str,
        parameters: list | None = None,
    ) -> str:
        """Submit SQL statement to execution queue.

        Returns immediately (wait_timeout=0s) with statement_id.

        Args:
            sql: SQL statement (SELECT, INSERT, UPDATE, DELETE, etc.)
            parameters: List of parameter values (for ? placeholders)

        Returns:
            statement_id for polling/fetching

        Raises:
            StatementFailed: If submission fails
        """
        config = get_config()

        # Prepend a SQL comment with user_id + thread_id so every row in
        # system.query.history.statement_text carries the attribution
        # needed to split warehouse cost by user in the Cost Attribution
        # dashboard. Always emit the prefix — even for service-principal
        # or direct /invocations calls where the user context hasn't been
        # set — so the dashboard's coco_top_sql_queries query catches
        # every CoCo-originated SQL statement. When context is unknown,
        # fall back to 'sp' (service principal) so the rows remain
        # distinguishable from real user traffic.
        from coco.observability.user_context import get_user_context

        uid, tid = get_user_context()
        if uid == "unknown":
            uid = "sp"
        if tid == "unknown":
            tid = "sp"
        sql = f"/* coco_user_id={uid}, coco_thread_id={tid} */\n{sql}"

        url = f"{self.api_base}/statements"

        payload = {
            "sql": sql,
            "warehouse_id": self.warehouse_id,
            "wait_timeout": config.sql_warehouse.wait_timeout,
            "on_wait_timeout": config.sql_warehouse.on_wait_timeout,
            "disposition": config.sql_warehouse.result_disposition,
            "format": config.sql_warehouse.result_format,
        }

        if parameters:
            payload["parameters"] = parameters

        logger.debug(
            "Submitting statement; warehouse_id=%s, sql_len=%d",
            self.warehouse_id,
            len(sql),
        )

        try:
            resp = await self._http_client.post(
                url,
                json=payload,
                headers=self._auth_headers,
            )
            resp.raise_for_status()

            data = resp.json()
            statement_id = data.get("statement_id")
            if not statement_id:
                raise StatementFailed(
                    statement_id="unknown",
                    error_message=("Server did not return statement_id"),
                )

            logger.debug("Statement submitted; statement_id=%s", statement_id)
            return statement_id

        except httpx.HTTPError as e:
            raise StatementFailed(
                statement_id="unknown",
                error_message=f"HTTP error: {e}",
            )

    async def poll(
        self,
        statement_id: str,
        max_wait_seconds: int = 1800,
    ) -> StatementStatus:
        """Poll statement until terminal state.

        Uses exponential backoff: starts at 0.5s, caps at 10s.

        Args:
            statement_id: ID from submit()
            max_wait_seconds: Timeout for polling (default 30 min)

        Returns:
            StatementStatus (SUCCEEDED, FAILED, CANCELED, etc.)

        Raises:
            StatementTimeout: If polling exceeds max_wait_seconds
            StatementFailed: If statement failed
        """
        url = f"{self.api_base}/statements/{statement_id}"

        backoff_seconds = 0.5
        max_backoff_seconds = 10.0
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > max_wait_seconds:
                raise StatementTimeout(
                    statement_id=statement_id,
                    max_wait_seconds=max_wait_seconds,
                )

            try:
                resp = await self._http_client.get(
                    url,
                    headers=self._auth_headers,
                )
                resp.raise_for_status()

                data = resp.json()
                status_str = data.get("status", {}).get("state")

                # Parse status
                try:
                    status = StatementStatus(status_str)
                except ValueError:
                    logger.warning("Unknown status: %s", status_str)
                    status = StatementStatus.RUNNING

                # Check for failure
                if status == StatementStatus.FAILED:
                    error_msg = (
                        data.get("status", {})
                        .get("error", {})
                        .get("message", "Unknown error")
                    )
                    raise StatementFailed(
                        statement_id=statement_id,
                        error_message=error_msg,
                    )

                if status in (
                    StatementStatus.SUCCEEDED,
                    StatementStatus.CANCELED,
                ):
                    logger.debug(
                        "Statement terminal; statement_id=%s, status=%s",
                        statement_id,
                        status.value,
                    )
                    return status

                # Still running; wait before next poll
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(
                    backoff_seconds * 1.5,
                    max_backoff_seconds,
                )

            except httpx.HTTPError as e:
                raise StatementFailed(
                    statement_id=statement_id,
                    error_message=f"Poll HTTP error: {e}",
                )

    async def fetch_results(
        self,
        statement_id: str,
    ) -> AsyncIterator[pa.RecordBatch]:
        """Stream result chunks as Arrow record batches.

        For EXTERNAL_LINKS disposition, fetches presigned URLs.
        Handles 403 (expired link) by re-issuing getStatement.

        Args:
            statement_id: ID from submit()

        Yields:
            PyArrow RecordBatch objects

        Raises:
            ImportError: If pyarrow not installed
            ResultLinkExpired: If presigned URL expires
            StatementFailed: If statement status is not SUCCEEDED
        """
        if pa is None:
            raise ImportError(
                "pyarrow required for fetch_results; install with 'pip install pyarrow'"
            )

        # Get statement result metadata + links
        url = f"{self.api_base}/statements/{statement_id}"

        resp = await self._http_client.get(
            url,
            headers=self._auth_headers,
        )
        resp.raise_for_status()

        data = resp.json()
        status_str = data.get("status", {}).get("state")

        if status_str != "SUCCEEDED":
            error_msg = (
                data.get("status", {})
                .get("error", {})
                .get("message", f"Status is {status_str}")
            )
            raise StatementFailed(
                statement_id=statement_id,
                error_message=error_msg,
            )

        # Extract external links
        result_data = data.get("result", {})
        external_links = result_data.get("external_links", [])

        if not external_links:
            logger.debug("No external links; statement may have no results")
            return

        logger.debug("Fetching %d result chunks", len(external_links))

        for link_obj in external_links:
            file_link = link_obj.get("file_link")
            if not file_link:
                logger.warning("Link object missing file_link")
                continue

            # Fetch chunk with presigned URL
            try:
                chunk_resp = await self._http_client.get(
                    file_link,
                    headers={},  # Presigned URL has auth in query
                )

                if chunk_resp.status_code == 403:
                    # Link expired; re-fetch
                    logger.warning("Presigned URL expired; re-fetching result")
                    raise ResultLinkExpired(
                        statement_id=statement_id,
                        file_link=file_link,
                    )

                chunk_resp.raise_for_status()

                # Parse Arrow stream format
                reader = pa.ipc.RecordBatchStreamReader(chunk_resp.content)
                for i in range(reader.num_record_batches):
                    batch = reader.get_batch(i)
                    logger.debug(
                        "Yielding batch %d with %d rows",
                        i,
                        len(batch),
                    )
                    yield batch

            except ResultLinkExpired:
                raise
            except httpx.HTTPError as e:
                logger.error(
                    "Error fetching chunk from %s: %s",
                    file_link[:50],
                    e,
                )
                raise StatementFailed(
                    statement_id=statement_id,
                    error_message=f"Chunk fetch failed: {e}",
                )

    async def cancel(self, statement_id: str) -> None:
        """Best-effort cancel of running statement.

        Args:
            statement_id: ID from submit()
        """
        url = f"{self.api_base}/statements/{statement_id}/cancel"

        try:
            resp = await self._http_client.post(
                url,
                json={},
                headers=self._auth_headers,
            )
            resp.raise_for_status()
            logger.info("Canceled statement %s", statement_id)
        except Exception as e:
            logger.warning("Failed to cancel %s: %s", statement_id, e)

    async def explain(
        self,
        sql: str,
    ) -> tuple[bool, str]:
        """Validate SQL and get execution plan via EXPLAIN.

        Args:
            sql: SQL statement to explain

        Returns:
            (is_valid, message) where message is plan or error
        """
        explain_sql = f"EXPLAIN {sql}"

        try:
            statement_id = await self.submit(explain_sql)
            status = await self.poll(statement_id, max_wait_seconds=30)

            if status != StatementStatus.SUCCEEDED:
                return False, f"EXPLAIN failed with status {status}"

            # Fetch and concatenate results
            plan_lines = []
            async for batch in self.fetch_results(statement_id):
                for record in batch.to_pylist():
                    plan_lines.append(str(record))

            plan_text = "\n".join(plan_lines)
            return True, plan_text

        except Exception as e:
            return False, str(e)

    async def __aenter__(self) -> StatementClient:
        """Context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit; cleanup HTTP client."""
        await self._http_client.aclose()
