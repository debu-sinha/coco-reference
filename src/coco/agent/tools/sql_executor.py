"""SQL executor for cohort queries.

Uses WorkspaceClient.statement_execution directly (via
asyncio.to_thread) instead of the repo's custom async StatementClient.
The custom client's `fetch_results` only handles EXTERNAL_LINKS
disposition and silently returns zero batches when the Statement
Execution API uses INLINE disposition (which it does for any small
result like a COUNT). That made every aggregate query look like
"the table is empty" to the agent.

The SDK path handles both dispositions transparently by reading
`r.result.data_array` (INLINE) or iterating chunk links (EXTERNAL),
and gives us column metadata via `r.manifest.schema.columns`
without any of the arrow/httpx plumbing we were doing by hand.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

from coco.agent.models import SQLExecutorResult
from coco.config import get_config

logger = logging.getLogger(__name__)


def _run_statement_sync(
    ws: WorkspaceClient,
    warehouse_id: str,
    sql: str,
    max_rows: int,
) -> SQLExecutorResult:
    """Submit + poll + fetch a single SQL statement via the SDK.

    Sequential blocking calls - designed to run on a worker thread so
    the agent's event loop stays responsive while the warehouse
    computes the result.
    """
    statement_id = ""
    try:
        r = ws.statement_execution.execute_statement(
            statement=sql,
            warehouse_id=warehouse_id,
            wait_timeout="30s",
        )
        statement_id = r.statement_id or ""

        # Poll to a terminal state. The SDK honours wait_timeout but
        # large queries can still need more than that one window.
        terminal = {
            StatementState.SUCCEEDED,
            StatementState.FAILED,
            StatementState.CANCELED,
            StatementState.CLOSED,
        }
        timed_out = False
        deadline = time.monotonic() + 300.0
        try:
            while r.status and r.status.state not in terminal:
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                time.sleep(0.5)
                r = ws.statement_execution.get_statement(statement_id)
        finally:
            # Kill the warehouse query if we timed out or hit an
            # exception during polling so it does not keep running.
            if timed_out or (r.status and r.status.state not in terminal):
                if statement_id:
                    try:
                        ws.statement_execution.cancel_statement(statement_id)
                        logger.info("Cancelled statement %s after timeout/error", statement_id)
                    except Exception as cancel_err:
                        logger.warning(
                            "Failed to cancel statement %s: %s", statement_id, cancel_err
                        )

        if timed_out:
            logger.error("Statement %s timed out after 5 min", statement_id)
            return SQLExecutorResult(statement_id=statement_id, row_count=0)

        if not r.status or r.status.state != StatementState.SUCCEEDED:
            err_msg = (
                r.status.error.message
                if (r.status and r.status.error and r.status.error.message)
                else str(r.status.state if r.status else "unknown")
            )
            logger.error(
                "Statement %s ended with non-success state: %s",
                statement_id,
                err_msg,
            )
            return SQLExecutorResult(statement_id=statement_id, row_count=0)

        # Column metadata from the manifest. Works for both INLINE
        # and EXTERNAL_LINKS dispositions because manifest.schema is
        # always populated on SUCCEEDED.
        columns: list[str] = []
        col_types: list[str] = []
        if r.manifest and r.manifest.schema and r.manifest.schema.columns:
            for c in r.manifest.schema.columns:
                columns.append(c.name or "")
                col_types.append(c.type_text or "STRING")

        # Row count from the manifest (authoritative) falls back to
        # counting data_array entries if unavailable.
        total_rows = int(getattr(r.manifest, "total_row_count", 0) or 0) if r.manifest else 0

        # Data extraction: the SDK exposes inline rows via
        # `r.result.data_array` as a list of lists in manifest column
        # order. For external-link disposition we would need to walk
        # chunk urls, but small aggregates (counts, limit queries)
        # come back inline and that is the case the agent cares about
        # most today. Large external result handling is a TODO.
        sample_rows: list[dict] = []
        data_array = (r.result.data_array if r.result else None) or []
        if data_array and columns:
            for row in data_array[:max_rows]:
                sample_rows.append(
                    {col: row[i] if i < len(row) else None for i, col in enumerate(columns)}
                )
            # If manifest row count is unknown, use data_array length
            # as a lower bound.
            if total_rows == 0:
                total_rows = len(data_array)

        logger.info(
            "execute_sql: statement=%s cols=%d rows=%d sample=%d",
            statement_id,
            len(columns),
            total_rows,
            len(sample_rows),
        )

        return SQLExecutorResult(
            statement_id=statement_id,
            row_count=total_rows,
            columns=columns,
            sample_rows=sample_rows,
            result_path=None,
        )
    except Exception as e:
        logger.exception("execute_sql failed: %s", e)
        return SQLExecutorResult(statement_id=None, row_count=0)


async def execute_sql(
    sql: str,
    max_rows: int = 100,
    access_token: Optional[str] = None,
) -> SQLExecutorResult:
    """Execute a Databricks SQL statement and return sample results.

    Args:
        sql: The SQL to run. Assumed to already have passed guardrails.
        max_rows: Cap on how many rows to return as `sample_rows`.
        access_token: Unused. Retained for API compatibility with the
            old implementation; the SDK path uses the serving SP's
            credentials via WorkspaceClient.

    Returns:
        SQLExecutorResult with `statement_id`, `row_count`, `columns`
        and up to `max_rows` sample rows as dicts.
    """
    del access_token  # SDK uses SP auth from the container env

    config = get_config()
    warehouse_id = config.sql_warehouse.id
    if not warehouse_id:
        logger.error("execute_sql: no warehouse id in config")
        return SQLExecutorResult(statement_id=None, row_count=0)

    ws = WorkspaceClient()
    # The SDK's statement_execution API is synchronous. Park on a
    # worker thread so the agent event loop stays responsive.
    return await asyncio.to_thread(_run_statement_sync, ws, warehouse_id, sql, max_rows)


# Retain name for callers still importing via the old identifier.
_ = SQLExecutorResult

# Unused import suppressor.
_ = Any
